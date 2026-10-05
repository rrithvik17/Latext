# Latext Security Hardening & Vulnerability Management

This document outlines the security controls, container hardening, secret policies, and dependency auditing practices implemented for the Latext platform.

---

## 1. Secrets Management Policy

- **Development**: Stored inside ignored `.env` files. Clean placeholders are maintained in `.env.example`.
- **Kubernetes**: Decoupled using Kubernetes `Secret` resources.
  > [!WARNING]
  > **Kubernetes Secrets Safety**
  > base64 encoding inside Kubernetes Secret manifests is NOT encryption. Committing base64 strings to git repositories exposes secrets. For production workloads, utilize Sealed Secrets, External Secrets Operator, or Cloud KMS integrations.
- **CI/CD**: Credentials (e.g. Docker registry logins, Kubernetes configs) are injected via GitHub Actions Repository Secrets.
- **Zero Exposure**: Secrets are never hardcoded, written to configuration maps (`ConfigMaps`), or printed in application logs.

---

## 2. Docker Container Security Hardening

Both application images have been hardened to enforce least-privilege runtime security:

### Backend Image Hardening ([Dockerfile](file:///c:/Users/rithv/Desktop/Latext/backend/Dockerfile))
- **Non-Root Execution**: Runs under a dedicated system user `appuser` (UID/GID 10001) instead of `root`.
- **Minimal Surface**: Uses a slim base image and installs dependencies with `--no-install-recommends` to limit diagnostic tools.
- **Shell Disabling**: Configures `/sbin/nologin` shell for the system account.

### Frontend Image Hardening ([Dockerfile](file:///c:/Users/rithv/Desktop/Latext/frontend/Dockerfile))
- **Least Privilege**: Runs under the default Node alpine non-root user `node` (UID 1000).
- **Deterministic Install**: Enforces `npm ci` for dependency lock-file integrity.

---

## 3. GitHub Actions Least-Privilege Permissions

All CI/CD workflows enforce strict access permissions:
```yaml
permissions:
  contents: read
```
This restricts the standard `GITHUB_TOKEN` from writing to repositories or modifying issues unless explicitly authorized.

---

## 4. Ecosystem Vulnerability Scanning

- **Python Audit**: Run `pip-audit` to detect known CVEs in PyPI packages.
- **Node Audit**: Run `npm audit` inside the frontend folder to scan Node dependencies.
- **Container Audit**: Utilize `trivy image latext-backend:latest` to inspect container base OS layers.
