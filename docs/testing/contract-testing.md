# Contract testing

The Grafana dashboards and the Python metric code name the same series, but nothing ties them together at runtime. A renamed metric leaves a dead panel, and a new metric nobody charts goes unnoticed. [`tests/contract/test_grafana_metrics.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/tests/contract/test_grafana_metrics.py) checks both directions without running the stack.

## How it gets the real names

A module-scoped fixture sets up OTel `MeterProvider`s with a `PrometheusMetricReader`, so the SDK does the name conversion instead of the test guessing it. It imports every module in `app.core.metrics`, instantiates every `BaseMetrics` subclass, the `MetricsMiddleware` and the system metrics on one provider, and FastStream's `KafkaTelemetryMiddleware` on a second one. Then it gives every instrument one data point: observable instruments get a stub callback, and synchronous ones get whichever of `add`, `record` or `set` they have. The result is two maps from Prometheus family name to sample names (`_total`, `_bucket`, `_count`, `_sum` and so on), one for app metrics and one for FastStream's.

Family names follow the collector, not the Python exporter. The Python exporter appends the unit unless the name already ends with it; the collector's translator skips the unit when it's any token of the name. So the up-down counter `http_requests_active` with unit `requests` stays `http_requests_active` in Victoria Metrics, while the Python exporter alone would call it `http_requests_active_requests`. `_collector_name` applies the collector's rule, and dashboards must use the collector's name.

On the Grafana side, the test reads every `expr` from the dashboard JSON files and from the alert rule YAML in `provisioning/alerting/`, strips strings, label matchers, ranges and `by`/`without` clauses, and drops PromQL functions and keywords. What's left are metric names.

## The checks

All three tests carry the `grafana_contract` marker.

`test_grafana_metrics_have_a_source` fails when a dashboard or alert rule queries a series that nothing emits. A name counts as emitted if it's an app sample, a FastStream sample, or starts with one of the collector prefixes in `COLLECTOR_PREFIXES`. That allowlist is short on purpose: `mongodb_` for the collector's mongodb receiver and `system_memory_utilization_` for the host memory scraper the alert rules use.

`test_code_metrics_used_in_dashboards` fails when an app metric family appears in no dashboard or alert rule. One sample per family is enough, so a histogram is covered by any of its `_bucket`, `_count` or `_sum`. The SDK's `target` family is skipped. FastStream's families aren't required to be charted.

`test_collector_prefixes_do_not_cover_python_metrics` fails if a collector prefix also matches a metric that Python emits. Otherwise a typo in such a metric would hide behind the allowlist.

## Running

CI runs them in the backend unit job, right after the unit tests:

```bash
cd backend
uv run pytest tests/contract -m grafana_contract
```

The pytest-env setting `OTEL_SDK_DISABLED=true` is popped for the fixture's lifetime and restored afterwards, so the real SDK runs.

## Adding a metric

Add the instrument to a `BaseMetrics` subclass and the reverse check fails until a dashboard panel or alert rule uses it. Add a panel for a series that doesn't exist and the forward check fails, naming the dashboard file and the metric. A new collector receiver needs its prefix added to `COLLECTOR_PREFIXES` before dashboards can use its series.
