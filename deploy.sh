#!/bin/bash
# =============================================================================
# Integr8sCode Deployment Script (Docker Compose)
# =============================================================================
#
# Usage:
#   ./deploy.sh dev                 # Start local development (docker-compose)
#   ./deploy.sh dev --build         # Rebuild and start local development
#   ./deploy.sh down                # Stop local development
#   ./deploy.sh check               # Run local quality checks (lint, type, security)
#   ./deploy.sh test                # Run full test suite locally
#   ./deploy.sh logs [service]      # View logs (dev mode)
#   ./deploy.sh status              # Show status of running services
#   ./deploy.sh openapi [path]      # Generate OpenAPI spec from backend
#   ./deploy.sh types               # Generate TypeScript types for frontend
#
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_header() {
    echo -e "${BLUE}"
    echo "==========================================================================="
    echo "  $1"
    echo "==========================================================================="
    echo -e "${NC}"
}

print_success() { echo -e "${GREEN}✓ $1${NC}"; }
print_warning() { echo -e "${YELLOW}⚠ $1${NC}"; }
print_error() { echo -e "${RED}✗ $1${NC}"; }
print_info() { echo -e "${BLUE}→ $1${NC}"; }

# --8<-- [start:usage]
show_help() {
    echo "Integr8sCode Deployment Script"
    echo ""
    echo "Usage: ./deploy.sh <command> [options]"
    echo ""
    echo "Commands:"
    echo "  dev [options]      Start full stack (docker-compose)"
    echo "                     --build             Rebuild images locally"
    echo "                     --no-build          Use pre-built images only (no build fallback)"
    echo "                     --wait              Wait for services to be healthy"
    echo "                     --timeout <secs>    Health check timeout (default: 300)"
    echo "                     --observability     Include Grafana, Jaeger, etc."
    echo "                     --debug             Include observability + Kafdrop"
    echo "  infra [options]    Start infrastructure only (mongo, redis, kafka, etc.)"
    echo "                     --wait              Wait for services to be healthy"
    echo "                     --timeout <secs>    Health check timeout (default: 120)"
    echo "  down               Stop all services"
    echo "  check              Run quality checks (ruff, mypy, bandit)"
    echo "  test               Run full test suite"
    echo "  logs [service]     View logs (defaults to all services)"
    echo "  status             Show status of running services"
    echo "  openapi [path]     Generate OpenAPI spec (default: docs/reference/openapi.json)"
    echo "  types              Generate TypeScript types for frontend from OpenAPI spec"
    echo "  help               Show this help message"
    echo ""
    echo "Configuration:"
    echo "  All settings come from backend/config.toml (single source of truth)"
    echo "  For CI/tests: cp backend/config.test.toml backend/config.toml"
    echo ""
    echo "Examples:"
    echo "  ./deploy.sh dev                    # Start dev environment"
    echo "  ./deploy.sh dev --build            # Rebuild and start"
    echo "  ./deploy.sh dev --wait             # Start and wait for healthy"
    echo "  ./deploy.sh logs backend           # View backend logs"
}
# --8<-- [end:usage]

# =============================================================================
# LOCAL DEVELOPMENT (docker-compose)
# =============================================================================
cmd_dev() {
    print_header "Starting Local Development Environment"

    local BUILD_FLAG=""
    local NO_BUILD_FLAG=""
    local WAIT_FLAG=""
    local WAIT_TIMEOUT="300"
    local PROFILE_FLAGS=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --build)
                BUILD_FLAG="--build"
                print_info "Rebuilding images..."
                ;;
            --no-build)
                NO_BUILD_FLAG="--no-build"
                print_info "Using pre-built images (skipping build)..."
                ;;
            --wait)
                WAIT_FLAG="--wait"
                ;;
            --timeout)
                shift
                WAIT_TIMEOUT="$1"
                ;;
            --observability)
                PROFILE_FLAGS="--profile observability"
                print_info "Including observability stack (Grafana, Jaeger, etc.)"
                ;;
            --debug)
                PROFILE_FLAGS="--profile observability --profile debug"
                print_info "Including observability + debug tools (Kafdrop, etc.)"
                ;;
        esac
        shift
    done

    local WAIT_TIMEOUT_FLAG=""
    if [[ -n "$WAIT_FLAG" ]]; then
        WAIT_TIMEOUT_FLAG="--wait-timeout $WAIT_TIMEOUT"
    fi

    docker compose $PROFILE_FLAGS up -d $BUILD_FLAG $NO_BUILD_FLAG $WAIT_FLAG $WAIT_TIMEOUT_FLAG

    echo ""
    print_success "Development environment started!"
    echo ""
    echo "Services:"
    echo "  Backend:   https://localhost:443"
    echo "  Frontend:  https://localhost:5001"
    if [[ "$PROFILE_FLAGS" == *"debug"* ]]; then
        echo "  Kafdrop:   http://localhost:9000"
    fi
    if [[ "$PROFILE_FLAGS" == *"observability"* ]]; then
        echo "  Jaeger:    http://localhost:16686"
        echo "  Grafana:   http://localhost:3000"
    fi
    echo ""
    echo "Commands:"
    echo "  ./deploy.sh logs             # View all logs"
    echo "  ./deploy.sh logs backend     # View backend logs"
    echo "  ./deploy.sh down             # Stop all services"
}

