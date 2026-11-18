# Incumbent lifecycle baseline

The measured window is **2026-11-17 00:00 UTC through 2026-11-18 00:00 UTC**, with
an inclusive start and exclusive end. The cohort is HARNESS work that merged
into the default branch of `noncelogic/k3s-harness` (`pilot-dispatcher`). The
readback on November 18 found **37 distinct merged PRs**. All 37 join to one
HARNESS item each by repository and PR number in the live conductor state.
[Normalized merge facts](incumbent-lifecycle-merges.json).

| Scorecard measure | Observed value | Evidence and coverage |
| --- | ---: | --- |
| Merged PRs per day | 37 | HARNESS, `noncelogic/k3s-harness` default branch, GitHub `mergedAt`. Fleet coverage is unknown. |
| Real handbacks per day | Unknown | No complete stream of committed transfers back to the owning queue. The drive can log a handoff before it publishes the transfer. |
| Median release-to-merge time | Unknown | The release path retains a boolean in its queue cache. The available facts lack first eligible release timestamps joined to the same task revision. |
| Red-main hours per product per week | Unknown | This extract lacks weekly default-branch required-check failure and recovery boundaries. |
| Items not ready longer than one cycle | Unknown | The readiness sync is scheduled every five minutes. The extract lacks stable hold opening, continuation and clearing facts. |
| Silent refusals | Unknown | The extract lacks a complete set of refusal decisions and confirmation that each reason reached the task projection. |

This is a pre-cutover measurement. The comparison must use the same board,
repository, branch, day length, and merge inclusion rule. The checkout
fixture provides reproducible contract evidence, with its own replay clock.

## Live OpenTelemetry coverage

