from typing import Dict, Any

# Different load test scenarios
SCENARIOS: Dict[str, Dict[str, Any]] = {
    "smoke": {"users": 1, "spawn_rate": 1, "run_time": "1m"},
    "light": {"users": 10, "spawn_rate": 2, "run_time": "5m"},
    "medium": {"users": 50, "spawn_rate": 5, "run_time": "10m"},
    "heavy": {"users": 100, "spawn_rate": 10, "run_time": "15m"},
    "stress": {"users": 200, "spawn_rate": 20, "run_time": "30m"},
}
