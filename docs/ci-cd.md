# Latext CI/CD Delivery Pipeline

This document details the architecture, workflows, image tagging, and database migration gates configured for the Latext integration and deployment pipelines.

---

## 1. CI Pipeline Architecture

The Continuous Integration workflow is managed via GitHub Actions inside [`.github/workflows/ci.yml`](file:///c:/Users/rithv/Desktop/Latext/.github/workflows/ci.yml). It triggers on pushes and pull requests targeting the `main` branch.

```text
    Developer Git Push
            │
            ▼
     GitHub Actions Runner
       ┌────┴────┐
       ▼         ▼
  [ Backend ]  [ Frontend ]
       │         │
       ▼         ▼
  pytest Suite  npm run build
```

### Pipelines Verification:
1. **Backend Test Suite**: Runs inside Ubuntu host using service containers for **PostgreSQL 16** and **Redis 7** to preserve authentic row locking (`FOR UPDATE SKIP LOCKED`) and Pub/Sub mechanics during verification testing.
2. **Frontend Compilation**: Installs dependencies via `npm ci` and runs `npm run build` to verify type safety and Next.js production builds.

---

## 2. CD Deployment Workflow

The Continuous Delivery workflow is managed inside [`.github/workflows/deploy.yml`](file:///c:/Users/rithv/Desktop/Latext/.github/workflows/deploy.yml).

### Steps in Delivery Sequence:
1. **Build & Image Tagging**: Builds Docker containers and tags them using the specific **Git Commit SHA** (`latext-backend:<git-sha>`). This ensures strict version transparency.
2. **Database Migration Job Gate**: Deploys a single-replica Kubernetes `Job` mapping to `k8s/migration-job.yaml` which executes `alembic upgrade head`. The CD pipeline blocks rollout until the migration Job successfully exits, preventing concurrent migration conflicts between scaling backend replicas.
3. **Rolling Update**: Deploys application manifests using `kubectl apply -k k8s/`. Kubernetes monitors readiness probes to spin up new pods before terminating old ones.
4. **Smoke Test Verification**: Triggers [`smoke_test.py`](file:///c:/Users/rithv/Desktop/Latext/backend/scripts/smoke_test.py) checking `/health`, `/ready`, registration, messaging, and WebSocket delivery pathways.
5. **Rollback Trigger**: If smoke tests fail, the CD pipeline automatically triggers a rollback:
   ```bash
   kubectl rollout undo deployment/backend -n latext
   ```

---

## 3. Environment & Manifest Isolation

Workload environments are isolated using Kustomize overlays:
- **`k8s/base/`**: Defines the foundational StatefulSet, deployments, and services.
- **`k8s/overlays/local/`**: Configured with local developer parameters (e.g. SQLite compatible tests or local volume bounds).
- **`k8s/overlays/production/`**: Enforces strict node sizing, replica scaling limits, and links to managed cloud database systems.
