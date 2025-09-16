from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import matplotlib.pyplot as plt


def _load_report(path: str | Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _ensure_out_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def plot_timeline(report: Dict[str, Any], out_dir: Path) -> Path:
    tl = report.get("timeline", {})
    seconds: List[int] = tl.get("seconds", [])
    rps: List[int] = tl.get("rps", [])
    eps: List[int] = tl.get("eps", [])

    if not seconds:
        # Nothing to plot
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


def _top_endpoints(report: Dict[str, Any], top_n: int = 10) -> List[Tuple[str, Dict[str, Any]]]:
    eps: Dict[str, Any] = report.get("endpoints", {})
    items = list(eps.items())
    items.sort(key=lambda kv: kv[1].get("count", 0), reverse=True)
    return items[:top_n]


def plot_endpoint_latency(report: Dict[str, Any], out_dir: Path, top_n: int = 10) -> Path:
    data = _top_endpoints(report, top_n)
    if not data:
        return out_dir / "endpoint_latency.png"

    labels = [k for k, _ in data]
    p50 = [v.get("latency_ms_success", {}).get("p50", 0) for _, v in data]
    p90 = [v.get("latency_ms_success", {}).get("p90", 0) for _, v in data]
    p99 = [v.get("latency_ms_success", {}).get("p99", 0) for _, v in data]

    x = range(len(labels))
    width = 0.25

    fig, ax = plt.subplots(figsize=(max(10, len(labels) * 0.6), 5))
    ax.bar([i - width for i in x], p50, width=width, label="p50", color="#22c55e")
    ax.bar(x, p90, width=width, label="p90", color="#eab308")
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


def plot_endpoint_throughput(report: Dict[str, Any], out_dir: Path, top_n: int = 10) -> Path:
    data = _top_endpoints(report, top_n)
    if not data:
        return out_dir / "endpoint_throughput.png"

    labels = [k for k, _ in data]
    total = [v.get("count", 0) for _, v in data]
    errors = [v.get("errors", 0) for _, v in data]
    successes = [t - e for t, e in zip(total, errors)]

    x = range(len(labels))
    width = 0.45

    fig, ax = plt.subplots(figsize=(max(10, len(labels) * 0.6), 5))
    ax.bar(x, successes, width=width, label="Success", color="#22c55e")
    ax.bar(x, errors, width=width, bottom=successes, label="Errors", color="#ef4444")
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


def generate_plots(report_path: str | Path, output_dir: str | Path | None = None) -> List[Path]:
    report = _load_report(report_path)
    out_dir = _ensure_out_dir(output_dir or Path(report_path).parent)
    paths = [
        plot_timeline(report, out_dir),
        plot_endpoint_latency(report, out_dir),
        plot_endpoint_throughput(report, out_dir),
    ]
    return paths


def main(argv: List[str] | None = None) -> int:
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
