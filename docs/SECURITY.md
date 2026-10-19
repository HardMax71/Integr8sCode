# Security policy

Security fixes go into `main` and the latest release. If you run something older, upgrade.

## Reporting vulnerabilities

Don't open a public GitHub issue. Email [max.azatian@gmail.com](mailto:max.azatian@gmail.com) instead.

Include what you can: the kind of issue, where it is, steps to reproduce, a PoC if you have one. You'll get an acknowledgment within 48 hours. If it's confirmed, we'll fix it and credit you in the disclosure, unless you'd rather stay anonymous.

## What's in place

CI runs Bandit on the backend, Trivy on every image that passes the tests on `main`, and Syft plus Grype on the backend and frontend dependencies. Dependabot keeps Python, npm, Docker, compose and GitHub Actions dependencies current, and every action is pinned to a commit SHA. See [Supply chain security](security/supply-chain.md).

The app's Content Security Policy is a `<meta>` tag SvelteKit writes into the page. Scripts must be same-origin or match the hash of SvelteKit's one inline bootstrap script. Styles must be same-origin or Google Fonts, plus the editor's own `<style>` tag, which carries a nonce nginx fills in per response. `style=""` attributes are allowed because Svelte transitions and CodeMirror set them at runtime. nginx adds `frame-ancestors 'none'` as a header, along with HSTS, `X-Frame-Options: DENY`, `nosniff`, a strict referrer policy and a permissions policy. The Grafana server block gets none of these headers. See [Frontend build](architecture/frontend-build.md#configuration) and [Nginx configuration](operations/nginx-configuration.md#security-headers).

User code runs as a non-root user with a read-only root filesystem, no capabilities, `RuntimeDefault` seccomp, user namespaces (`hostUsers: false`) and no service account token. Each pod has an `activeDeadlineSeconds` set from the execution timeout, raised to a per-language minimum where one is defined. `K8S_POD_RUNTIME_CLASS_NAME` can put pods under gVisor or another sandboxed runtime.

The k8s worker owns the namespace controls and applies them at startup: the `executor-deny-all` NetworkPolicy, which blocks all executor ingress and egress on a cluster that enforces NetworkPolicies, and the `restricted` Pod Security Admission labels. It also creates the namespace itself and applies the `executor-quota` ResourceQuota, which caps the total CPU and memory that executor pods request; a pod over the quota is refused. See [Pod and namespace security](security/policies.md).

Passwords are hashed with `pwdlib`'s `BcryptHasher`, with `BCRYPT_ROUNDS` rounds. Sessions are a JWT in an httpOnly cookie plus a CSRF double-submit token, and repeated failed logins lock the account. See [Authentication](architecture/authentication.md).

Redis requires a password and MongoDB requires authentication. MongoDB, Redis, Kafka and the observability services only listen on `127.0.0.1` on the host; the frontend (5001) is the public port. nginx serves it over TLS with the certificate mounted at `/etc/nginx/certs`, or with a self-signed one it makes when it starts. The backend listens on `127.0.0.1:443` over TLS with a self-signed certificate it makes on first start, and nginx verifies that certificate on every proxied request. Third-party images in compose are pinned to fixed versions.

The secrets (`SECRET_KEY`, `MONGO_USER`, `MONGO_PASSWORD`, `REDIS_PASSWORD`, and the Grafana, Mailjet and MongoDB monitor credentials) come from environment variables. Compose has development defaults for all of them, so set real values in production. The release workflow does that from repository secrets.
