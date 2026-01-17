#!/bin/bash
# =============================================================================
# Integr8sCode Unified Deployment Script
# =============================================================================
#
# Usage:
#   ./deploy.sh dev                 # Start local development (docker-compose)
#   ./deploy.sh dev --build         # Rebuild and start local development
#   ./deploy.sh down                # Stop local development
#   ./deploy.sh prod                # Deploy to K8s (builds images locally)
#   ./deploy.sh prod --prod         # Deploy with production values (uses registry)
#   ./deploy.sh prod --dry-run      # Test Helm deployment without applying
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

# Helm configuration
NAMESPACE="integr8scode"
RELEASE_NAME="integr8scode"
CHART_PATH="./helm/integr8scode"

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

show_help() {
    echo "Integr8sCode Deployment Script"
    echo ""
    echo "Usage: ./deploy.sh <command> [options]"
    echo ""
    echo "Commands:"
    echo "  dev [options]      Start full stack (docker-compose)"
    echo "                     --build             Rebuild images"
    echo "                     --wait              Wait for services to be healthy"
    echo "                     --timeout <secs>    Health check timeout (default: 300)"
    echo "  infra [options]    Start infrastructure only (mongo, redis, kafka, etc.)"
    echo "                     --wait              Wait for services to be healthy"
    echo "                     --timeout <secs>    Health check timeout (default: 120)"
    echo "  down               Stop all services"
    echo "  prod [options]     Deploy to Kubernetes with Helm"
    echo "  check              Run quality checks (ruff, mypy, bandit)"
    echo "  test               Run full test suite"
    echo "  logs [service]     View logs (defaults to all services)"
    echo "  status             Show status of running services"
    echo "  openapi [path]     Generate OpenAPI spec (default: docs/reference/openapi.json)"
    echo "  types              Generate TypeScript types for frontend from OpenAPI spec"
    echo "  help               Show this help message"
    echo ""
    echo "Prod options:"
    echo "  --dry-run          Validate templates without applying"
    echo "  --prod             Use production values (ghcr.io images, no local build)"
    echo "  --local            Force local build even with --prod values"
    echo "  --set key=value    Override Helm values"
    echo ""
    echo "Configuration:"
    echo "  All settings come from backend/.env (single source of truth)"
    echo "  For CI/tests: cp backend/.env.test backend/.env"
    echo "  Observability (Jaeger, Grafana) auto-enabled if OTEL_EXPORTER_OTLP_ENDPOINT is set"
    echo ""
    echo "Examples:"
    echo "  ./deploy.sh dev                    # Start dev environment"
    echo "  ./deploy.sh dev --build            # Rebuild and start"
    echo "  ./deploy.sh dev --wait             # Start and wait for healthy"
    echo "  ./deploy.sh prod                   # Deploy with local images"
    echo "  ./deploy.sh logs backend           # View backend logs"
}

# =============================================================================
# LOCAL DEVELOPMENT (docker-compose)
# =============================================================================
cmd_dev() {
    print_header "Starting Local Development Environment"

    local BUILD_FLAG=""
    local WAIT_FLAG=""
    local WAIT_TIMEOUT="300"

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --build)
                BUILD_FLAG="--build"
                print_info "Rebuilding images..."
                ;;
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

    # Auto-detect observability: enable if OTEL endpoint is configured in .env
    local PROFILE_FLAGS=""
    if grep -q "^OTEL_EXPORTER_OTLP_ENDPOINT=" ./backend/.env 2>/dev/null; then
        PROFILE_FLAGS="--profile observability"
        print_info "Observability enabled (OTEL endpoint configured in .env)"
    else
        print_info "Observability disabled (no OTEL endpoint in .env)"
    fi

    docker compose $PROFILE_FLAGS up -d $BUILD_FLAG $WAIT_FLAG $WAIT_TIMEOUT_FLAG

    echo ""
    print_success "Development environment started!"
    echo ""
    echo "Services:"
    echo "  Backend:   https://localhost:443"
    echo "  Frontend:  https://localhost:5001"
    echo "  Kafdrop:   http://localhost:9000"
    if [[ -n "$PROFILE_FLAGS" ]]; then
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
    # zookeeper-certgen is needed for kafka to start
    docker compose up -d zookeeper-certgen mongo redis zookeeper kafka schema-registry $WAIT_FLAG $WAIT_TIMEOUT_FLAG

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

    echo ""
    echo "Kubernetes Pods (if deployed):"
    kubectl get pods -n "$NAMESPACE" 2>/dev/null || echo "  No Kubernetes deployment found"
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
# KUBERNETES DEPLOYMENT (Helm)
# =============================================================================
build_and_import_images() {
    print_info "Building Docker images..."

    docker build -t base:latest -f ./backend/Dockerfile.base ./backend
    docker build -t integr8scode-backend:latest -f ./backend/Dockerfile ./backend

    if [[ -f ./frontend/Dockerfile.prod ]]; then
        docker build -t integr8scode-frontend:latest -f ./frontend/Dockerfile.prod ./frontend
    else
        docker build -t integr8scode-frontend:latest -f ./frontend/Dockerfile ./frontend
    fi

    print_success "Images built"

    if command -v k3s &> /dev/null; then
        print_info "Importing images to K3s..."
        docker save base:latest | sudo k3s ctr images import -
        docker save integr8scode-backend:latest | sudo k3s ctr images import -
        docker save integr8scode-frontend:latest | sudo k3s ctr images import -
        print_success "Images imported to K3s"
    else
        print_warning "K3s not found - skipping image import"
    fi
}

