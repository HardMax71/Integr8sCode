# Contract testing

The Grafana dashboards and the metric definitions name the same series, but nothing ties them together at runtime. A renamed metric leaves a dead panel, and a new metric nobody charts goes unnoticed. [`tests/contract/test_grafana_metrics.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/tests/contract/test_grafana_metrics.py) checks both directions without running the stack.

## How it gets the real names

A module-scoped fixture sets up OTel `MeterProvider`s with a `PrometheusMetricReader`, so the SDK does the name conversion instead of the test guessing it. On one provider it creates an instrument for each metric the collector's `signaltometrics` connector makes from spans, with the name, unit and kind from `otel-collector-config.yaml`; these are all the app's metrics. The libraries go on a second one, set up the way the app sets them up: FastStream's `KafkaTelemetryMiddleware`, the FastAPI instrumentation on a bare app whose middleware stack it builds (that's when the instrumentation creates its instruments), and the system metrics instrumentation with the app's `PROCESS_METRICS`. Then it gives every instrument one data point: observable instruments get a stub callback, and synchronous ones get whichever of `add`, `record` or `set` they have. The result is two maps from Prometheus family name to sample names (`_total`, `_bucket`, `_count`, `_sum` and so on), one for app metrics and one for the libraries'.

Family names follow the collector, not the Python exporter. The Python exporter appends the unit unless the name already ends with it; the collector's translator skips the unit when it's any token of the name. So an up-down counter named `jobs_active` with unit `jobs` stays `jobs_active` in Victoria Metrics, while the Python exporter alone would call it `jobs_active_jobs`. `_collector_name` applies the collector's rule, and dashboards must use the collector's name.

On the Grafana side, the test reads every `expr` from the dashboard JSON files and from the alert rule YAML in `provisioning/alerting/` and parses it with [promql-parser](https://github.com/messense/py-promql-parser). `promql_parser.walk` visits every node of the query, and the name of each vector selector is a metric the query reads. Functions, label names and strings never look like metric names, since the parser knows what each token is.

## The checks

All three tests carry the `grafana_contract` marker.

`test_grafana_metrics_have_a_source` fails when a dashboard or alert rule queries a series that nothing emits. Queries on the Loki datasource are LogQL and name no metrics, so the test skips them. A name counts as emitted if it's an app sample, a library sample, or starts with one of the collector prefixes in `COLLECTOR_PREFIXES`. That allowlist is short on purpose: `container_` for the collector's docker_stats receiver, `kafka_` for its kafka_metrics receiver, `mongodb_` for its mongodb receiver and `system_` for its `host_metrics` scrapers.

`test_code_metrics_used_in_dashboards` fails when an app metric family appears in no dashboard or alert rule. One sample per family is enough, so a histogram is covered by any of its `_bucket`, `_count` or `_sum`. The SDK's `target` family is skipped. The libraries' families aren't required to be charted.

`test_collector_prefixes_do_not_cover_python_metrics` fails if a collector prefix also matches a metric that Python emits. Otherwise a typo in such a metric would hide behind the allowlist.

## Running

CI runs them in the Grafana Contract Tests job whenever `backend/` or one of the service config folders (`grafana/`, `otel-collector/` and the rest) changes:

```bash
cd backend
uv run pytest tests/contract -m grafana_contract
```

The pytest-env setting `OTEL_SDK_DISABLED=true` is popped for the fixture's lifetime and restored afterwards, so the real SDK runs.

## Adding a metric

Define a metric under `signaltometrics` in `otel-collector-config.yaml` and the reverse check fails until a dashboard panel or alert rule uses it. Add a panel for a series that doesn't exist and the forward check fails, naming the dashboard file and the metric. A new collector receiver needs its prefix added to `COLLECTOR_PREFIXES` before dashboards can use its series.
