# tests/load/run_load_tests.py
import argparse
import subprocess

from config import SCENARIOS


def run_load_test(scenario: str, host: str) -> None:
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario}")

    config = SCENARIOS[scenario]

    cmd = [
        "locust",
        "-f",
        "locustfile.py",
        "--host",
        host,
        "--users",
        str(config["users"]),
        "--spawn-rate",
        str(config["spawn_rate"]),
        "--run-time",
        config["run_time"],
        "--headless",  # Run without web UI
        "--only-summary",  # Only show summary stats
        "--html",
        f"report_{scenario}.html",  # Generate HTML report
    ]

    subprocess.run(cmd)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run load tests")
    parser.add_argument(
        "--scenario",
        choices=SCENARIOS.keys(),
        default="smoke",
        help="Load test scenario to run",
    )
    parser.add_argument(
        "--host", default="https://localhost:443", help="Host to test against"
    )

    args = parser.parse_args()
    run_load_test(args.scenario, args.host)
