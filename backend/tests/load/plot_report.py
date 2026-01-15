from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
from pydantic import TypeAdapter
from pydantic.dataclasses import dataclass


@dataclass
class LatencyStats:
    p50: int = 0
    p90: int = 0
    p99: int = 0


@dataclass
class EndpointData:
    count: int = 0
    errors: int = 0
    latency_ms_success: LatencyStats | None = None


@dataclass
class TimelineData:
    seconds: list[int] | None = None
    rps: list[int] | None = None
    eps: list[int] | None = None


@dataclass
class ReportDict:
    timeline: TimelineData | None = None
    endpoints: dict[str, EndpointData] | None = None


_report_adapter = TypeAdapter(ReportDict)


def _load_report(path: str | Path) -> ReportDict:
    with open(path, encoding="utf-8") as f:
        return _report_adapter.validate_python(json.load(f))


def _ensure_out_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def plot_timeline(report: ReportDict, out_dir: Path) -> Path:
    tl = report.timeline or TimelineData()
    seconds = tl.seconds or []
    rps = tl.rps or []
    eps = tl.eps or []

    if not seconds:
        return out_dir / "timeline.png"

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(seconds, rps, label="RPS", color="#2563eb")
    ax.plot(seconds, eps, label="Errors/s", color="#ef4444")
    ax.set_xlabel("Second")
    ax.set_ylabel("Requests per second")
    ax.set_title("Throughput Timeline")
    ax.grid(True, alpha=0.3)
    ax.legend()
    out_path = out_dir / "timeline.png"
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def _top_endpoints(report: ReportDict, top_n: int = 10) -> list[tuple[str, EndpointData]]:
    eps = report.endpoints or {}
    items = list(eps.items())
    items.sort(key=lambda kv: kv[1].count, reverse=True)
    return items[:top_n]


def plot_endpoint_latency(report: ReportDict, out_dir: Path, top_n: int = 10) -> Path:
    data = _top_endpoints(report, top_n)
    if not data:
        return out_dir / "endpoint_latency.png"

    labels = [k for k, _ in data]
    p50 = [(v.latency_ms_success or LatencyStats()).p50 for _, v in data]
    p90 = [(v.latency_ms_success or LatencyStats()).p90 for _, v in data]
    p99 = [(v.latency_ms_success or LatencyStats()).p99 for _, v in data]

    x = range(len(labels))
    width = 0.25

    fig, ax = plt.subplots(figsize=(max(10, len(labels) * 0.6), 5))
    ax.bar([i - width for i in x], p50, width=width, label="p50", color="#22c55e")
    ax.bar(list(x), p90, width=width, label="p90", color="#eab308")
    ax.bar([i + width for i in x], p99, width=width, label="p99", color="#ef4444")
    ax.set_ylabel("Latency (ms)")
    ax.set_title("Success Latency by Endpoint (Top N)")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend()
    out_path = out_dir / "endpoint_latency.png"
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def plot_endpoint_throughput(report: ReportDict, out_dir: Path, top_n: int = 10) -> Path:
    data = _top_endpoints(report, top_n)
    if not data:
        return out_dir / "endpoint_throughput.png"

    labels = [k for k, _ in data]
    total = [v.count for _, v in data]
    errors = [v.errors for _, v in data]
    successes = [t - e for t, e in zip(total, errors, strict=True)]

    x = range(len(labels))
    width = 0.45

    fig, ax = plt.subplots(figsize=(max(10, len(labels) * 0.6), 5))
    ax.bar(list(x), successes, width=width, label="Success", color="#22c55e")
    ax.bar(list(x), errors, width=width, bottom=successes, label="Errors", color="#ef4444")
    ax.set_ylabel("Requests")
    ax.set_title("Endpoint Throughput (Top N)")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend()
    out_path = out_dir / "endpoint_throughput.png"
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def generate_plots(report_path: str | Path, output_dir: str | Path | None = None) -> list[Path]:
    report = _load_report(report_path)
    out_dir = _ensure_out_dir(output_dir or Path(report_path).parent)
    return [
        plot_timeline(report, out_dir),
        plot_endpoint_latency(report, out_dir),
        plot_endpoint_throughput(report, out_dir),
    ]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Generate plots from a load report JSON")
    p.add_argument("report", help="Path to JSON report")
    p.add_argument("--out", default=None, help="Output directory for PNGs (default: report dir)")
    args = p.parse_args(argv)

    paths = generate_plots(args.report, args.out)
    for pth in paths:
        print(f"Wrote {pth}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
