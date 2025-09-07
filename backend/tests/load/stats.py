from __future__ import annotations

import json
import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Tuple


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(math.ceil(p * len(s)) - 1)))
    return s[k]


@dataclass(slots=True)
class EndpointStats:
    count: int = 0
    errors: int = 0
    status_count: Dict[int, int] = field(default_factory=lambda: defaultdict(int))
    durations_ms: list[float] = field(default_factory=list)
    durations_ms_success: list[float] = field(default_factory=list)
    durations_ms_error: list[float] = field(default_factory=list)
    bytes_rx: int = 0

    def add(self, status: int, duration_ms: float, bytes_rx: int) -> None:
        self.count += 1
        self.status_count[status] += 1
        self.durations_ms.append(duration_ms)
        self.bytes_rx += bytes_rx
        if status >= 400:
            self.errors += 1
            self.durations_ms_error.append(duration_ms)
        else:
            self.durations_ms_success.append(duration_ms)

    def summary(self) -> dict[str, Any]:
        def _latency_dict(values: list[float]) -> dict[str, float]:
            return {
                "min": min(values) if values else 0.0,
                "p50": _pct(values, 0.50),
                "p90": _pct(values, 0.90),
                "p99": _pct(values, 0.99),
                "max": max(values) if values else 0.0,
            }
        return {
            "count": self.count,
            "errors": self.errors,
            "status": dict(self.status_count),
            # Overall latency distribution (all statuses)
            "latency_ms": _latency_dict(self.durations_ms),
            # Separate latency distributions
            "latency_ms_success": _latency_dict(self.durations_ms_success),
            "latency_ms_error": _latency_dict(self.durations_ms_error),
            "bytes_rx": self.bytes_rx,
        }


@dataclass(slots=True)
class StatsCollector:
    started_at: float = field(default_factory=time.time)
    per_endpoint: Dict[Tuple[str, str], EndpointStats] = field(default_factory=lambda: defaultdict(EndpointStats))
    exceptions: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    notes: list[str] = field(default_factory=list)

    # High-level counters
    total_requests: int = 0
    total_errors: int = 0
    # Simple time-bucketed counters for RPS plots
    _timeline_counts: Dict[int, int] = field(default_factory=lambda: defaultdict(int))
    _timeline_errors: Dict[int, int] = field(default_factory=lambda: defaultdict(int))

    def record(self, method: str, url: str, status: int, duration_ms: float, bytes_rx: int) -> None:
        key = (method, url.split("?")[0])
        self.per_endpoint[key].add(status, duration_ms, bytes_rx)
        self.total_requests += 1
        if status >= 400:
            self.total_errors += 1
        # timeline bucket
        try:
            sec = int(time.time() - self.started_at)
            self._timeline_counts[sec] += 1
            if status >= 400:
                self._timeline_errors[sec] += 1
        except Exception:
            pass

    def record_exception(self, exc: BaseException) -> None:
        name = exc.__class__.__name__
        self.exceptions[name] += 1

    def add_note(self, note: str) -> None:
        self.notes.append(note)

    def finalize(self) -> dict[str, Any]:
        runtime = time.time() - self.started_at
        endpoints = {
            f"{m} {u}": s.summary() for (m, u), s in self.per_endpoint.items()
        }
        # Build simple timeline arrays for plotting
        seconds_sorted = sorted(self._timeline_counts.keys())
        rps = [self._timeline_counts[s] for s in seconds_sorted]
        eps = [self._timeline_errors.get(s, 0) for s in seconds_sorted]
        return {
            "runtime_seconds": round(runtime, 3),
            "total_requests": self.total_requests,
            "total_errors": self.total_errors,
            "exceptions": dict(self.exceptions),
            "endpoints": endpoints,
            "timeline": {
                "seconds": seconds_sorted,
                "rps": rps,
                "eps": eps,
            },
            "notes": self.notes,
        }

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            json.dump(self.finalize(), f, indent=2)
