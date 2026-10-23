import json
from collections.abc import Iterator
from pathlib import Path
from typing import NotRequired, TypedDict

import promql_parser
import pytest
import yaml
from fastapi import FastAPI
from faststream.kafka.opentelemetry import KafkaTelemetryMiddleware
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.system_metrics import SystemMetricsInstrumentor
from opentelemetry.metrics import CallbackOptions, Meter, Observation
from opentelemetry.sdk.metrics import MeterProvider
from prometheus_client.metrics_core import Metric

from app.core.metrics.base import PROCESS_METRICS

REPO_ROOT = Path(__file__).resolve().parents[3]
GRAFANA_DIR = REPO_ROOT / "grafana" / "provisioning"
DASHBOARDS_DIR = GRAFANA_DIR / "dashboards"
ALERTING_DIR = GRAFANA_DIR / "alerting"
COLLECTOR_CONFIG = REPO_ROOT / "otel-collector" / "otel-collector-config.yaml"

# Series written by otel-collector receivers rather than by any Python process, keyed by name prefix.
COLLECTOR_PREFIXES: dict[str, str] = {
    "container_": "docker_stats receiver",
    "kafka_": "kafka_metrics receiver",
    "mongodb_": "mongodb receiver",
    "system_": "host_metrics receiver",
}


class _Sum(TypedDict):
    value: str
    monotonic: NotRequired[bool]


class _SpanMetric(TypedDict):
    """One metric the collector's signaltometrics connector makes from spans."""

    name: str
    unit: NotRequired[str]
    sum: NotRequired[_Sum]
    gauge: NotRequired[object]
    histogram: NotRequired[object]


def _create_span_metrics(meter: Meter) -> None:
    """Create an SDK instrument for each metric the collector derives from spans, with its name, unit and kind."""
    span_metrics: list[_SpanMetric] = yaml.safe_load(COLLECTOR_CONFIG.read_text())["connectors"]["signaltometrics"][
        "spans"
    ]
    for metric in span_metrics:
        name, unit = metric["name"], metric.get("unit", "")
        if "histogram" in metric:
            meter.create_histogram(name, unit=unit)
        elif "gauge" in metric:
            meter.create_gauge(name, unit=unit)
        elif metric["sum"].get("monotonic", False):
            meter.create_counter(name, unit=unit)
        else:
            meter.create_up_down_counter(name, unit=unit)


def _stub_observation(_: CallbackOptions) -> list[Observation]:
    return [Observation(1)]


def _trigger_instruments(provider: MeterProvider) -> None:
    """Give every instrument one data point so the reader emits its family."""
    for meter in provider._meters.values():
        for instrument in meter._instrument_id_instrument.values():
            if hasattr(instrument, "_callbacks"):
                instrument._callbacks = [_stub_observation]
                continue
            for method_name in ("add", "record", "set"):
                method = getattr(instrument, method_name, None)
                if method is not None:
                    method(1)
                    break


def _collector_name(family: Metric) -> str:
    """Name a family the way the collector's Prometheus translator does.

    The Python exporter appends the unit unless the name already ends with it, while the
    collector skips it when the unit is any token of the name (``http_requests_active``).
    """
    suffix = f"_{family.unit}"
    if family.unit and family.name.endswith(suffix):
        base = family.name.removesuffix(suffix)
        if family.unit in base.split("_"):
            return base
    return family.name


def _families(reader: PrometheusMetricReader) -> dict[str, set[str]]:
    families: dict[str, set[str]] = {}
    for family in reader._collector.collect():
        name = _collector_name(family)
        samples = {name + sample.name.removeprefix(family.name) for sample in family.samples}
        if samples:
            families[name] = samples
    return families


@pytest.fixture(scope="module")
def produced_families() -> Iterator[tuple[dict[str, set[str]], dict[str, set[str]]]]:
    """Run every span metric the collector defines and the libraries' telemetry through the real OTel SDK.

    The libraries are FastStream's Kafka middleware and the FastAPI and system metrics instrumentations,
    configured the way the app configures them.

    Yields:
        App families and library families, each mapping family name to its sample names.
    """
    with pytest.MonkeyPatch.context() as mp:
        # pytest-env sets OTEL_SDK_DISABLED=true, and the providers below need the real SDK
        mp.delenv("OTEL_SDK_DISABLED", raising=False)
        app_reader = PrometheusMetricReader()
        app_provider = MeterProvider(metric_readers=[app_reader])
        lib_reader = PrometheusMetricReader()
        lib_provider = MeterProvider(metric_readers=[lib_reader])

        _create_span_metrics(app_provider.get_meter("signaltometrics"))
        KafkaTelemetryMiddleware(meter_provider=lib_provider)
        api = FastAPI()
        FastAPIInstrumentor.instrument_app(api, meter_provider=lib_provider)
        # The instrumentation's ASGI middleware creates its instruments when the stack is built
        api.build_middleware_stack()
        system_metrics = SystemMetricsInstrumentor(config=PROCESS_METRICS)
        system_metrics.instrument(meter_provider=lib_provider)

        _trigger_instruments(app_provider)
        _trigger_instruments(lib_provider)
        yield _families(app_reader), _families(lib_reader)
    system_metrics.uninstrument()
    app_provider.shutdown()
    lib_provider.shutdown()


