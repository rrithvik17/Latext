# Latext — Distributed, Timezone-Aware Scheduled Messaging Platform

[![CI Pipeline](https://github.com/latext/latext/actions/workflows/ci.yml/badge.svg)](https://github.com/latext/latext/actions/workflows/ci.yml)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?logo=fastapi)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Next.js-14-black?logo=next.js)](https://nextjs.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?logo=postgresql)](https://www.postgresql.org)
[![Redis](https://img.shields.io/badge/Redis-7-DC382D?logo=redis)](https://redis.io)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-1.28-326CE5?logo=kubernetes)](https://kubernetes.io)
[![KEDA](https://img.shields.io/badge/KEDA-Autoscaling-FF8000?logo=kubernetes)](https://keda.sh)

> **"Messages, exactly when they matter."**
> A modern, WhatsApp-inspired messaging application built on top of a highly resilient, horizontally scalable distributed systems architecture.

---

## 🏗️ Architecture Overview

Latext separates real-time user-facing API interactions from asynchronous background schedule coordination and reliable multi-pod WebSocket message delivery:

```mermaid
flowchart TD
    subgraph Clients["Clients"]
        BrowserA["Web Client (User A)"]
        BrowserB["Web Client (User B)"]
    end

    subgraph Ingress["Ingress & Frontend"]
        NextJS["Next.js 14 Frontend<br/>(Tailwind CSS)"]
    end

    subgraph BackendCluster["Backend API Layer (FastAPI)"]
        API1["Backend Pod 1<br/>(FastAPI + WebSockets)"]
        API2["Backend Pod 2<br/>(FastAPI + WebSockets)"]
        OutboxTask["Outbox Publisher<br/>(Async Worker Daemon)"]
    end

    subgraph DataStorage["Data & Event Tier"]
        Postgres[("PostgreSQL 16 (StatefulSet)<br/>• Users & Conversations<br/>• Messages & Outbox Events<br/>• Scheduled Messages")]
        RedisQueue[("Redis 7.0<br/>• latext:scheduled:queue<br/>• latext:scheduled:retry<br/>• latext:scheduled:dead-letter")]
        RedisPubSub[("Redis Pub/Sub<br/>• latext:events (Fanout)")]
    end

    subgraph WorkerCluster["Asynchronous Processing Layer"]
        Scheduler["Scheduler Daemon<br/>(Singleton Leader)"]
        Worker1["Worker Pod 1<br/>(Stateless Consumer)"]
        Worker2["Worker Pod 2<br/>(Stateless Consumer)"]
        KEDA["KEDA Autoscaler<br/>(Queue-Length Driven)"]
    end

    BrowserA <-->|HTTP / WS| NextJS
    BrowserB <-->|HTTP / WS| NextJS
    NextJS <-->|REST API| API1
    NextJS <-->|REST API| API2
    NextJS <-->|WebSocket Stream| API1
    NextJS <-->|WebSocket Stream| API2

    API1 -->|ACID Writes| Postgres
    API2 -->|ACID Writes| Postgres
    OutboxTask -->|Poll Outbox| Postgres
    OutboxTask -->|Publish| RedisPubSub

    Scheduler -->|Claim Due Jobs| Postgres
    Scheduler -->|LPUSH Due Jobs| RedisQueue
    Worker1 -->|BRPOP Job| RedisQueue
    Worker2 -->|BRPOP Job| RedisQueue
    KEDA -.->|Scale Workers| WorkerCluster

    Worker1 -->|Process Message| Postgres
    Worker2 -->|Process Message| Postgres
    Worker1 -.->|Outbox Insert| Postgres

    RedisPubSub -->|Broadcast Event| API1
    RedisPubSub -->|Broadcast Event| API2
    API1 -.->|Push Message| BrowserA
    API2 -.->|Push Message| BrowserB
```

---

## ✨ Core Features

1. **Real-Time 1-to-1 Chat**:
   - Sub-millisecond local messaging with WebSocket connections.
   - Distinct delivery lifecycle indicators: **`SENT` (✓)** $\rightarrow$ **`DELIVERED` (✓✓)** $\rightarrow$ **`READ` (✓✓)**.
   - Distributed multi-pod routing via Redis Pub/Sub fanout.

2. **Timezone-Aware Scheduled Messaging**:
   - Compose messages and choose exact future delivery times across any IANA timezone (e.g. `Europe/Copenhagen`, `America/New_York`, `Asia/Tokyo`).
   - Strict Daylight Saving Time (DST) validation rejecting invalid non-existent or ambiguous transition times.
   - Full lifecycle management: `SCHEDULED` $\rightarrow$ `PROCESSING` $\rightarrow$ `SENT` (with inline `EDIT` and `CANCEL`).

3. **Transactional Outbox & At-Least-Once Delivery**:
   - Message persistence and event generation are committed atomically in a single PostgreSQL transaction.
   - Background outbox publisher guarantees reliable publication to Redis Pub/Sub even during network partitions or process crashes.

4. **Resilient Queue & DLQ Processing**:
   - Due jobs are buffered in Redis lists and consumed by worker pools.
   - Exponential backoff retry engine for transient failures.
   - Isolated Dead-Letter Queue (`latext:scheduled:dead-letter`) with transactionally decoupled state tracking (`FAILED_PENDING_DLQ`).

5. **Cloud-Native Autoscaling & Observability**:
   - Full Kubernetes deployment manifests with zero-downtime rolling updates and graceful shutdown hooks.
   - **KEDA Autoscaling**: Automatically scales background worker replicas based on Redis queue depth.
   - **Prometheus & Grafana**: Real-time instrumentation of end-to-end delivery latencies, database transaction durations, and worker throughput.

---

## ⚡ Performance Highlights

| Metric | Measured Value | Configuration / Environment |
| :--- | :--- | :--- |
| **Peak Throughput** | **109.25 msg/sec** | 2 Workers, Concurrency=10, Batch Size=10 (Local Docker) |
| **P95 Queue-to-Delivery Latency** | **< 120 ms** | 100 Concurrent Scheduled Messages Workload |
| **Idempotency Guarantee** | **100% Unique** | 0 duplicate persistent messages under failure injection |
| **PostgreSQL Connection Budget** | **125 / 250 safe limit** | Explicitly enforced against maximum KEDA replica bounds |

---

## 🚀 Quick Start

### 1. Run with Docker Compose (Recommended)

Ensure Docker Desktop is running:

```bash
# Clone repository
git clone https://github.com/latext/latext.git
cd latext

# Copy environment variables
cp .env.example .env

# Start all services (Backend, Frontend, Postgres, Redis, Scheduler, Workers, Prometheus, Grafana)
docker compose up --build
```

Access services:
- **Web App**: [http://localhost:3000](http://localhost:3000) (Demo accounts: `alice@example.com` / `bob@example.com` with password `password123`)
- **Interactive API Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Grafana Metrics Dashboard**: [http://localhost:3001](http://localhost:3001) (`admin` / `admin`)
- **Prometheus Scrape Targets**: [http://localhost:9090](http://localhost:9090)

---

### 2. Deploy to Kubernetes

Deploy Latext onto a local or cloud Kubernetes cluster (Minikube / Docker Desktop / EKS / GKE):

```bash
# 1. Create namespace, ConfigMaps, Secrets, StatefulSets, and Services
kubectl apply -k k8s/

# 2. Run database migrations
kubectl apply -f k8s/migration-job.yaml -n latext

# 3. Verify pods are running
kubectl get pods -n latext
```

---

## 🧪 Testing & Verification

### Backend Integration Tests (Pytest)
```powershell
$env:PYTHONPATH="."; $env:DATABASE_URL="sqlite+aiosqlite:///test.db"; .\backend\venv\Scripts\pytest backend
```
*Current test suite: **30 passed, 1 skipped**.*

### Frontend Production Build (Next.js)
```bash
cd frontend
npm run build
```
*Compiled with **0 errors**.*

### End-to-End Smoke Test
```powershell
$env:PYTHONPATH="backend"; .\backend\venv\Scripts\python backend/scripts/smoke_test.py
```

---

## 📚 Technical Documentation

- **[Project Story & Engineering Evolution](docs/project-story.md)**: Case study detailing how performance bottlenecks were diagnosed, benchmarked, and re-architected across Phases 1–7.6.
- **[Resume & Portfolio Notes](docs/resume-notes.md)**: Key technical highlights, metrics, and resume bullet points.
- **[Interview Deep-Dive Guide](docs/interview-guide.md)**: 21 comprehensive interview questions and architectural explanations.
- **[System Limitations & Trade-Offs](docs/limitations.md)**: Transparent discussion of engineering trade-offs and current system boundaries.
- **[Kubernetes & Scaling Guide](docs/kubernetes.md)**: Connection budgeting, resource limits, and KEDA triggers.
- **[Architecture Deep-Dive](docs/architecture.md)**: Detailed component interaction and transaction specifications.

---

## 📄 License
MIT License. Created as a production-grade distributed systems showcase.
