#!/bin/bash
# tests/load/run_all_scenarios.sh

scenarios=("smoke" "light" "medium" "heavy" "stress")
host="http://localhost:443"

for scenario in "${scenarios[@]}"
do
    echo "Running $scenario scenario..."
    python run_load_tests.py --scenario "$scenario" --host "$host"
    echo "Completed $scenario scenario"
    echo "Waiting 30 seconds before next scenario..."
    sleep 30
done