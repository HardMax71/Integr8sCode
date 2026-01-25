# Supply Chain Security

Modern applications pull in hundreds of transitive dependencies. When something like Log4Shell hits, the first question is "are we affected?" - and if you don't know exactly what's in your software, you can't answer that quickly. This is where SBOMs come in.

## SBOM generation

An SBOM (Software Bill of Materials) is essentially an ingredients list for software - a machine-readable inventory of every library, package, and dependency your application uses. Integr8sCode generates SBOMs automatically using [Anchore Syft](https://github.com/anchore/syft), which scans both the Python backend and JavaScript frontend to produce SPDX-formatted JSON files.

The workflow in [`.github/workflows/sbom-compliance.yml`](https://github.com/HardMax71/Integr8sCode/blob/main/.github/workflows/sbom-compliance.yml) runs on every push to main, every PR, and weekly on Sundays. It does three things:

1. Generates separate SBOMs for backend and frontend
2. Scans those SBOMs for known vulnerabilities using [Anchore Grype](https://github.com/anchore/grype)
3. Uploads findings to GitHub's Security tab as SARIF reports

The SBOM artifacts stick around for 5 days in case you need to inspect them. The vulnerability scan doesn't block builds yet (we set `fail-build: false`) - it just reports. Once the dependency situation stabilizes, flipping that to `true` would enforce a clean bill of health on every PR.

## Viewing results

Vulnerability findings show up in the repository's Security tab under Code Scanning alerts. They're categorized by component (`backend-dependencies`, `frontend-dependencies`) so you can see which part of the stack is affected.

You can also grab the SBOM artifacts directly from the [workflow runs](https://github.com/HardMax71/Integr8sCode/actions/workflows/sbom-compliance.yml) page - useful if you need to share them with security auditors or feed them into other tools.

## Running locally

If you want to generate an SBOM on your machine:

```bash
# Install syft
curl -sSfL https://raw.githubusercontent.com/anchore/syft/main/install.sh | sh -s -- -b /usr/local/bin

# Generate SBOM for backend
syft ./backend -o spdx-json=backend-sbom.json

# Scan it for vulnerabilities
curl -sSfL https://raw.githubusercontent.com/anchore/grype/main/install.sh | sh -s -- -b /usr/local/bin
grype sbom:backend-sbom.json
```

## Other security tooling

Beyond SBOM scanning, the project uses Bandit for Python static analysis (see [`security.yml`](https://github.com/HardMax71/Integr8sCode/blob/main/.github/workflows/security.yml)) and Dependabot for automated dependency updates. Between these three - SAST, SCA, and automated patching - most of the low-hanging supply chain risks are covered.
