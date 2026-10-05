# Latext — System Limitations & Engineering Trade-Offs

To maintain high engineering integrity, this document explicitly outlines the known limitations, architectural boundaries, and deliberate trade-offs in Latext.

---

## 1. Single-Region Architecture
* **Current State**: Latext operates within a single cluster/region.
* **Limitation**: There is no cross-region active-active replication. If an entire cloud region or local cluster fails, traffic cannot automatically failover to a geographic replica.
* **Trade-Off Justification**: Single-region deployment avoids the latency penalties, consensus overhead, and partition complexities of distributed multi-region databases.

---

## 2. Ephemeral Redis Pub/Sub
* **Current State**: WebSocket broadcast uses Redis Pub/Sub channels.
* **Limitation**: Redis Pub/Sub is fire-and-forget. If a backend pod is temporarily disconnected from Redis during event publication, it will miss that specific broadcast.
* **Mitigation**: Latext relies on the Transactional Outbox for persistence, and client applications perform an initial REST sync upon WebSocket reconnection to fetch any missed messages.

---

## 3. WebSocket Authentication via Query Parameter
* **Current State**: Browsers establishing WebSocket connections (`new WebSocket(url)`) pass the JWT access token in the query string (`?token=...`).
* **Limitation**: The standard browser WebSocket API does not support custom HTTP request headers during the initial handshake. Query parameters may appear in server access logs if not sanitized.
* **Trade-Off Justification**: This is a standard browser limitation. In production environments, reverse proxies (e.g. NGINX or Envoy) strip query parameters from access logs.

---

## 4. Single Coordinator Scheduler
* **Current State**: The scheduler coordinator is deployed as a single Kubernetes replica (`replicas: 1`).
* **Limitation**: If the scheduler pod terminates, there is a brief delay (10–30 seconds) while Kubernetes restarts the pod or reschedules it onto another node, during which due messages are not moved into Redis.
* **Trade-Off Justification**: Running a single coordinator avoids the overhead of distributed leader election (e.g., Raft/Etcd/ZooKeeper). Stalled or delayed messages are safely picked up immediately upon restart.

---

## 5. At-Least-Once Delivery Semantics
* **Current State**: Both the Transactional Outbox publisher and Redis worker queues provide **at-least-once** guarantees.
* **Limitation**: Under rare network partition scenarios, duplicate events may be published or re-processed.
* **Mitigation**: Database-level unique constraints (`messages.scheduled_message_id`) and client-side message ID tracking enforce strict deduplication.

---

## 6. Local Storage in Kubernetes Manifests
* **Current State**: Kubernetes manifests use `volumeClaimTemplates` with standard `ReadWriteOnce` storage classes for PostgreSQL and Redis.
* **Limitation**: Tailored for local Kubernetes environments (Minikube, Docker Desktop). Production deployments would require managed cloud database services (e.g. AWS RDS / Aurora, GCP Cloud SQL) and Redis clusters.

---

## 7. Product Positioning
* **Scope**: Latext is an independent, WhatsApp-inspired messaging application showcasing real-time and scheduled distributed messaging patterns. It does **not** integrate with or use the proprietary WhatsApp Business API or proprietary meta assets.
