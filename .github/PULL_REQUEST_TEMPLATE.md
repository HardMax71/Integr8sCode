## Summary

<!-- Briefly describe what this PR does. Link to related issues if applicable. -->

Fixes #

## Changes

<!-- List the key changes made in this PR -->

-
-
-

## Type of Change

<!-- Mark the relevant option(s) -->

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to change)
- [ ] Documentation update
- [ ] Refactoring (no functional changes)
- [ ] CI/CD or tooling changes

## Test Plan

<!-- Describe how you tested your changes -->

- [ ] Backend unit tests pass (`cd backend && uv run pytest tests/unit`)
- [ ] Frontend unit tests pass (`cd frontend && npm run test`)
- [ ] Backend E2E tests pass (`docker compose exec -T backend sh -c 'uv sync --group test --no-dev --frozen --no-install-project --no-build && pytest tests/e2e'`)
- [ ] Frontend E2E tests pass (`cd frontend && npm run test:e2e`)
- [ ] API spec and client regenerated if routes or schemas changed (`uv run python -m scripts.export_openapi` in backend/, then `npm run generate:api` in frontend/), never edited by hand
- [ ] Manual testing performed

**Manual test steps:**

1.
2.
3.

## Checklist

- [ ] My code follows the project's style guidelines
- [ ] I have run `pre-commit run --all-files` and all checks pass
- [ ] I have added tests that prove my fix/feature works
- [ ] I have updated documentation if needed
- [ ] My changes don't introduce new warnings

## Screenshots (if applicable)

<!-- Add screenshots for UI changes -->
