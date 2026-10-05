# Latext Kubernetes Deployment, Scaling & Autoscaling Guide

This document details the configuration, architecture, deployment commands, connection budget equations, and autoscaling layouts for running Latext on a Kubernetes cluster.

---

## 1. Kubernetes Architecture

Latext has been designed to operate as a containerized, horizontally scalable microservice cluster orchestrated by Kubernetes. The architecture maps out as follows:

```text
                                  Ingress (HTTP / WebSocket)
                                              │
                                              ▼
                                 backend-service (LoadBalancer)
                                              │
                         ┌────────────────────┴────────────────────┐
                         ▼                                         ▼
                 backend-pod-1 (Node A)                    backend-pod-2 (Node B)
                         │                                         │
             ┌───────────┴───────────┐                 ┌───────────┴───────────┐
             ▼                       ▼                 ▼                       ▼
      postgres-service         redis-service    postgres-service         redis-service
             │                       │                 │                       │
             ▼                       ▼                 ▼                       ▼
       postgres-statefulset     redis-pod        postgres-statefulset     redis-pod
```

### Manifest Specifications (`k8s/`):
1. **Namespace (`latext`)**: All resources live within the `latext` namespace to ensure environment isolation.
2. **ConfigMap & Secret (`latext-config`, `latext-secrets`)**: Centralizes configurations (Redis/DB URL, CORS, token expiry) and secures secret tokens (JWT secret key).
3. **PostgreSQL (`postgres`)**: Configured as a single-replica `StatefulSet` with a `PersistentVolumeClaim` (PVC) for local database durability. 
   > [!IMPORTANT]
   > The StatefulSet PostgreSQL is for local development and testing only. In production environments, a managed cloud database service (e.g. AWS RDS, Google Cloud SQL) or a production-operated high-availability database cluster (e.g., Patroni) should be used.
4. **Redis (`redis`)**: Deployed as a single replica. Pub/Sub events are ephemeral; PostgreSQL remains the authoritative source of truth.
5. **Backend (`backend`)**: Runs FastAPI containers with `replicas: 2` to demonstrate horizontal load balancing. Integrates liveness and readiness probes.
6. **Worker (`worker`)**: Deployed as worker pods consuming queue items. Set to `replicas: 2`.
7. **Scheduler (`scheduler`)**: Deployed as a singleton (`replicas: 1`) to avoid duplicate scheduled-message runs.

---

## 2. Health Probes & Graceful Shutdown

To ensure high availability and prevent cascading container restarts, we distinguish between liveness and readiness probes:

- **Liveness Probe (`/health`)**: Answers "is the FastAPI process running?". It is a lightweight static path returning 200 immediately without querying PostgreSQL or Redis. If a database timeout occurs, the container is **not** restarted, preventing cascading restart loops.
- **Readiness Probe (`/ready`)**: Answers "is this pod ready to receive traffic?". It performs `SELECT 1` on PostgreSQL and a ping check on Redis. If either service is down, Kubernetes automatically pulls the pod out of the active Service load balancer until the dependency recovers.
- **Graceful Shutdown**: All workloads listen to `SIGTERM` signals and utilize a `preStop` hook (configured with `terminationGracePeriodSeconds: 30`). This provides:
  - **Backend**: Time to cleanly close active WebSocket sessions and unsubscribe from Redis Pub/Sub channels.
  - **Worker**: Time to complete current database transactions and return/release claimed jobs before termination.

---

## 3. Database Connection Safety Budget

Running multiple backend and worker pod replicas increases the risk of PostgreSQL connection exhaustion. 

### Sizing Equation:
Let:
- $B$ = Backend pod replicas count
- $W$ = Worker pod replicas count
- $P_b$ = Backend connection pool size limit (default = 15; pool size 5 + max overflow 10)
- $P_w$ = Worker connection pool size limit (default = 15)
- $P_s$ = Scheduler connection pool (default = 15)

