import asyncio
import pytest
import pytest_asyncio
from typing import AsyncGenerator
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import get_db
from app.models.base import Base
# Make sure models are imported so metadata knows about them
from app.models.user import User
from app.models.conversation import Conversation, ConversationParticipant
from app.models.message import Message
from app.models.outbox import OutboxEvent
from app.main import app

# Use the same configured database URL but clean tables before/after
engine = create_async_engine(
    settings.DATABASE_URL,
    poolclass=StaticPool,
)

TestingSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_test_db():
    async with engine.begin() as conn:
        # Reset database tables
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    async with TestingSessionLocal() as session:
        yield session
        # Ensure we rollback any changes made in tests
        await session.rollback()


@pytest_asyncio.fixture
async def client(db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


class MockPubSub:
    def __init__(self, mock_redis):
        self.mock_redis = mock_redis
        self.channels = []
        self.subscribed = False

    async def subscribe(self, channel):
        self.channels.append(channel)
        self.subscribed = True
        self.mock_redis.subscribers.append(self)

    async def unsubscribe(self, channel):
        if channel in self.channels:
            self.channels.remove(channel)
        if not self.channels:
            self.subscribed = False
            if self in self.mock_redis.subscribers:
                self.mock_redis.subscribers.remove(self)

    async def get_message(self, ignore_subscribe_messages=False, timeout=1.0):
        if not self.subscribed:
            return None
        if self.mock_redis.event_queue:
            evt = self.mock_redis.event_queue.pop(0)
            return {"type": "message", "channel": evt["channel"], "data": evt["data"]}
        await asyncio.sleep(0.01)
        return None

    async def close(self):
        self.subscribed = False
        if self in self.mock_redis.subscribers:
            self.mock_redis.subscribers.remove(self)


class MockRedis:
    def __init__(self):
        self.lists = {}
        self.zsets = {}
        self.fail_ping = False
        self.fail_rpush = False
        self.subscribers = []
        self.event_queue = []

    async def ping(self):
        if self.fail_ping:
            raise ConnectionError("Redis is offline")
        return True

    async def publish(self, channel, message):
        evt = {"channel": channel, "data": message}
        self.event_queue.append(evt)
        return len(self.subscribers)

    def pubsub(self):
        return MockPubSub(self)

    async def rpush(self, key, value):
        if self.fail_rpush:
            raise ConnectionError("Redis write failed")
        if key not in self.lists:
            self.lists[key] = []
        self.lists[key].append(value)
        return len(self.lists[key])

    async def blpop(self, key, timeout=0):
        if key not in self.lists or not self.lists[key]:
            await asyncio.sleep(0.01)
            return None
        val = self.lists[key].pop(0)
        return (key, val)

    async def zadd(self, key, mapping):
        if key not in self.zsets:
            self.zsets[key] = []
        for member, score in mapping.items():
            self.zsets[key] = [x for x in self.zsets[key] if x[0] != member]
            self.zsets[key].append((member, score))
        self.zsets[key].sort(key=lambda x: x[1])
        return len(mapping)

    async def zrangebyscore(self, key, min_score, max_score):
        if key not in self.zsets:
            return []
        res = []
        for member, score in self.zsets[key]:
            if min_score <= score <= max_score:
                res.append(member)
        return res

    async def zrem(self, key, member):
        if key not in self.zsets:
            return 0
        original_len = len(self.zsets[key])
        self.zsets[key] = [x for x in self.zsets[key] if x[0] != member]
        return original_len - len(self.zsets[key])

    async def lrange(self, key, start, end):
        if key not in self.lists:
            return []
        return self.lists[key]


@pytest.fixture(autouse=True)
def mock_redis_injection(monkeypatch):
    mock_r = MockRedis()
    monkeypatch.setattr("app.queue.client.redis_client", mock_r)
    monkeypatch.setattr("app.queue.producer.redis_client", mock_r)
    monkeypatch.setattr("app.queue.consumer.redis_client", mock_r)
    monkeypatch.setattr("app.queue.retry.redis_client", mock_r)
    monkeypatch.setattr("app.worker.worker.redis_client", mock_r)
    monkeypatch.setattr("app.events.publisher.redis_client", mock_r)
    monkeypatch.setattr("app.events.subscriber.redis_client", mock_r)
    monkeypatch.setattr("app.events.outbox_publisher.redis_client", mock_r)
    return mock_r