SigNoz in `aks-obs-01` retained the incumbent control-plane request and stage
traces in `signoz_traces.signoz_index_v3`. The production resource is
`meta-harness/control-plane` in `k3s-azure-01/exp-phase0`. All eight span kinds
had scope `meta-harness.control-plane` version `1`. At readback, both the
control-plane Deployment and `conductor-drive` CronJob templates reported
source revision `30240d672c7f370c3ab8425ac9d802c4ef00f5e7`. DV-32 spans omit a
source commit, so the template readback identifies the deployment at
measurement time. It does not assign that revision to historical spans.
[DV-32 trace design](https://github.com/noncelogic/k3s-harness/blob/30240d672c7f370c3ab8425ac9d802c4ef00f5e7/control-plane/OTLP-TRACE-DESIGN.md).

| Span name | Rows | Distinct trace and span IDs |
| --- | ---: | ---: |
| `mh.request.created` | 1,329 | 1,329 |
| `mh.request.duration` | 1,280 | 1,280 |
| `mh.request.state` | 2,520 | 2,519 |
| `mh.request.state.interval` | 2,505 | 2,504 |
| `mh.stage.created` | 1,329 | 1,329 |
| `mh.stage.duration` | 1,280 | 1,280 |
| `mh.stage.state` | 5,038 | 5,037 |
| `mh.stage.state.interval` | 5,023 | 5,022 |
| **Total** | **20,304** | **20,300** |

Of the 5,037 distinct stage state markers, 1,293 entered `running`, 1,188
`done`, 108 `failed`, 1,221 `collecting`, and 1,227 `scheduled`. All
had request ID, stage name, and stage sequence. The scorecard intake mapped
2,589 rows and skipped 2,449, including one repeated `scheduled` marker.
It reported zero invalid records. DV-32 excludes board, repository, and
task revision from these traces, and no nested span events were present
in the window. These trace counts measure the availability of request
and stage telemetry. The delivery rows require separate facts.

SigNoz also retained 148,178 stdout/stderr records from the drive
(57,760), plane-sync (47,067), mechanism health (21,409), maintenance
(18,390), and factory health (3,552) CronJobs over the same window.
Each has an empty OTel scope and the attributes `log.file.path`,
`log.iostream` and `logtag`. Drive logs use a UTC time followed by redacted
text. A log entry can describe a proposed or pending action. HARNESS-1663
tracks the typed delivery lifecycle needed for the rest of the scorecard.
[Drive source](https://github.com/noncelogic/k3s-harness/blob/30240d672c7f370c3ab8425ac9d802c4ef00f5e7/control-plane/conductor/drive.py#L253).
[Readiness release source](https://github.com/noncelogic/k3s-harness/blob/30240d672c7f370c3ab8425ac9d802c4ef00f5e7/control-plane/conductor/plane_sync.py#L2834).

## Reproduction

With existing SigNoz access, run this against the trace store. The same
query with `name = 'mh.stage.state'` in the filter and
`attributes_string['mh.state.current']` in the grouping gives the stage
entry breakdown. The `mh.stage.sequence` field is in
`attributes_number`, and `mh.request.id`, `mh.stage.name`,
`mh.state.previous`, and `mh.state.current` are in `attributes_string`.

```sql
SELECT scope.name, scope.version, name,
       count() AS span_rows,
       uniqExact((trace_id, span_id)) AS distinct_spans,
       countIf(notEmpty(events)) AS spans_with_events
FROM signoz_traces.signoz_index_v3
WHERE timestamp >= toDateTime64('2026-11-17 00:00:00', 9, 'UTC')
  AND timestamp < toDateTime64('2026-11-18 00:00:00', 9, 'UTC')
  AND serviceName = 'control-plane'
  AND resources_string['service.namespace'] = 'meta-harness'
  AND resources_string['k8s.cluster.name'] = 'k3s-azure-01'
  AND resources_string['k8s.namespace.name'] = 'exp-phase0'
  AND resources_string['deployment.environment.name'] = 'production'
  AND scope.name = 'meta-harness.control-plane' AND scope.version = '1'
GROUP BY scope.name, scope.version, name
ORDER BY name
```

Use the same trace-store access to export the minimum fields required by
the adapter. The export retains opaque trace and request IDs and should
stay in the operator workspace.

```sql
SELECT scope.name AS scope_name, scope.version AS scope_version, name AS span_name,
       toString(trace_id) AS trace_id, span_id,
       concat(
           formatDateTime(timestamp, '%Y-%m-%dT%H:%i:%s', 'UTC'), '.',
           leftPad(toString(toUnixTimestamp64Nano(timestamp) % 1000000000), 9, '0'), 'Z'
       ) AS observed_at,
       attributes_string['mh.request.id'] AS request_id,
       attributes_string['mh.stage.name'] AS stage_name,
       toUInt64(attributes_number['mh.stage.sequence']) AS stage_sequence,
       attributes_string['mh.state.current'] AS current_state
FROM signoz_traces.signoz_index_v3
WHERE timestamp >= toDateTime64('2026-11-17 00:00:00', 9, 'UTC')
  AND timestamp < toDateTime64('2026-11-18 00:00:00', 9, 'UTC')
  AND serviceName = 'control-plane'
  AND resources_string['service.namespace'] = 'meta-harness'
  AND resources_string['k8s.cluster.name'] = 'k3s-azure-01'
  AND resources_string['k8s.namespace.name'] = 'exp-phase0'
  AND resources_string['deployment.environment.name'] = 'production'
  AND scope.name = 'meta-harness.control-plane' AND scope.version = '1'
  AND name = 'mh.stage.state'
ORDER BY timestamp, trace_id, span_id
FORMAT JSONEachRow
```

```sh
jq -s . dv32-stage-state.ndjson > dv32-stage-state.json
python -m sortyard.lifecycle dv32-stage-state.json --dv32 \
  --start 2026-11-17T00:00:00Z --end 2026-11-18T00:00:00Z
```

For stdout/stderr coverage, use the same start and end with
`toUnixTimestamp64Nano(toDateTime64(..., 9, 'UTC'))` against
`signoz_logs.logs_v2.timestamp`. Filter those cluster and namespace
resource attributes and the five `k8s.cronjob.name` values listed above.
Group by CronJob and `scope_name`, and inspect attribute keys only.

GitHub is the source for merge time and identity. Verify the default
branch and use the search result's actual `mergedAt` timestamp to enforce
the window.

```sh
gh api repos/noncelogic/k3s-harness --jq '.default_branch'
gh pr list -R noncelogic/k3s-harness --state merged \
  --search 'base:pilot-dispatcher merged:2026-11-17' --limit 200 \
  --json number,mergedAt,baseRefName,url
```

From a running incumbent drive or maintenance pod in `exp-phase0`, read
`/data/conductor/state.json`. Restrict to the returned PRs and the exact
repository. Project the `pr`, `ident` and `seq` fields and check there is
exactly one match per GitHub PR. The normalized fact uses the item's
board and display identity (`ident-seq`), the GitHub timestamp and URL,
and the stable event ID `github:<repo>:pr:<number>:merged`. The source
revision `github-pr-merged-at-v1` identifies this extraction mapping.
The readback retained the matched fields only. Historical attribution in
the fact file is a snapshot, since the live conductor can prune or update
its state.

```sh
python -m sortyard.lifecycle docs/design/evidence/incumbent-lifecycle-merges.json \
  --start 2026-11-17T00:00:00Z --end 2026-11-18T00:00:00Z \
  --board HARNESS --repo noncelogic/k3s-harness --complete merged_prs_per_day \
  --reconciliation-seconds 300
```
