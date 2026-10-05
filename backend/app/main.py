from fastapi import FastAPI, Response, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from app.core.config import settings
from app.api.routes import auth, users, conversations, scheduled_messages
from app.websocket import endpoint

import asyncio
from contextlib import asynccontextmanager
from app.events.subscriber import start_subscriber
from app.events.outbox_publisher import start_outbox_publisher, start_outbox_cleanup_daemon

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Launch background subscriber, publisher, and cleanup loops
    sub_task = asyncio.create_task(start_subscriber())
    pub_task = asyncio.create_task(start_outbox_publisher())
    clean_task = asyncio.create_task(start_outbox_cleanup_daemon())
    yield
    # Shutdown
    sub_task.cancel()
    pub_task.cancel()
    clean_task.cancel()
    try:
        await asyncio.gather(sub_task, pub_task, clean_task, return_exceptions=True)
    except Exception:
        pass

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Latext Messaging Platform API - Phase 1 MVP",
    version="1.0.0",
    lifespan=lifespan
)

# CORS configuration
if settings.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Include REST Routers
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(conversations.router)
app.include_router(scheduled_messages.router)

# Include WebSocket Router
app.include_router(endpoint.router)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "project": settings.PROJECT_NAME}


@app.get("/ready")
async def readiness_check(
    db: AsyncSession = Depends(get_db)
):
    from sqlalchemy import select
    from app.queue.client import check_redis_health
    from fastapi import HTTPException
    
    # 1. Verify Database
    try:
        await db.execute(select(1))
    except Exception as db_err:
        raise HTTPException(status_code=503, detail=f"Database connection failed: {db_err}")
        
    # 2. Verify Redis
    try:
        redis_ok = await check_redis_health()
        if not redis_ok:
            raise HTTPException(status_code=503, detail="Redis connection failed")
    except Exception as redis_err:
        raise HTTPException(status_code=503, detail=f"Redis connection failed: {redis_err}")
        
    return {"status": "ready"}


@app.get("/metrics")
async def get_metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
