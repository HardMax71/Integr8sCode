from prometheus_client import Counter, Histogram, Gauge

SCRIPT_EXECUTIONS = Counter(
    'script_executions_total',
    'Total number of script executions',
    ['status', 'python_version']
)

EXECUTION_DURATION = Histogram(
    'script_execution_duration_seconds',
    'Time spent executing scripts',
    ['python_version']
)

ACTIVE_EXECUTIONS = Gauge(
    'active_executions',
    'Number of currently running script executions'
)