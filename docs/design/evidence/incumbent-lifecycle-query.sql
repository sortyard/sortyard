-- Run against the authorized SigNoz ClickHouse reader with UTC window_start/window_end parameters.
-- Export JSONEachRow, then use jq -s . and sortyard.lifecycle --conductor-logs.
SELECT body
FROM signoz_logs.logs_v2
WHERE timestamp >= toUnixTimestamp64Nano(toDateTime64({window_start:String}, 9, 'UTC'))
  AND timestamp < toUnixTimestamp64Nano(toDateTime64({window_end:String}, 9, 'UTC'))
  AND resources_string['k8s.cluster.name'] = 'k3s-azure-01'
  AND resources_string['k8s.namespace.name'] = 'exp-phase0'
  AND resources_string['k8s.cronjob.name'] IN (
      'conductor-drive', 'conductor-plane-sync', 'conductor-maintenance')
  AND JSONExtractString(body, 'record_type') IN ('harness.lifecycle.v1', 'harness.lifecycle_error.v1')
ORDER BY timestamp, id
FORMAT JSONEachRow
