# Operating-process extension: independent technical review

2026-11-16; reviewer: appwrite_auth subagent. Scope: planning contracts and source grounding on `design/operational-processes`, not runtime qualification or live estate health.

Result: **PASS after correction**. No outstanding material findings in this planning extension.

Initial findings, corrected and independently rechecked:

1. **Actor lifecycle lacked a public path.** Resource catalog declares draft -> enabled and retirement, but only register/configure/pause/resume are registered. Configure arguments contain no lifecycle transition and resume has no initial-enable semantics. Define first enable explicitly and provide retirement through a named public action (with the same UI/agent parity and current-grant checks). This avoids an eventual administrative-only escape hatch.
2. **Pinned execution and lease were incompletely represented.** `DomainOperationalProcessRun.actor_bindings` contains only mutable actor references. After `actor.configure`, the run cannot identify its actual pinned configuration/executor from the closed contract. Record the actor configuration revision and executor snapshot per role, retaining historical configuration; do not snapshot away live revocation checks. The run also records lease owner/fence without expiry or a reference to the reused lease record, despite requiring an unexpired lease. Add the expiry or existing lease reference so takeover and inspection have an explicit binding.

Reviewed operating-process prose, seven unbound actor templates, fourteen unbound/record policy templates, five process templates, OPS-005–010, resource/data/action/OpenAPI changes and seed validator/tests against pinned source assessment. Existing policy ownership, Git/native delivery ownership, explicit delegation, separate diagnosis/repair authority, ambiguous effect reconciliation, cumulative budgets, exact positive verification and unavailable crashloop proposals are preserved. New policy parameter coverage is explicitly proposed rather than asserted as current enforcement; actual source consumer drift is disclosed. No live capability is claimed.

Validation: `gen.py --check` validated 384 requirements / 63 kinds / 56 actions / 174 legacy behaviors; operating-process plus requirements-contract tests **28 passed**. Findings were sent to the root author for correction. No shared repository edits by reviewer.

## Correction verification

The author added `actor.enable` (draft only) and `actor.retire` (draft/enabled/paused), with expected revisions, idempotency, current grants and public transport parity. Resume is explicitly paused-only. Run role bindings now carry actor reference/configuration revision, executor reference/revision and grant references; normative retained snapshots preserve historical bindings and exclude privilege inheritance from later edits. Lease expiry is required in the run record and non-null for active running/waiting/verifying states. Current revocation still constrains new effects.

Final independent checks: generator validates **384 requirements / 63 kinds / 58 actions / 174 legacy behaviors**; operating-process and requirements-contract tests **29 passed**, including rejection of mutable bare actor refs and a null running lease. Ruff on the changed validator/new tests and `git diff --check` pass. These are local design-contract checks, not an executed actor, activated policy or production recovery proof.
