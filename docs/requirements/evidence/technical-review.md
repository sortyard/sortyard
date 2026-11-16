# Independent contract-fix review

Status: PASS for the current planning-contract change, 2026-11-16. No remaining actionable blocker found in reviewed scope. Read-only review; no shared source edits. This is not runtime acceptance or deployment approval.

Reviewed the latest `/home/muse/sortyard-gitops` worktree against the four findings in `technical-review-round1.md`, source ownership, approval/delegation semantics, capability mappings and the updated repository entry points.

- R1 resolved: Task retains the six board states with separate queue lifecycle, reason/evidence/owner routes and combined-state constraints. Claimed tasks cannot remain todo; terminal/backlog tasks cannot hold claims. Editable priorities preserve urgent/high/medium/low/none.
- R2 resolved: registered `decision.answer` handles exact hash/revision-bound approval Decisions; replacement plans supersede earlier content and invalidate approval, expiry/default cannot approve, current authority is rechecked. Independent review additionally found that project-only Decisions could not represent approval for workspace actions. The auth agent fixed this before final validation: Decision supports workspace scope with optional bound project; approval inherits the exact ActionPlan scope, and project authority cannot approve a workspace action. Ordinary task Decisions retain project binding. Positive workspace/project ref checks and negative Task scope checks are present.
- R3 resolved: persisted grants retain nonempty typed action/scope arrays, explicit authority/executor/audience/expiry and closed recognized limits. Policy reason codes remain arrays. Accepted grant arguments and stored grant data have explicit matching semantics rather than inferred string fields.
- R4 resolved: 34 retained operator capabilities map to registered public actions/read operations or documented sequences. Pause/resume, job.run, needs.discharge and chain stop/resume now have owner-controlled contracts; unsupported capabilities remain unavailable, with no arbitrary-shell fallback.
- Ownership remains coherent: CortexPlane goals/processes, Walwarden knowledge, Ranker ranking, Closer commitments and existing policy families remain with their registered authorities. Projections do not become competing writable stores. Policy multi-user writes still require provider-side scoped attribution support.
- Entry points clearly distinguish existing Phase1/Postgres implementation and served `spec/` APIs from the future composed/Appwrite planning baseline. Historical draft provenance is retained. Technical review status can now be updated by the root reviewer; this review does not claim planned handlers are installed.

Independent verification on the final worktree:

```text
python docs/requirements/tools/gen.py --check
Validated 378 requirements, 60 kinds, 48 actions and 174 legacy behaviors.

python -m pytest -q tests/test_requirements_contract.py tests/test_readme.py tests/test_agents_md.py
32 passed in 0.72s
```

The first test command initially used nonexistent `test_readme_contract.py`/`test_agents_contract.py` names and collected no tests; corrected to the actual repository filenames above. No hidden successful result is inferred from that failed invocation.

Residual acceptance belongs to implementation tasks: runtime collaborator/delegation isolation, owner receipt reconciliation, transport revocation bounds, full event delivery and custody/migration cutover. Real Appwrite primitive qualification supports the substrate choice but does not satisfy those domain adapter obligations.

Final clarification: grooming fences canonicalize the source board across logical project aliases.
The root verified the final generated artifacts, lint, format, typing and affected tests before publication.
