# Shared lifecycle facts and pre-cutover scorecard

This implements the evidence contract in [native execution §5](native-execution.md#5-cutover-evidence).
Both the checkout replay and the incumbent evidence enter through
[`LifecycleEvent`](../../src/sortyard/lifecycle/contracts.py). The
[incumbent baseline](evidence/incumbent-lifecycle-baseline.md) records the source
queries, cohort and instrumentation coverage as of November 18, 2026.

## Event contract

| Field | Version 1 meaning |
| --- | --- |
| `schema_version`, `event_id`, `kind` | Version 1, stable source-namespaced identity, and a registered event kind. Repeat delivery uses the same ID. Conflicting payloads for one observed ID are quarantined and invalidate coverage. |
| `mode`, `observed_at`, `tick` | Observed and shadow facts carry a timezone-aware timestamp, serialized in UTC. Replay facts carry a nonnegative fixture tick. Only observed facts enter delivery measures. |
| `source`, `source_revision`, `evidence` | Producer or mapping name, revision of the evidence contract or retained input, and a stable pointer to the source record. A stream's deployed revision can be recorded alongside its export when unavailable in each record. |
| `board`, `repo`, `task_id`, `task_revision`, `pr_id`, `run_id`, `stage`, `check_id` | Source-attributed identities. Use the canonical repository and stable PR identifier. For main-state events, `check_id` identifies the required-check set whose state was observed. Missing attribution remains unset. |
| `reason`, `owner`, `policy_version` | Low-cardinality reason code, accountable owner, and effective policy version when the producer can attest to them. |
| `artifact_revision`, `binding`, `projection_reason_present` | Release provenance and the observed state of a refusal reason on the task projection. Null projection state means the task was never checked. |

Producers emit committed observations with stable IDs. A handback means execution returned
responsibility to the owning queue. A dependency wait, a check alarm and an attempt failure carry
their own event kinds or remain unmapped. A release includes task revision, artifact revision and
binding for the lead-time join. A refusal is scored using the task projection state, independently
of the presence of a reason code in telemetry.

## Checkout contract proof

```sh
python -m sortyard.checkout tests/fixtures/checkout-incident.json \
  --policy owner-first --lifecycle > /tmp/checkout-owner-first.json
python -m sortyard.checkout tests/fixtures/checkout-incident.json \
  --policy wait-and-retry --lifecycle > /tmp/checkout-wait-and-retry.json
python -m sortyard.lifecycle /tmp/checkout-owner-first.json \
  --start 2026-11-17T00:00:00Z --end 2026-11-18T00:00:00Z
```

| Replay result | Owner-first | Wait-and-retry |
| --- | ---: | ---: |
| Shared lifecycle facts | 7 | 12 |
| Checkout retries | 0 | 1 at tick 7 |
| Unrelated repo verified | Tick 1 | Tick 1 |
| Affected repo independently verified | Tick 20 | Tick 20 |
| Observed delivery samples | 0 | 0 |

The policies share the conductor, recorded GitHub adapter and verifier. Unrelated-repository
facts retain the same IDs and values across both runs. The affected repository clears on the
same-tree check evidence from run `43961502003` in both runs. The CLI reports uncovered delivery
rows as JSON `null` for both replay inputs.

## Scoring a retained window

```sh
python -m sortyard.lifecycle docs/design/evidence/incumbent-lifecycle-merges.json \
  --start 2026-11-17T00:00:00Z --end 2026-11-18T00:00:00Z \
  --board HARNESS --repo noncelogic/k3s-harness --complete merged_prs_per_day \
  --reconciliation-seconds 300
```

Use explicit window endpoints with timezone offsets. The window includes its start and excludes
its end. Each `--complete` asserts that the export covers that measure for the declared
population and window. A fleet window omits board and repo selectors and requires fleet-wide
source coverage. For release and hold measures, coverage includes earlier events needed for
the join or current state. Red-main hours require a seven-day repository window, every required
check set's state at the start, and closed failure intervals. Overdue holds count tasks still
held at the close of the window whose hold exceeds the known cadence, supplied via
`--reconciliation-seconds`.

The output includes sample counts and issues for each of the six rows. Use the same window,
population and coverage rules in a comparison. Unknown source coverage, malformed input and
conflicting event IDs leave affected values null. An observed cohort with established coverage
can report zero.

The optional `--dv32` intake accepts a JSON array of minimized incumbent SigNoz span records.
It projects version 1 `mh.stage.state` markers for `running`, `done`, and `failed` into stage
start and end facts. Ingestion totals record unmapped and invalid records. These facts carry
request, stage and trace identity. Version 1 timestamps retain microseconds and use the span
ID for deduplication. Board, repository and delivery-task attribution are unknown
under the deployed convention, so the adapter can attest to execution activity only.
