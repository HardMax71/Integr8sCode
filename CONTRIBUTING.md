# Contributing to Integr8sCode

Thank you for your interest in contributing! This guide will help you get started.

## Development Setup

### Prerequisites

- Python 3.12+
- Node.js 20+
- Docker & Docker Compose
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- k3s (for Kubernetes integration)

### Clone and Setup

```bash
git clone https://github.com/HardMax71/Integr8sCode.git
cd Integr8sCode

# Install pre-commit hooks (required before submitting PRs)
uv tool install pre-commit
pre-commit install

# Start the development environment
./deploy.sh dev
```

### Pre-commit Hooks

**Before submitting any PR**, ensure pre-commit hooks are installed. They run automatically on `git commit` and check:

- **ruff**: Python linting (style, imports, potential bugs)
- **mypy --strict**: Static type checking
- **eslint**: Frontend TypeScript/Svelte linting
- **svelte-check**: Frontend type checking

Run manually on all files:

```bash
pre-commit run --all-files
```

If hooks fail, fix the issues before committing. The same checks run in CI, so local failures will also fail the pipeline.

### Backend Development

```bash
cd backend

# Install dependencies
uv sync

# Run linting
uv run ruff check . --config pyproject.toml

# Run type checking
uv run mypy --config-file pyproject.toml --strict .

# Run tests
uv run pytest
```

### Frontend Development

```bash
cd frontend

# Install dependencies
npm install

# Run dev server
npm run dev

# Run E2E tests
npx playwright test
```

## Code Style

### Python (Backend)

- Follow PEP 8 with 120 character line limit
- Use type hints for all function signatures
- Ruff handles import sorting and style enforcement
- MyPy strict mode enforces complete type coverage

### TypeScript/Svelte (Frontend)

- Use TypeScript for all new code
- Follow existing component patterns
- Use Svelte 5 runes syntax

## Pull Request Process

1. **Create a feature branch** from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** with clear, atomic commits

3. **Ensure all checks pass**:
   ```bash
   pre-commit run --all-files
   cd backend && uv run pytest
   cd frontend && npx playwright test
   ```

4. **Push and create a PR** against `main`

5. **Fill out the PR template** with:
   - Summary of changes
   - Test plan
   - Any breaking changes

## Commit Messages

Use clear, descriptive commit messages:

```
feat: add user notification preferences
fix: resolve race condition in execution coordinator
docs: update deployment guide for k3s setup
refactor: extract common validation logic
test: add integration tests for DLQ processor
```

## Reporting Issues

Use GitHub Issues with the provided templates:

- **Bug Report**: For unexpected behavior or errors
- **Feature Request**: For new functionality suggestions

Include reproduction steps, environment details, and relevant logs.

## Questions?

Open a GitHub Discussion or reach out via issues.