Total possible active PostgreSQL connections ($C_{total}$) is calculated as:
$$C_{total} = (B \times P_b) + (W \times P_w) + P_s$$

For a local development PostgreSQL instance configured with `max_connections = 300`, we enforce a safety connection ceiling of **250** to prevent database exhaustion:
$$(B + W + 1) \times 15 \le 250 \implies B + W \le 15$$

If worker or backend replicas scale beyond this constraint without adjusting database parameters, database connection errors will occur, degrading performance.

---

## 4. Horizontal Pod Autoscaling (HPA) & Queue-Aware Scaling

- **Backend Scaling**: Enforced via HorizontalPodAutoscaler (HPA) based on average CPU/Memory metrics (e.g. scaling up from 2 to 8 replicas when CPU utilization exceeds 50%).
- **Worker Scaling (Queue-Aware)**: Worker CPU utilization does not necessarily scale with message scheduled queues demand. We analyze autoscaling workers based on **Redis queue depth** using **KEDA** (Kubernetes Event-driven Autoscaling).
  - *Mechanism*: KEDA deploys a `ScaledObject` that periodically queries Redis `LLEN latext:scheduled:queue` (or Prometheus metrics). If the queue depth rises above a target threshold (e.g., 50 pending messages), KEDA automatically scales worker pods up to handle the burst, and scales down to `minReplicas` (e.g. 2 workers) once the queue is drained.

---

## 5. Local Setup & Deployment Commands

### Applying Manifests:
```bash
# Create resources using Kustomize
kubectl apply -k k8s/
```

### Inspecting Workloads:
```bash
# Check status of all pods in latext namespace
kubectl get pods -n latext

# View deployments and service bindings
kubectl get deployments,services -n latext

# Monitor logs of backend pods
kubectl logs -l app=backend -n latext -f
```

### Scaling Workloads manually:
```bash
# Scale backend pods to 4 replicas
kubectl scale deployment backend --replicas=4 -n latext

# Scale worker pods to 4 replicas
kubectl scale deployment worker --replicas=4 -n latext
```

### Simulating Failures:
```bash
# Delete a backend pod (triggers automatic recreation)
kubectl delete pod -l app=backend -n latext

# Restart Redis service (triggers worker recovery)
kubectl rollout restart deployment redis -n latext
```

---

## 6. Database Migration Job, Rolling Updates & Rollback

### Controlled Database Migrations
Rather than running migrations inside application container startup scripts (which causes concurrency race conditions when scaling), migrations are executed via a single-replica Kubernetes `Job` ([`migration-job.yaml`](file:///c:/Users/rithv/Desktop/Latext/k8s/migration-job.yaml)):
```bash
# Apply the migration Job
kubectl apply -f k8s/migration-job.yaml -n latext

# Check Job completion status
kubectl wait --for=condition=complete job/latext-migration-job -n latext --timeout=120s
```

### Rolling Update Policy
Workloads execute rolling updates ensuring continuous service availability. In the backend deployment spec, we define:
- `maxSurge: 1`: Spins up one new pod before terminating old pods.
- `maxUnavailable: 0`: Ensures 100% of the active replica count is available to serve traffic during updates.

> [!NOTE]
> Since WebSockets are stateful and long-lived, active connections will disconnect upon pod termination. Reconnection strategies on the client automatically reconnect and reconcile message state from PostgreSQL history.

### Rollback Commands
If post-deployment smoke tests fail, trigger an immediate rollback:
```bash
# Rollback to the previous deployment revision
kubectl rollout undo deployment/backend -n latext

# Verify rollout status of the rollback
kubectl rollout status deployment/backend -n latext
```
> [!IMPORTANT]
> A rollout rollback reverts the application code image, but does NOT rollback the database schema. Database schema reversals must be handled manually with Alembic CLI (`alembic downgrade`) to avoid transaction and state loss.
