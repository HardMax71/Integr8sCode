#!/bin/bash
set -u
./opensearch-docker-entrypoint.sh opensearch &
pid=$!
trap 'kill -TERM $pid' TERM INT
api=http://localhost:9200
until curl -sf "$api/_cluster/health?wait_for_status=yellow&timeout=1s" > /dev/null; do
  kill -0 $pid 2> /dev/null || exit 1
  sleep 2
done
curl -sf -X PUT "$api/_index_template/logs" -H 'Content-Type: application/json' -d @/etc/opensearch-setup/logs-template.json > /dev/null || exit 1
# A stored policy is never overwritten, so a changed policy needs a new id
curl -sf -o /dev/null "$api/_plugins/_ism/policies/logs-30d" \
  || curl -sf -X PUT "$api/_plugins/_ism/policies/logs-30d" -H 'Content-Type: application/json' -d @/etc/opensearch-setup/logs-retention-policy.json > /dev/null \
  || exit 1
# An index the collector created before the policy existed gets it too; one that has it already is skipped
curl -s -X POST "$api/_plugins/_ism/add/logs-*" -H 'Content-Type: application/json' -d '{"policy_id": "logs-30d"}' > /dev/null
# The first wait returns when the trap runs; the second waits for OpenSearch to finish shutting down
wait $pid
wait $pid
