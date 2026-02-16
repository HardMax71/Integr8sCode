from __future__ import annotations

import importlib
import json
import os
import pkgutil
import re
from pathlib import Path
from unittest.mock import MagicMock

import app.core.metrics as metrics_pkg
import pytest
from app.core.metrics.base import BaseMetrics
from app.core.middlewares.metrics import MetricsMiddleware, create_system_metrics
from opentelemetry import metrics as otel_api
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.metrics import MeterProvider

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
DASHBOARDS_DIR = BACKEND_ROOT / "grafana" / "provisioning" / "dashboards"

PROMQL_BUILTINS = frozenset({
    "sum", "avg", "min", "max", "count", "stddev", "stdvar", "group",
    "count_values", "topk", "bottomk", "quantile",
    "by", "without", "on", "ignoring", "group_left", "group_right", "bool",
    "sum_over_time", "avg_over_time", "min_over_time", "max_over_time",
    "count_over_time", "stddev_over_time", "stdvar_over_time",
    "last_over_time", "present_over_time", "quantile_over_time",
    "rate", "irate", "increase", "delta", "idelta", "deriv", "predict_linear",
    "histogram_quantile", "histogram_avg", "histogram_count", "histogram_sum",
    "histogram_fraction", "histogram_stddev", "histogram_stdvar",
    "holt_winters",
    "changes", "resets",
    "vector", "scalar", "time", "timestamp",
    "absent", "absent_over_time", "sgn",
    "sort", "sort_desc", "sort_by_label", "sort_by_label_desc",
    "label_replace", "label_join",
    "round", "ceil", "floor", "clamp", "clamp_min", "clamp_max",
    "abs", "sqrt", "ln", "log2", "log10", "exp", "exp2",
    "acos", "asin", "atan", "atan2", "cos", "sin", "tan",
    "acosh", "asinh", "atanh", "cosh", "sinh", "tanh",
    "deg", "rad", "pi",
    "day_of_month", "day_of_week", "day_of_year", "days_in_month",
    "hour", "minute", "month", "year",
    "or", "and", "unless",
    "offset", "inf", "nan",
    "le", "result", "status", "type", "format", "table", "instant",
})


@pytest.fixture(scope="module")
def prometheus_families() -> dict[str, set[str]]:
    """Instantiate every metric class through the real OTel -> Prometheus pipeline.

    Returns:
        Mapping of family name to set of sample names produced by that family.
    """
    # pytest-env sets OTEL_SDK_DISABLED=true; override so the real SDK is active.
    os.environ.pop("OTEL_SDK_DISABLED", None)

    reader = PrometheusMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    otel_api.set_meter_provider(provider)

    for _, mod_name, _ in pkgutil.iter_modules(metrics_pkg.__path__):
        importlib.import_module(f"app.core.metrics.{mod_name}")

    for cls in BaseMetrics.__subclasses__():
        cls(MagicMock())
    MetricsMiddleware(MagicMock())
    create_system_metrics()

    # Trigger every synchronous instrument via the SDK meter registry.
    # Duck-typed getattr dispatch — no isinstance, works for any instrument type.
    for meter in provider._meters.values():
        for instrument in meter._instrument_id_instrument.values():
            for method_name in ("add", "record", "set"):
                method = getattr(instrument, method_name, None)
                if method is not None:
                    method(1)
                    break

    families: dict[str, set[str]] = {}
    for family in reader._collector.collect():
        sample_names: set[str] = set()
        for sample in family.samples:
            sample_names.add(sample.name)
        if sample_names:
            families[family.name] = sample_names
    return families


def _collect_exprs(obj: object, out: list[str]) -> None:
    """Recursively extract ``expr`` field values from a Grafana dashboard JSON."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "expr" and isinstance(value, str):
                out.append(value)
            else:
                _collect_exprs(value, out)
    elif isinstance(obj, list):
        for item in obj:
            _collect_exprs(item, out)


def _extract_metric_names(expr: str) -> set[str]:
    """Extract Prometheus metric names from a PromQL expression."""
    expr = re.sub(r'"[^"]*"', "", expr)
    expr = re.sub(r"\{[^}]*\}", "", expr)
    expr = re.sub(r"\[[^\]]*\]", "", expr)
    expr = re.sub(r"\b(?:by|without)\s*\([^)]*\)", "", expr, flags=re.IGNORECASE)
    tokens = re.findall(r"[a-zA-Z_:][a-zA-Z0-9_:]*", expr)
    return {t for t in tokens if t.lower() not in PROMQL_BUILTINS and ("_" in t or len(t) > 3)}


def _dashboard_metrics() -> dict[str, set[str]]:
    """Return ``{dashboard_filename: {metric_name, ...}}`` for all dashboards."""
    result: dict[str, set[str]] = {}
    for path in sorted(DASHBOARDS_DIR.glob("*.json")):
        data = json.loads(path.read_text())
        exprs: list[str] = []
        _collect_exprs(data, exprs)
        metrics: set[str] = set()
        for expr in exprs:
            metrics |= _extract_metric_names(expr)
        if metrics:
            result[path.name] = metrics
    return result


@pytest.mark.grafana_contract
def test_dashboard_metrics_defined_in_code(
    prometheus_families: dict[str, set[str]],
) -> None:
    """Every metric in Grafana dashboards must map to a Python OTel definition."""
    prom_names: set[str] = set()
    for samples in prometheus_families.values():
        prom_names |= samples

    orphaned: dict[str, set[str]] = {}
    for dashboard, metrics in _dashboard_metrics().items():
        missing = metrics - prom_names
        if missing:
            orphaned[dashboard] = missing

    if orphaned:
        lines = ["Grafana dashboards reference metrics not found in code:\n"]
        for dashboard, metrics in sorted(orphaned.items()):
            lines.append(f"  {dashboard}:")
            for m in sorted(metrics):
                lines.append(f"    - {m}")
        pytest.fail("\n".join(lines))


@pytest.mark.grafana_contract
def test_code_metrics_used_in_dashboards(
    prometheus_families: dict[str, set[str]],
) -> None:
    """Every metric defined in Python OTel code must appear in a Grafana dashboard."""
    all_dashboard_metrics: set[str] = set()
    for metrics in _dashboard_metrics().values():
        all_dashboard_metrics |= metrics

    auto_generated = {"target"}
    unused: dict[str, set[str]] = {}
    for family_name, sample_names in sorted(prometheus_families.items()):
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
