# Supply chain security

Four things in CI cover the supply chain: SBOMs with a Grype scan of the dependencies, Trivy scans of the built images, Bandit on the Python code, and pinning of everything CI runs. Dependabot keeps the pins moving.

## SBOM and dependency scan

[sbom-compliance.yml](https://github.com/HardMax71/Integr8sCode/blob/main/.github/workflows/sbom-compliance.yml) runs on pushes and PRs to `main` and every Sunday. For `backend/` and `frontend/` it generates an SPDX JSON SBOM with `anchore/sbom-action` (Syft), scans it with `anchore/scan-action` (Grype) at a `high` cutoff, and uploads the findings as SARIF. The scan has `fail-build: false`, so it reports without blocking. The SBOMs are kept as workflow artifacts for 5 days.

Findings show up in the repository's Security tab under code scanning, as `backend-dependencies` and `frontend-dependencies`.

## Image and code scans

Docker Scan & Promote runs Trivy v0.75.0 on the `base`, `backend`, `frontend` and `cert-generator` images of every commit that passed Stack Tests on `main`. It reports `CRITICAL` and `HIGH` findings that have a fix, skips anything listed in `backend/.trivyignore`, and uploads SARIF per image as `trivy-<image>`. A finding fails the job and blocks the promote to `latest`. The images keep the count at zero by upgrading their OS packages at build time, and the backend drops pip, whose vendored packages were the only Python findings. The ignore file holds three Go CVEs in kubectl v1.37.1, the newest release, which cert-generator only uses to talk to the local k3s API. See [CI/CD](../operations/cicd.md#docker-scan-promote).

security.yml runs `uvx --no-build bandit==1.9.4 -r backend/ -x backend/tests/ -ll` on pushes and PRs to `main`. `-ll` reports medium severity and up, and any finding fails the workflow.

## Pinning

Every GitHub Action, including those used inside the composite actions, is pinned to a full commit SHA with the version in a comment. The Trivy action is pinned to the commit of v0.36.0, since its older tags were deleted upstream. Tools are pinned to exact versions (bandit, Trivy, mkdocs and its plugins), Python installs are `uv sync --frozen --no-build` from the lockfile, and npm installs are `npm ci --ignore-scripts`. The k3s install script and the Kueue manifest are fetched over HTTPS only and checked against a SHA256 before use.

Dependabot opens one grouped PR per ecosystem every week, for uv, npm, the Dockerfiles, the compose images and the GitHub Actions, and updates SHA and version comment together. Details are in [CI/CD](../operations/cicd.md#dependabot).

## Running it locally

```bash
syft ./backend -o spdx-json=backend-sbom.json
grype sbom:backend-sbom.json
trivy image ghcr.io/hardmax71/integr8scode/backend:latest
```

Install Syft, Grype and Trivy from their release pages or your package manager.
