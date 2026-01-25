# Security Policy

Security patches go into `main` and the latest release. If you're running something older, upgrade.

## Reporting vulnerabilities

Found a security issue? Don't open a public GitHub issue - email [max.azatian@gmail.com](mailto:max.azatian@gmail.com) instead.

Include what you can: vulnerability type, where it occurs, reproduction steps, PoC if you have one. You'll get an acknowledgment within 48 hours. If confirmed, we'll patch it and credit you in the disclosure (unless you prefer to stay anonymous).

## Automated scanning

The CI pipeline runs [Bandit](https://bandit.readthedocs.io/) on the Python backend for static analysis, and [Dependabot](https://docs.github.com/en/code-security/dependabot) keeps dependencies patched across Python, npm, and Docker. For SBOM generation and vulnerability scanning, see [Supply Chain Security](security/supply-chain.md).

## Runtime hardening

Executor pods run user code with non-root users, read-only filesystems, dropped capabilities, and no service account tokens. Network policies deny all traffic by default. Details in [Network Isolation](security/policies.md).

Secrets stay out of the repo - `.env` files and credentials are your responsibility to manage in deployment.