def _collect_exprs(obj: object, out: list[str]) -> None:
    """Recursively extract ``expr`` field values from Grafana dashboard or alerting data."""
    if isinstance(obj, dict):
        match obj:
            # LogQL, which promql-parser can't read; metric names only appear in the PromQL queries
            case {"datasourceUid": "loki"} | {"datasource": {"uid": "loki"}} | {"datasource": "Loki"}:
                return
        for key, value in obj.items():
            if key == "expr" and isinstance(value, str):
                out.append(value)
            else:
                _collect_exprs(value, out)
    elif isinstance(obj, list):
        for item in obj:
            _collect_exprs(item, out)


class _SelectorNames:
    """Collects the metric names of a query's selectors while ``promql_parser.walk`` visits its nodes."""

    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit(self, node: promql_parser.Expr) -> None:
        match node:
            case promql_parser.VectorSelector(name=str(name)):
                self.names.add(name)


def _grafana_metrics() -> dict[str, set[str]]:
    """Return ``{file_name: {metric_name, ...}}`` for all dashboards and alert rule files."""
    sources = [(p, json.loads(p.read_text())) for p in sorted(DASHBOARDS_DIR.glob("*.json"))]
    sources += [(p, yaml.safe_load(p.read_text())) for p in sorted(ALERTING_DIR.glob("*.yml"))]
    result: dict[str, set[str]] = {}
    for path, data in sources:
        exprs: list[str] = []
        _collect_exprs(data, exprs)
        selectors = _SelectorNames()
        for expr in exprs:
            promql_parser.walk(promql_parser.parse(expr), pre_visit=selectors.visit)
        if selectors.names:
            result[path.name] = selectors.names
    return result


def _from_collector(name: str) -> bool:
    return name.startswith(tuple(COLLECTOR_PREFIXES))


@pytest.mark.grafana_contract
def test_grafana_metrics_have_a_source(
    produced_families: tuple[dict[str, set[str]], dict[str, set[str]]],
) -> None:
    """Every metric a dashboard or alert queries comes from app code, a library's telemetry or a collector receiver."""
    known: set[str] = set()
    for families in produced_families:
        for samples in families.values():
            known |= samples

    orphaned: dict[str, set[str]] = {}
    for source, names in _grafana_metrics().items():
        missing = {n for n in names - known if not _from_collector(n)}
        if missing:
            orphaned[source] = missing

    if orphaned:
        lines = ["Grafana queries metrics that nothing emits:\n"]
        for source, names in sorted(orphaned.items()):
            lines.append(f"  {source}:")
            for n in sorted(names):
                lines.append(f"    - {n}")
        pytest.fail("\n".join(lines))


@pytest.mark.grafana_contract
def test_code_metrics_used_in_dashboards(
    produced_families: tuple[dict[str, set[str]], dict[str, set[str]]],
) -> None:
    """Every metric defined in Python OTel code must appear in a Grafana dashboard."""
    app_families, _ = produced_families
    all_dashboard_metrics: set[str] = set()
    for names in _grafana_metrics().values():
        all_dashboard_metrics |= names

    auto_generated = {"target"}
    unused: dict[str, set[str]] = {}
    for family_name, sample_names in sorted(app_families.items()):
        if family_name in auto_generated:
            continue
        if not sample_names & all_dashboard_metrics:
            unused[family_name] = sample_names

    if unused:
        lines = ["Code defines metrics not used in any Grafana dashboard:\n"]
        for family, samples in sorted(unused.items()):
            lines.append(f"  {family}:")
            for s in sorted(samples):
                lines.append(f"    - {s}")
        pytest.fail("\n".join(lines))


@pytest.mark.grafana_contract
def test_collector_prefixes_do_not_cover_python_metrics(
    produced_families: tuple[dict[str, set[str]], dict[str, set[str]]],
) -> None:
    """A collector prefix must not swallow a metric that Python code emits, or typos in it would pass."""
    shadowed = {
        sample
        for families in produced_families
        for samples in families.values()
        for sample in samples
        if _from_collector(sample)
    }
    assert not shadowed, f"COLLECTOR_PREFIXES also match Python metrics: {sorted(shadowed)}"