cmd_down() {
    print_header "Stopping Local Development Environment"
    docker compose down
    print_success "All services stopped"
}

cmd_infra() {
    print_header "Starting Infrastructure Services Only"

    local WAIT_FLAG=""
    local WAIT_TIMEOUT="120"

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --wait)
                WAIT_FLAG="--wait"
                ;;
            --timeout)
                shift
                WAIT_TIMEOUT="$1"
                ;;
        esac
        shift
    done

    local WAIT_TIMEOUT_FLAG=""
    if [[ -n "$WAIT_FLAG" ]]; then
        WAIT_TIMEOUT_FLAG="--wait-timeout $WAIT_TIMEOUT"
    fi

    # Start only infrastructure services (no app, no workers, no observability)
    docker compose up -d mongo redis kafka $WAIT_FLAG $WAIT_TIMEOUT_FLAG

    print_success "Infrastructure services started"
    docker compose ps
}

cmd_logs() {
    local SERVICE="$1"
    if [[ -n "$SERVICE" ]]; then
        docker compose logs -f "$SERVICE"
    else
        docker compose logs -f
    fi
}

cmd_status() {
    print_header "Service Status"

    echo ""
    echo "Docker Compose Services:"
    docker compose ps 2>/dev/null || echo "  No docker-compose services running"
}

# =============================================================================
# QUALITY CHECKS
# =============================================================================
cmd_check() {
    print_header "Running Quality Checks"

    cd backend

    print_info "Running Ruff linting..."
    if uv run ruff check . --config pyproject.toml; then
        print_success "Ruff linting passed"
    else
        print_error "Ruff linting failed"
        exit 1
    fi

    print_info "Running MyPy type checking..."
    if uv run mypy --config-file pyproject.toml .; then
        print_success "MyPy type checking passed"
    else
        print_error "MyPy type checking failed"
        exit 1
    fi

    print_info "Running Bandit security scan..."
    if uv run bandit -r . -x tests/ -ll; then
        print_success "Security scan passed"
    else
        print_error "Security scan failed"
        exit 1
    fi

    cd ..
    print_success "All quality checks passed!"
}

# =============================================================================
# TEST SUITE
# =============================================================================
cmd_test() {
    print_header "Running Test Suite"

    print_info "Starting full stack..."
    cmd_dev --build --wait

    print_info "Running tests inside Docker..."
    if docker compose exec -T backend \
        uv run pytest tests/integration tests/unit -v --cov=app --cov-report=term; then
        print_success "All tests passed!"
        TEST_RESULT=0
    else
        print_error "Tests failed"
        TEST_RESULT=1
    fi

    print_info "Cleaning up..."
    docker compose down

    exit $TEST_RESULT
}

# =============================================================================
# OPENAPI SPEC GENERATION
# =============================================================================
cmd_openapi() {
    print_header "Generating OpenAPI Spec"

    local OUTPUT="${1:-docs/reference/openapi.json}"

    cd backend
    print_info "Extracting schema from FastAPI app..."

    uv run python -c "
import json
from app.main import create_app
app = create_app()
schema = app.openapi()
print(json.dumps(schema, indent=2))
" > "../$OUTPUT"

    cd ..
    print_success "OpenAPI spec written to $OUTPUT"
}

# =============================================================================
# TYPESCRIPT API CLIENT GENERATION
# =============================================================================
cmd_types() {
    print_header "Generating TypeScript API Client"

    # Ensure OpenAPI spec exists
    if [[ ! -f "docs/reference/openapi.json" ]]; then
        print_info "OpenAPI spec not found, generating first..."
        cmd_openapi
    fi

    cd frontend
    print_info "Generating typed API client from OpenAPI spec..."
    npm run generate:api
    cd ..

    print_success "Typed API client generated in frontend/src/lib/api/"
}

# =============================================================================
# MAIN
# =============================================================================
case "${1:-help}" in
    dev)
        shift
        cmd_dev "$@"
        ;;
    infra)
        shift
        cmd_infra "$@"
        ;;
    down)
        cmd_down
        ;;
    logs)
        cmd_logs "$2"
        ;;
    status)
        cmd_status
        ;;
    check)
        cmd_check
        ;;
    test)
        cmd_test
        ;;
    openapi)
        cmd_openapi "$2"
        ;;
    types)
        cmd_types
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        print_error "Unknown command: $1"
        echo ""
        show_help
        exit 1
        ;;
esac