cmd_prod() {
    print_header "Deploying to Kubernetes"

    local DRY_RUN=""
    local VALUES_FILE="values.yaml"
    local EXTRA_ARGS=""
    local USE_REGISTRY=false
    local FORCE_LOCAL=false

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --dry-run)
                DRY_RUN="--dry-run"
                print_warning "DRY RUN MODE - No changes will be applied"
                ;;
            --prod)
                VALUES_FILE="values-prod.yaml"
                USE_REGISTRY=true
                print_info "Using production values (ghcr.io images)"
                ;;
            --local)
                FORCE_LOCAL=true
                print_info "Forcing local image build"
                ;;
            --set)
                shift
                EXTRA_ARGS="$EXTRA_ARGS --set $1"
                ;;
            *)
                print_error "Unknown option: $1"
                exit 1
                ;;
        esac
        shift
    done

    deploy_helm "$VALUES_FILE" "$DRY_RUN" "$EXTRA_ARGS" "$USE_REGISTRY" "$FORCE_LOCAL"
}

deploy_helm() {
    local VALUES_FILE="$1"
    local DRY_RUN="$2"
    local EXTRA_ARGS="$3"
    local USE_REGISTRY="$4"
    local FORCE_LOCAL="$5"

    # Build images if:
    # - Not dry-run AND
    # - Not using registry OR force local build
    if [[ -z "$DRY_RUN" ]]; then
        if [[ "$USE_REGISTRY" != "true" ]] || [[ "$FORCE_LOCAL" == "true" ]]; then
            build_and_import_images
        else
            print_info "Using pre-built images from ghcr.io (skipping local build)"
        fi
    fi

    print_info "Updating Helm dependencies..."
    helm dependency update "$CHART_PATH"

    print_info "Creating namespace..."
    if [[ -z "$DRY_RUN" ]]; then
        kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
    fi

    print_info "Deploying with Helm..."
    helm upgrade --install "$RELEASE_NAME" "$CHART_PATH" \
        --namespace "$NAMESPACE" \
        --values "$CHART_PATH/$VALUES_FILE" \
        --wait \
        --timeout 10m \
        $DRY_RUN \
        $EXTRA_ARGS

    if [[ -z "$DRY_RUN" ]]; then
        echo ""
        print_success "Deployment complete!"
        echo ""
        echo "Pods:"
        kubectl get pods -n "$NAMESPACE"
        echo ""
        echo "Services:"
        kubectl get services -n "$NAMESPACE"
        echo ""
        if [[ "$VALUES_FILE" == "values-prod.yaml" ]]; then
            echo "Note: Passwords must be set via --set flags for production"
        else
            echo "Default credentials: user/user123, admin/admin123"
        fi
        echo ""
        echo "Commands:"
        echo "  kubectl logs -n $NAMESPACE -l app.kubernetes.io/component=backend"
        echo "  kubectl port-forward -n $NAMESPACE svc/$RELEASE_NAME-backend 8443:443"
        echo "  helm uninstall $RELEASE_NAME -n $NAMESPACE"
    fi
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
    prod)
        shift
        cmd_prod "$@"
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
