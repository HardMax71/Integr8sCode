# Security Policy

Integr8sCode takes the security of our software and our users' data seriously. We are committed to ensuring a secure
environment and following best practices for vulnerability management and disclosure.

## Supported Versions

We currently support security updates for the following versions of Integr8sCode:

| Version        | Supported          |
|----------------|--------------------|
| `main`         | :white_check_mark: |
| Latest Release | :white_check_mark: |

If you are running an older version, we strongly recommend upgrading to the latest release to ensure you have the most
recent security patches.

## Reporting a Vulnerability

If you discover a security vulnerability within Integr8sCode, please **DO NOT** create a public GitHub issue. Instead,
please report it privately to our security team.

### How to Report

1. **Email:** Send a detailed report to <mailto:max.azatian@gmail.com>.
2. **Details:** Please include as much information as possible:
    * Type of vulnerability (e.g., XSS, SQL Injection, RCE).
    * Full path or URL where the vulnerability occurs.
    * Step-by-step instructions to reproduce the issue.
    * Proof of concept (PoC) code or screenshots, if available.
    * Any specific configuration required to reproduce the issue.

### Our Response Process

1. **Acknowledgment:** We will acknowledge receipt of your report within 48 hours.
2. **Assessment:** We will investigate the issue to confirm its validity and impact.
3. **Resolution:** If confirmed, we will work on a patch. We will keep you updated on our progress.
4. **Disclosure:** Once a fix is released, we will publicly disclose the vulnerability (with your permission, crediting
   you for the discovery).

## Security Measures

We employ several automated tools and practices to maintain the security of our codebase:

* **Static Application Security Testing (SAST):** We use **Bandit** to scan our Python backend code for common security
  issues.
* **Dependency Management:** We use **Dependabot** to automatically monitor and update vulnerable dependencies in our
  `package.json`, `pyproject.toml`, and Docker files.
* **Container Security:** We follow best practices for containerization, including using minimal base images and
  non-root users where possible.
* **Secrets Management:** We do not commit secrets to the repository. Please ensure `.env` files and other secrets are
  properly managed in your deployment environment.

## Software Bill of Materials (SBOM)

We strive to maintain transparency regarding our dependencies. You can inspect our direct dependencies in:

* `backend/pyproject.toml` (Python)
* `frontend/package.json` (Node.js/Svelte)
* `helm/integr8scode/Chart.yaml` (Kubernetes/Helm)

Thank you for helping keep Integr8sCode safe!
