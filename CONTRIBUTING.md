# Contributing to Integr8sCode

## Development Setup

### Prerequisites

- Python 3.14 (uv reads backend/.python-version and installs it)
- Node.js 26
- Docker and Docker Compose
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- k3s or another Kubernetes cluster, to run executions and the E2E suites

### Clone and Setup

```bash
git clone https://github.com/HardMax71/Integr8sCode.git
cd Integr8sCode

# Install dependencies (the hooks below call uv run and npm run, so they need these)
(cd backend && uv sync)
(cd frontend && npm ci)

# Install pre-commit hooks (required before submitting PRs)
uv tool install pre-commit
pre-commit install

# Start the stack
./deploy.sh dev
```

### Pre-commit Hooks

Install the hooks before you open a PR. They run on `git commit` whenever backend Python files or frontend sources are staged:

| Hook | What it runs | Also in CI |
|------|--------------|------------|
| ruff format | `uv run ruff format`, rewrites files | no |
| ruff check | `uv run ruff check --fix` | yes, without `--fix` |
| mypy | `uv run mypy --strict .` | yes |
| grimp | `uv run python -m scripts.check_orphan_modules` | yes |
| eslint | `npm run lint` | yes |
| stylelint | `npm run stylelint` | yes |
| prettier | `npm run format`, rewrites files | yes, as `npm run format:check` |
| svelte-check | `npm run check` | yes |

Run them on everything with:

```bash
pre-commit run --all-files
```

Fix whatever fails before committing. CI runs the same checks, so a local failure fails the pipeline too. The exception is ruff format, which CI doesn't check.

### Backend Development

```bash
cd backend

# Install dependencies
uv sync

# Lint (covers tests too) and type check
uv run ruff check . --config pyproject.toml
uv run mypy --config-file pyproject.toml --strict .

# Dead code check
uv run python -m scripts.check_orphan_modules

# Unit tests
uv run pytest tests/unit
```

Always pass a path to pytest. A plain `uv run pytest` also collects tests/e2e, which needs the running stack and Kubernetes. The E2E suite runs inside the backend container, the same way CI runs it:

```bash
./deploy.sh dev --wait
docker compose exec -T backend sh -c 'uv sync --group test --no-dev --frozen --no-install-project && pytest tests/e2e'
```

### Frontend Development

```bash
cd frontend

# Install dependencies
npm ci

# Unit tests, type check, lint
npm run test
npm run check
npm run lint

# E2E tests (Playwright, needs the stack from ./deploy.sh dev)
npm run test:e2e:deps      # once, installs system deps for Chromium
npm run test:e2e:browsers  # once, installs Chromium
npm run test:e2e
```

The stack serves a production build of the frontend on https://localhost:5001, so rebuild it with `./deploy.sh dev --build` after frontend changes. `npm run dev` only works inside the compose network, since it proxies to the backend container and needs the shared CA.

## Code Style

Python follows PEP 8 with a 120 character line limit and type hints on every signature; ruff and strict mypy enforce both. Frontend code is TypeScript with Svelte 5 runes and follows the existing component patterns. AGENTS.md has the full conventions for both sides.

## Pull Request Process

1. Create a feature branch from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. Make your changes in clear, atomic commits

3. Make sure all checks pass (from the repo root):
   ```bash
   pre-commit run --all-files
   (cd backend && uv run pytest tests/unit)
   (cd frontend && npm run test)
   (cd frontend && npm run test:e2e)
   ```

4. Push and open a PR against `main`

5. Fill out the PR template: summary, test plan and any breaking changes

## Commit Messages

Use clear, descriptive commit messages:

```
feat: add user notification preferences
fix: resolve race condition in execution coordinator
docs: update deployment guide for k3s setup
refactor: extract common validation logic
test: add e2e tests for DLQ processor
```

## Reporting Issues

Use GitHub Issues: the Bug Report template for unexpected behavior or errors, the Feature Request template for new functionality. Include reproduction steps, environment details and relevant logs.

## Questions?

Search the [existing issues](https://github.com/HardMax71/Integr8sCode/issues) first. If none answers it, open a blank issue with your question.
