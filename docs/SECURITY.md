# Security policy

Security fixes go into `main` and the latest release. If you run something older, upgrade.

## Reporting vulnerabilities

Don't open a public GitHub issue. Email [max.azatian@gmail.com](mailto:max.azatian@gmail.com) instead.

Include what you can: the kind of issue, where it is, steps to reproduce, a PoC if you have one. You'll get an acknowledgment within 48 hours. If it's confirmed, we'll fix it and credit you in the disclosure, unless you'd rather stay anonymous.

## What's in place

CI runs Bandit on the backend, Trivy on every image that passes the tests on `main`, and Syft plus Grype on the backend and frontend dependencies. Dependabot keeps Python, npm, Docker, compose and GitHub Actions dependencies current, and every action is pinned to a commit SHA. See [Supply chain security](security/supply-chain.md).

nginx sends a nonce-based Content Security Policy: scripts and `<style>` elements need the per-request nonce, and `style=""` attributes are allowed because Svelte transitions and CodeMirror set them at runtime. It also sends HSTS, `X-Frame-Options: DENY`, `nosniff`, a strict referrer policy and a permissions policy. See [Nginx configuration](operations/nginx-configuration.md#security-headers).

User code runs as a non-root user with a read-only root filesystem, no capabilities, `RuntimeDefault` seccomp, user namespaces (`hostUsers: false`) and no service account token. Each pod has an `activeDeadlineSeconds` set from the execution timeout, raised to a per-language minimum where one is defined. `K8S_POD_RUNTIME_CLASS_NAME` can put pods under gVisor or another sandboxed runtime.

The k8s worker owns the namespace controls and applies them at startup: the `executor-deny-all` NetworkPolicy, which blocks all executor ingress and egress, and the `restricted` Pod Security Admission labels. Total CPU and memory are capped by Kueue, which setup-k8s.sh installs; pods over quota wait behind a scheduling gate instead of failing. See [Pod and namespace security](security/policies.md).

Passwords are hashed with `pwdlib`'s `BcryptHasher`, with `BCRYPT_ROUNDS` rounds. Sessions are a JWT in an httpOnly cookie plus a CSRF double-submit token, and repeated failed logins lock the account. See [Authentication](architecture/authentication.md).

Redis requires a password and MongoDB requires authentication. MongoDB, Redis, Kafka and the observability services only listen on `127.0.0.1` on the host; the backend (443) and frontend (5001) are the public ports, both TLS with self-signed certificates from the cert-generator container. Third-party images in compose are pinned to fixed versions.

The secrets (`SECRET_KEY`, `MONGO_USER`, `MONGO_PASSWORD`, `REDIS_PASSWORD`, and the Grafana, Mailjet and MongoDB monitor credentials) come from environment variables. Compose has development defaults for all of them, so set real values in production. The release workflow does that from repository secrets.
