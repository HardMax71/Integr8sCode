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
# Compose starts OpenSearch refusing to create logs- indices, so none exists without the template and the policy
curl -sf -X PUT "$api/_cluster/settings" -H 'Content-Type: application/json' -d '{"persistent": {"action.auto_create_index": "true"}}' > /dev/null || exit 1
# The first wait returns when the trap runs; the second waits for OpenSearch to finish shutting down
wait $pid
wait $pid
