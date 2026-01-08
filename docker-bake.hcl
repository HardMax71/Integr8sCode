// Docker Bake file for building all services with proper caching
// Usage: docker buildx bake -f docker-bake.hcl [target]
//
// Targets:
//   base          - Shared Python base image (dependencies only)
//   backend       - Backend API server
//   workers       - All worker services (saga, k8s, pod-monitor, etc.)
//   all           - Everything needed for E2E tests
//
// CI Usage:
//   docker buildx bake -f docker-bake.hcl all \
//     --set *.cache-from=type=gha \
//     --set *.cache-to=type=gha,mode=max

// Variables for cache configuration (can be overridden via --set)
variable "CACHE_FROM" {
  default = ""
}

variable "CACHE_TO" {
  default = ""
}

// Base image - contains Python, system deps, and all Python dependencies
// This is the most important layer to cache since it rarely changes
target "base" {
  context    = "./backend"
  dockerfile = "Dockerfile.base"
  tags       = ["integr8scode-base:latest"]
  cache-from = CACHE_FROM != "" ? [CACHE_FROM] : []
  cache-to   = CACHE_TO != "" ? [CACHE_TO] : []
}

// Backend API server
target "backend" {
  context    = "./backend"
  dockerfile = "Dockerfile"
  tags       = ["integr8scode-backend:latest"]
  contexts = {
    base = "target:base"
  }
  cache-from = CACHE_FROM != "" ? [CACHE_FROM] : []
  cache-to   = CACHE_TO != "" ? [CACHE_TO] : []
}

// Certificate generator for Zookeeper/Kafka
target "zookeeper-certgen" {
  context    = "./backend/zookeeper"
  dockerfile = "Dockerfile.certgen"
  tags       = ["integr8scode-zookeeper-certgen:latest"]
  cache-from = CACHE_FROM != "" ? [CACHE_FROM] : []
  cache-to   = CACHE_TO != "" ? [CACHE_TO] : []
}

// Certificate generator for TLS (mkcert)
target "cert-generator" {
  context    = "./cert-generator"
  dockerfile = "Dockerfile"
  tags       = ["integr8scode-cert-generator:latest"]
  cache-from = CACHE_FROM != "" ? [CACHE_FROM] : []
  cache-to   = CACHE_TO != "" ? [CACHE_TO] : []
}

// Execution Coordinator worker
target "coordinator" {
  context    = "./backend"
  dockerfile = "workers/Dockerfile.coordinator"
  tags       = ["integr8scode-coordinator:latest"]
  contexts = {
    base = "target:base"
  }
  cache-from = CACHE_FROM != "" ? [CACHE_FROM] : []
  cache-to   = CACHE_TO != "" ? [CACHE_TO] : []
}

// Saga Orchestrator worker
target "saga-orchestrator" {
  context    = "./backend"
  dockerfile = "workers/Dockerfile.saga_orchestrator"
  tags       = ["integr8scode-saga-orchestrator:latest"]
  contexts = {
    base = "target:base"
  }
  cache-from = CACHE_FROM != "" ? [CACHE_FROM] : []
  cache-to   = CACHE_TO != "" ? [CACHE_TO] : []
}

// Kubernetes Worker
target "k8s-worker" {
  context    = "./backend"
  dockerfile = "workers/Dockerfile.k8s_worker"
  tags       = ["integr8scode-k8s-worker:latest"]
  contexts = {
    base = "target:base"
  }
  cache-from = CACHE_FROM != "" ? [CACHE_FROM] : []
  cache-to   = CACHE_TO != "" ? [CACHE_TO] : []
}

// Pod Monitor worker
target "pod-monitor" {
  context    = "./backend"
  dockerfile = "workers/Dockerfile.pod_monitor"
  tags       = ["integr8scode-pod-monitor:latest"]
  contexts = {
    base = "target:base"
  }
  cache-from = CACHE_FROM != "" ? [CACHE_FROM] : []
  cache-to   = CACHE_TO != "" ? [CACHE_TO] : []
}

// Result Processor worker
target "result-processor" {
  context    = "./backend"
  dockerfile = "workers/Dockerfile.result_processor"
  tags       = ["integr8scode-result-processor:latest"]
  contexts = {
    base = "target:base"
  }
  cache-from = CACHE_FROM != "" ? [CACHE_FROM] : []
  cache-to   = CACHE_TO != "" ? [CACHE_TO] : []
}

// Event Replay service
target "event-replay" {
  context    = "./backend"
  dockerfile = "workers/Dockerfile.event_replay"
  tags       = ["integr8scode-event-replay:latest"]
  contexts = {
    base = "target:base"
  }
  cache-from = CACHE_FROM != "" ? [CACHE_FROM] : []
  cache-to   = CACHE_TO != "" ? [CACHE_TO] : []
}

// DLQ Processor service
target "dlq-processor" {
  context    = "./backend"
  dockerfile = "workers/Dockerfile.dlq_processor"
  tags       = ["integr8scode-dlq-processor:latest"]
  contexts = {
    base = "target:base"
  }
  cache-from = CACHE_FROM != "" ? [CACHE_FROM] : []
  cache-to   = CACHE_TO != "" ? [CACHE_TO] : []
}

// Frontend
target "frontend" {
  context    = "./frontend"
  dockerfile = "Dockerfile"
  tags       = ["integr8scode-frontend:latest"]
  cache-from = CACHE_FROM != "" ? [CACHE_FROM] : []
  cache-to   = CACHE_TO != "" ? [CACHE_TO] : []
}

// =============================================================================
// GROUP TARGETS
// =============================================================================

// All worker services
group "workers" {
  targets = [
    "coordinator",
    "saga-orchestrator",
    "k8s-worker",
    "pod-monitor",
    "result-processor",
  ]
}

// Infrastructure build targets (certs)
group "infra" {
  targets = [
    "zookeeper-certgen",
  ]
}

// Backend E2E tests - everything needed except frontend
group "backend-e2e" {
  targets = [
    "base",
    "backend",
    "zookeeper-certgen",
    "cert-generator",
    "coordinator",
    "saga-orchestrator",
    "k8s-worker",
    "pod-monitor",
    "result-processor",
  ]
}

// Full stack
group "all" {
  targets = [
    "base",
    "backend",
    "zookeeper-certgen",
    "cert-generator",
    "coordinator",
    "saga-orchestrator",
    "k8s-worker",
    "pod-monitor",
    "result-processor",
    "event-replay",
    "dlq-processor",
    "frontend",
  ]
}

// Default target
group "default" {
  targets = ["backend-e2e"]
}
