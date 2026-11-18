# Incumbent lifecycle rollout evidence

On November 18, 2026, [harness PR #563](https://github.com/noncelogic/k3s-harness/pull/563)
passed its Python, console and journey checks and merged as
`abd5ea0910d749b02287dfd64c1e38c5439f4bec`. It adds durable readiness episodes,
observed release and merge lineage, acknowledged returns from execution, refusal projection
evidence and required default-head samples for the HARNESS pilot. The existing
[SigNoz query](incumbent-lifecycle-query.sql) selects the versioned records for the shared scorer.

## SigNoz health and retained coverage

The November 11–18 UTC readback counted 609,011 logs from drive, plane-sync and factory-health.
There were zero typed lifecycle records and zero default-head status samples. These are source
coverage counts. The historical [37-merge baseline](incumbent-lifecycle-baseline.md) still comes
from GitHub merge times joined with HARNESS conductor state.

The central collector then stopped accepting telemetry under its 1 GiB limit. Its only endpoint
went unready and k3s logged rejected batches. [Helm revision 9 and the readback](https://github.com/noncelogic/meta-harness/blob/0300119b/devops/aks/observability/README.md#signoz-collector-recovery-on-november-18-2026)
restored intake on the existing node pool. By 12:54:21 UTC, SigNoz had received 109 fresh drive
logs, 109 fresh plane-sync logs and 15 fresh maintenance logs. These jobs ran incumbent code.
The outage interval has a collection gap.

## Release gate and scorecard status

At 13:15 UTC the live conductor templates still pointed to `ab8aeee172a23103fa48770d4cd6f61e3676daad`.
New default-branch pushes superseded multiple required push runs, including the one for the
[merged lifecycle commit](https://github.com/noncelogic/k3s-harness/actions/runs/44309036498).
The [current successor run](https://github.com/noncelogic/k3s-harness/actions/runs/44311647216)
contains the producer. A live observation qualifies once its logged bundle digest matches the
deployed producer revision.

| Missing measure | Evidence required after rollout |
| --- | --- |
| Real handbacks per day | A covered day of acknowledged returns from execution for the comparison cohort. |
| Median release-to-merge time | Matching first releases and GitHub merge observations for the same task revision. |
| Red-main hours per week | A covered seven-day HARNESS repository window with known check state and failure/recovery boundaries. |
| Readiness holds older than one cycle | Checkpointed hold episodes with complete plane-sync cadence coverage. |
| Silent refusals | Complete decision and task-projection evidence for the same scoped cohort. |

The five values remain unknown. The initial readiness and refusal cohort covers native Todo
eligibility on declared build repositories. Drive-only refusals and fleet red-main comparisons
need additional coverage. Cutover remains pending.
