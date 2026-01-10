from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

from .config import LoadConfig
from .http_client import APIClient
from .monkey_runner import run_monkey_swarm
from .plot_report import generate_plots
from .stats import StatsCollector
from .user_runner import run_user_swarm


async def _run(cfg: LoadConfig) -> int:
    # Brief run configuration summary to stdout for easier troubleshooting
    print(
        f"Load config: base_url={cfg.base_url} api_prefix={cfg.api_prefix} "
        f"mode={cfg.mode} clients={cfg.clients} concurrency={cfg.concurrency} duration={cfg.duration_seconds}s verify_tls={cfg.verify_tls}"
    )
    # Quick preflight to catch prefix/port mistakes early
    pre_stats = StatsCollector()
    pre = APIClient(cfg, pre_stats)
    try:
        r = await pre._request("GET", cfg.api("/example-scripts"))
        print(f"Preflight /example-scripts status={r.status_code}")
    except Exception as e:  # noqa: BLE001
        print(f"Preflight error: {e}")
    finally:
        await pre.close()
    stats = StatsCollector()

    if cfg.mode in ("monkey", "both"):
        await run_monkey_swarm(cfg, stats, clients=max(1, cfg.clients // (2 if cfg.mode == "both" else 1)))

    if cfg.mode in ("user", "both"):
        await run_user_swarm(cfg, stats, clients=max(1, cfg.clients // (2 if cfg.mode == "both" else 1)))

    # Save report
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    out_dir = Path(cfg.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stats_path = out_dir / f"report_{cfg.mode}_{ts}.json"
    stats.save(stats_path)
    # Print concise summary
    summary = stats.finalize()
    print(f"Load run complete: mode={cfg.mode} requests={summary['total_requests']} errors={summary['total_errors']} runtime={summary['runtime_seconds']}s")
    print(f"Report saved to: {stats_path}")
    # Optional plots
    if getattr(cfg, "generate_plots", False):
        try:
            generated = generate_plots(str(stats_path))
            for pth in generated:
                print(f"Plot saved: {pth}")
        except Exception as e:  # noqa: BLE001
            print(f"Plot generation failed: {e}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    p = argparse.ArgumentParser(description="Load and monkey test runner")
    p.add_argument("--base-url", default=None, help="Base URL (default env LOAD_BASE_URL or https://localhost:443)")
    p.add_argument("--mode", choices=["monkey", "user", "both"], default=None, help="Run mode")
    p.add_argument("--clients", type=int, default=None, help="Total virtual clients")
    p.add_argument("--concurrency", type=int, default=None, help="Max concurrent tasks")
    p.add_argument("--duration", type=int, default=None, help="Duration in seconds (default 180)")
    p.add_argument("--output", default=None, help="Output directory for reports")
    p.add_argument("--plots", action="store_true", help="Generate PNG plots from the report")
    args = p.parse_args(argv)

    cfg = LoadConfig()
    if args.base_url:
        cfg.base_url = args.base_url
    if args.mode:
        cfg.mode = args.mode
    if args.clients is not None:
        cfg.clients = args.clients
    if args.concurrency is not None:
        cfg.concurrency = args.concurrency
    if args.output:
        cfg.output_dir = args.output
    if args.duration is not None:
        cfg.duration_seconds = args.duration

    # Pass plots flag through cfg (without changing dataclass fields)
    setattr(cfg, "generate_plots", bool(args.plots))
    return asyncio.run(_run(cfg))


if __name__ == "__main__":
    raise SystemExit(main())
