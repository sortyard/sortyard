# 14 — Mapping from the old plan to the new milestones

Board state read on 2026-11-12 (read-only): the SORTYARD project has 80 items. Items 1–66
mirror CORPUS one to one (17–66 are M2.1–M6.7 in order — verified from the titles); 67–80 are
items the legacy system filed itself (a cost item, drift items, post-merge deployment steps,
follow-ups).

Dispositions used below:

- **Done** — nothing more.
- **Keep** — the item stands; it now belongs to the work package shown.
- **Re-scope** — the item's subject stands but its content changes as described; retitle it or replace it with the work package's tasks.
- **Split** — the content is divided across the work packages shown.
- **Cancel** — close with the reason given; nothing replaces it one for one.
- **Close** — close as answered.

Nothing on the board has been changed by this specification. §5 lists the board actions a
planner should take.

## 1. Old phase → new milestone

| Old phase (CORPUS) | Becomes | What holds, what is re-cut |
|---|---|---|
| Phase 0 — Freeze the model | Done, with close-out in **MS0** | Schemas and OpenAPI stand as version 0 and are revised in MS1 (CF-20). SORTYARD-1 closes (CF-18). |
| Phase 1A — Foundation | **MS0** + **MS1** | Repo, chart, schema, ledger hold. The API, identity and client work — done only as prototypes outside the product — lands in MS1. |
| Phase 1B — Shadow truth | Migration track: **MS0** (WP0.2, WP0.3) + **MS2** (WP2.8) | The comparison holds; the live soak is replaced by record-and-replay (CF-13); the latency question is closed (CF-12). |
| Phase 2 — Read-only glass over shadow data | **MS1**, **MS2**, **MS6** | The views hold; "read-only" and "over shadow data" do not (CF-01, CF-03). Board and task detail move to MS1 and are writable; preview, decision log and inbox to MS2 over native data; dashboards to MS6. |
| Phase 3A — Bound execution core | **MS3** + **MS4** + part of **MS5** | Launcher, mirrors, integrator, credentials, conductor, self-heal hold. Sync controller, extension registry and eval runner are cancelled (CF-05, CF-06, CF-10). |
| Phase 3B — HARNESS authority cutover | **MS7a**, with SORTYARD as the pilot | The rehearsal and hypercare hold. HARNESS is not migrated (CF-15); the Plane projection is dropped (CF-16). |
| Phase 4A — Cutover factory | **MS7** (WP7.1, WP7.5), **MS5** | The kit holds. Sensor and grooming parity is product work in MS5. Evidence import is deferred; the freeze is in MS0. |
| Phase 4B — Product cutovers | **MS7b** (WP7.4) | Holds, extended from three products to every driven project. |
| Phase 4C — Legacy retirement | **MS7c** (WP7.5) | Holds. |
| Phase 5 — Definitions conformance + extension platform | Mostly cancelled; remainder in **MS2–MS8** | Conformance survives as MIG-010. Write surfaces ship with their capabilities. The SDK shrinks to a worker conformance kit (EXT-002). Proposals and the fork lane are project governance (CF-22). |
| Phase 6A — Release candidate | **MS8**, with pieces earlier | Docs, security, upgrades and the gauntlet hold. A goldfish gate runs at every milestone; supply-chain basics start in MS1. |
| Phase 6B — Launch | **MS8** gate + owner decisions | Licence and governance: OD-1. The repository can go public earlier: OD-2. |

## 2. Item by item

| Item | State | Corpus | Title (short) | Disposition | New home | Notes |
|---|---|---|---|---|---|---|
| SORTYARD-1 | Todo | — | Verify conductor fix-round semantics | **Close** | MS0 · WP0.1 | Answered from `drive.py` on `origin/pilot-dispatcher`: backstop 10, park on the same failure, conflict rounds 5, tripwire 5 (CF-18; FLW-010 to FLW-012). Record in DECISIONS. |
| SORTYARD-2 | Done | — | Freeze JSON Schemas | Done | — | Treated as schema v0; re-cut in WP1.1 (CF-20). |
| SORTYARD-3 | Done | — | OpenAPI spec + permission matrix | Done | — | Treated as v0; revised in WP1.2 and WP1.3 (API-017, IAM-008). |
| SORTYARD-4 | Done | — | Create and seed the repository | Done | — | |
| SORTYARD-5 | Done | M1.1+M1.6 | Repo + chart skeleton | Done | — | Residue: WP0.1 (replica, guides), WP1.6 (chart). |
| SORTYARD-6 | Done | M1.3+M1.4 | Postgres schema + event ledger | Done | — | Additions in WP1.1: revisions, `schema_version`, one sequence (OBS-001). |
| SORTYARD-7 | Todo | M1.7 | API service | **Re-scope** | MS1 · WP1.2 (+WP1.3) | Too large as one item. Replace with the WP1.2 tasks; drop the conductor-only operations (API-017). |
| SORTYARD-8 | Done | M1.9–M1.11 | Shadow conductor | Done; **move** | MS0 · WP0.2 | Code moves under `migration/` (MIG-006). Its evaluator is superseded by SCH-001/002; its read adapters feed WP2.8. |
| SORTYARD-9 | Done | M1.12 | Claim-comparison harness | Done; **port** | MS0 · WP0.2 → MS2 · WP2.8 | Lives in meta-harness today; port under `migration/`; used by MIG-005. |
| SORTYARD-10 | Done | M1.13 | One-loop latency answer | Done; **retire** | MS0 · WP0.2 | SY-DEC-002 closes as superseded (CF-12). |
| SORTYARD-11 | Done | M1.15 | Legacy evidence preservation | Done; **port** | MS0 · WP0.2, WP0.3 | The tool is merged; the snapshot does not exist yet — see SORTYARD-70/71. |
| SORTYARD-12 | Done | M1.2 | Definitions loader + seed | Done; **port and re-cut** | MS2 · WP2.6, MS3 · WP3.8 | Port the loader's versioning; re-cut the seed to the kinds in DEF-001 (drop archetypes, roles, context recipes; workflows become `change` and `job`). |
| SORTYARD-13 | Todo | M1.1 | Contributor foundation | **Keep** | MS0 · WP0.1 | DEP-018, QLT-003. First build item of MS0. |
| SORTYARD-14 | Done | M1.5 | Permission matrix surface | Done; **port** | MS1 · WP1.3 | Port `identity/`; restate create+claim as IAM-008. |
| SORTYARD-15 | Done | M1.8 | MCP server + CLI parity | Done; **port** | MS1 · WP1.4 | The generator becomes the plumbing layer (CLI-003, MCP-003); the curated layer is new (CF-08). |
| SORTYARD-16 | Done | M1.14 | Goldfish install + smoke | Done; **re-run owed** | MS1 · WP1.7 | Verdict was "blocked". The re-run is the MS1 gate (QLT-004). |
| SORTYARD-17 | Backlog | M2.1 | Console shell, design system, session auth | **Re-scope** | MS1 · WP1.5, WP1.3 | Pulled forward. Auth is IAM-001/002, not OIDC only (CF-09). |
| SORTYARD-18 | Backlog | M2.2 | Read-model projections | **Split** | MS1 · WP1.1; MS2 · WP2.5; MS6 · WP6.1 | Timeline (OBS-002); queue read models (OBS-003); metrics (OBS-004). No shadow snapshots. |
| SORTYARD-19 | Backlog | M2.3 | Board and milestone view (read-only) | **Re-scope** | MS1 · WP1.5 | Writable, with reordering (UI-003, TRK-007). |
| SORTYARD-20 | Backlog | M2.4 | Task detail is its chain + trace viewer | **Split** | MS1 · WP1.5; MS3 · WP3.9; MS6 · WP6.3 | UI-004, UI-010, UI-011. |
| SORTYARD-21 | Backlog | M2.5 | Pickup Preview over shadow decisions | **Re-scope** | MS2 · WP2.5, WP2.7 | Over native data (SCH-008, UI-006). |
| SORTYARD-22 | Backlog | M2.6 | DecisionLog and audit explorer | **Keep** | MS2 · WP2.7; MS6 · WP6.3 | UI-016. |
| SORTYARD-23 | Backlog | M2.7 | Eval grid and throughput dashboards | **Split / Cancel** | MS6 · WP6.1, WP6.2 | Dashboards keep; the eval grid is cancelled (CF-23). |
| SORTYARD-24 | Backlog | M2.8 | Decision inbox and shadow what-if | **Re-scope** | MS2 · WP2.7, WP2.6 | Inbox: UI-007. What-if: DEF-007. "Shadow steering" is cancelled. |
| SORTYARD-25 | Backlog | M2.9 | Console quality walk | **Cancel** | — | Replaced by the gate at every milestone (QLT-004) and the required a11y and keyboard specs (UI-019). |
| SORTYARD-26 | Backlog | M3.1 | Definitions sync controller | **Cancel** | — | Replaced by apply/export (DEF-002) and source lock (DEF-003) (CF-06). |
| SORTYARD-27 | Backlog | M3.2 | Extension registry core | **Cancel** | — | CF-05. See EXT-001, EXT-005. |
| SORTYARD-28 | Backlog | M3.3 | Context Assembler and packet store | **Re-scope** | MS3 · WP3.5 | Packet templates (EXE-015). |
| SORTYARD-29 | Backlog | M3.4 | Execution Binding resolver | **Re-scope** | MS3 · WP3.2 | EXE-001: the checks that exist, without skills or recipes. |
| SORTYARD-30 | Backlog | M3.5 | Mirror service and dependency materialisation | **Split** | MS3 · WP3.3; MS4 · WP4.8 | EXE-008 to EXE-010; EXE-011. |
| SORTYARD-31 | Backlog | M3.6 | Worker launcher and Chain Advancer | **Split** | MS3 · WP3.1, WP3.2, WP3.7 | Chain self-repair is not carried (FLW-017). |
| SORTYARD-32 | Backlog | M3.7 | Credential custody, auth broker, pool | **Keep** | MS4 · WP4.3, WP4.1 | CRD-001 to CRD-007. |
| SORTYARD-33 | Backlog | M3.8 | Real conductor | **Split** | MS2 · WP2.4; MS3 · WP3.6, WP3.7 | Evaluation first, then claims and epochs. |
| SORTYARD-34 | Backlog | M3.9 | Integrator | **Split** | MS3 · WP3.4; MS4 · WP4.1 | Plain-git first (MRG-011), then GitHub. |
| SORTYARD-35 | Backlog | M3.10 | Eval Runner as its own deployment | **Cancel** | — | CF-10, CF-23. Reviews are FLW-005 to FLW-009. |
| SORTYARD-36 | Backlog | M3.11 | Self-heal and escalation operations | **Keep** | MS5 · WP5.2 | REC-007 to REC-010. |
| SORTYARD-37 | Backlog | M3.12 | HARNESS import and Plane projection | **Re-scope** | MS2 · WP2.8 | Importer for every board (MIG-003). The projection is cancelled (OD-4). HARNESS is not migrated (OD-7). |
| SORTYARD-38 | Backlog | M3.13 | Pilot rehearsal in the replica | **Re-scope** | MS7 · WP7.1 | Rehearse the kit with SORTYARD as the subject. |
| SORTYARD-39 | Backlog | M3.14 | HARNESS cutover and hypercare | **Re-scope** | MS7 · WP7.2 | The pilot is SORTYARD. |
| SORTYARD-40 | Backlog | M4.1 | Repeatable cutover kit | **Keep** | MS7 · WP7.1 | MIG-007 to MIG-009. |
| SORTYARD-41 | Backlog | M4.2 | Evidence and baseline import | **Cancel (defer)** | LATER | MIG-014. The freeze is MIG-001 in MS0. |
| SORTYARD-42 | Backlog | M4.3 | Sensor and grooming parity | **Split** | MS5 · WP5.6, WP5.7, WP5.8; MS7 · WP7.3 | Grooming GRM-001 to 006; mechanisms REC-017/018; estate observers MIG-012. |
| SORTYARD-43 | Backlog | M4.4 | Experiment-rig disposition | **Keep** | MS7 · WP7.5 | MIG-013; a decision. |
| SORTYARD-44 | Backlog | M4.5 | Rove cutover | **Keep** | MS7 · WP7.4 | Order per OD-7. |
| SORTYARD-45 | Backlog | M4.6 | Loopmentum cutover | **Keep** | MS7 · WP7.4 | |
| SORTYARD-46 | Backlog | M4.7 | Cortexplane cutover | **Keep** | MS7 · WP7.4 | Needs WP7.3 (DLV-003). |
| — | — | — | Cutovers for WALWARDEN, CRANK, CLOSER, NONCE | **New** | MS7 · WP7.4 | Driven projects the corpus omitted (CF-15). |
| SORTYARD-47 | Backlog | M4.8 | Dispatcher absorption | **Re-scope** | MS7 · WP7.5 | Absorption is the product build (MS3, MS4); what remains is switching it off (MIG-011). |
| SORTYARD-48 | Backlog | M4.9 | drive.py and plane_sync retirement | **Keep** | MS7 · WP7.5 | MIG-011. |
| SORTYARD-49 | Backlog | M4.10 | One-source-of-truth audit | **Keep** | MS7 · WP7.5 | MIG-011. |
| SORTYARD-50 | Backlog | M5.1 | Definitions inventory and conformance ledger | **Re-scope** | MS7 · WP7.2 | MIG-010, seeded by [16-legacy-parity.md](16-legacy-parity.md). |
| SORTYARD-51 | Backlog | M5.2 | Archetype pack migration | **Cancel** | — | CF-05. |
| SORTYARD-52 | Backlog | M5.3 | Workflow and role pack migration | **Cancel** | — | The shipped workflows are in the default bundle (DEF-008). |
| SORTYARD-53 | Backlog | M5.4 | Skills migration into the registry | **Cancel** | — | The two live checklists become definitions (FLW-007, FLW-008). |
| SORTYARD-54 | Backlog | M5.5 | Policy conformance migration | **Split** | MS2+ (DEF-005); MS5 · WP5.10; MS7 · WP7.2 | Constants as policy keys; premise rules as a pack (RDY-009); the ledger (MIG-010). |
| SORTYARD-55 | Backlog | M5.6 | Operator write surfaces | **Cancel** | — | Each screen ships with its capability (CF-03): UI-008 (MS2), UI-012 (MS4), UI-017 (MS1→MS6). |
| SORTYARD-56 | Backlog | M5.7 | Extension SDK, scaffold, conformance kit | **Re-scope** | MS8 · WP8.4 | Only the worker conformance kit (EXT-002) and pinned bundles (EXT-005). |
| SORTYARD-57 | Backlog | M5.8 | Proposals | **Cancel** | — | Project governance (CF-22; QLT-042). |
| SORTYARD-58 | Backlog | M5.9 | Definitions-repo cutover | **Re-scope** | MS6 · WP6.4; MS7 · WP7.2 | The estate's definitions bundle plus source lock (DEF-003), applied at the pilot. |
| SORTYARD-59 | Backlog | M5.10 | Fork-PR verification lane | **Cancel** | — | Provider-hosted CI for forks (QLT-013). |
| SORTYARD-60 | Backlog | M6.1 | Public docs, quickstart, examples | **Keep** | MS8 · WP8.1 | QLT-001. The quickstart exists from MS1 and MS3. |
| SORTYARD-61 | Backlog | M6.2 | Security and supply-chain pass | **Split** | MS1 · WP1.1, WP1.6; MS8 · WP8.2 | QLT-022, QLT-024 early; QLT-020, 021, 023 at 1.0. |
| SORTYARD-62 | Backlog | M6.3 | Upgrade and compatibility suite | **Split** | MS1 · WP1.6; MS8 · WP8.3 | DEP-007 from MS1; DEP-008, API-013, EXT-007 at 1.0. |
| SORTYARD-63 | Backlog | M6.4 | Release-candidate gauntlet | **Keep** | MS8 gate | And a goldfish gate at every milestone (QLT-004). |
| SORTYARD-64 | Backlog | M6.5 | First external contribution rehearsal | **Cancel** | — | Covered by QLT-013's acceptance (a fork pull request runs the full checks). |
| SORTYARD-65 | Backlog | M6.6 | Licence, trademark, governance gate | **Split** | MS3 · WP3.10; MS8 · WP8.5 | Trademark search before any public preview (QLT-043); the rest QLT-040 to 042; OD-1. |
| SORTYARD-66 | Backlog | M6.7 | Public launch | **Keep** | MS8 gate | See OD-2 for going public earlier as a preview. |
| SORTYARD-67 | Done | — | Delivery cost: Sortyard | Done | — | Legacy health item; replaced by OBS-006. |
| SORTYARD-68 | Todo | — | Drift surface: plan is unreadable | **Close** | — | The project has no plan file by design (`tasks: off`). A false alarm of the legacy drift check; report it on the HARNESS board if not already. |
| SORTYARD-69 | Todo | — | Drift surface: STATUS.md is unreadable | **Close** | — | Same. |
| SORTYARD-70 | Todo | — | Capture and verify the evidence snapshot | **Keep — do first** | MS0 · WP0.3 | MIG-001. Time-critical. |
| SORTYARD-71 | Todo | — | Publish the snapshot and record its hashes | **Keep** | MS0 · WP0.3 | MIG-001. |
| SORTYARD-72 | Todo | — | Run the 1–2 week comparison soak | **Re-scope** | MS0 · WP0.3 → MS2 · WP2.8 | Becomes: record inputs (MIG-002), then replay (MIG-005). Close when MS2's exit criterion 6 is met. |
| SORTYARD-73 | Todo | — | Collect shadow timings and write the latency report | **Cancel** | — | CF-12. |
| SORTYARD-74 | Backlog | — | Follow-ups from PR #1 | **Keep** | MS0 · WP0.1 / MS1 · WP1.6 | Triage each line into those work packages. |
| SORTYARD-75 | Todo | — | Publish the image and install the chart | **Re-scope** | MS1 · WP1.6 | Publication is the release workflow (QLT-024, DEP-020); the estate install follows for MS2's mirror. |
| SORTYARD-76 | Backlog | — | Follow-ups from PR #2 (goldfish) | **Keep** | MS0 · WP0.1 | The findings map: GF1-01 → DEF-008; GF1-02 → API-001; GF1-03 → QLT-003; GF1-04 → QLT-002; GF1-05 → DEP-018; GF1-06 → API-003; GF1-07 → API-014; GF1-08 → DEP-012; GF1-09 → MIG-015. |
| SORTYARD-77 | Todo | — | Run the install on a clean cluster and finish the smoke | **Re-scope** | MS1 · WP1.7 | This is the MS1 gate. |
| SORTYARD-78 | Backlog | — | Design follow-ups from PR #3 | **Keep** | MS1 · WP1.1 | With the schema additions. |
| SORTYARD-79 | Todo | — | Provision read-only credentials; retain production inputs per pass | **Keep** | MS0 · WP0.3 | MIG-002. |
| SORTYARD-80 | Todo | — | Deploy the shadow and confirm DecisionLog ingestion | **Re-scope** | MS0 · WP0.3 | Deploy as the recorder only; its decisions are not the evidence (CF-13). |

## 3. Carry-over: Phase 1 deliverables that are not in the product repository

| Deliverable | Where it is | Lines | Disposition | Target |
|---|---|---|---|---|
| Identity and permission matrix (`identity/`) | meta-harness `projects/sortyard/` | ~1,000 | Port, revise for IAM-008 | `src/sortyard/` · WP1.3 |
| Generated API client, MCP server, CLI (`clients/`) | meta-harness | ~1,250 | Port as the plumbing layer | `src/sortyard/` · WP1.4 |
| Definitions loader and seed (`definitions/`) | meta-harness | ~930 + 37 seed files | Port versioning; re-cut the seed | WP2.6, WP3.8 |
| Claim comparator (`claim-comparison/`) | meta-harness | ~750 | Port | `migration/` · WP0.2 |
| Legacy evidence tool (`legacy-evidence/`) | meta-harness | ~550 | Port | `migration/` · WP0.2 |
| One-loop latency instrument (`one-loop-latency/`) | meta-harness | ~540 | Retire | — (CF-12) |
| `spec/PERMISSIONS.md` | meta-harness | — | Port; then generate it | `spec/` · WP0.2 |
| Shadow conductor (`src/sortyard/shadow/`, chart template) | product repo | ~1,100 | Move out of the core | `migration/` · WP0.2 |
| Brand kit (`branding/`) | meta-harness | — | Port the assets the console uses | WP1.5 |
| `DECISIONS.md` (SY-DEC-002, 003) | meta-harness | — | Bring the product repository's copy up to date | WP0.1 |
| Evidence snapshot | does not exist | — | Capture | WP0.3 |

## 4. CORPUS risks R1–R7

| Risk | Status here |
|---|---|
| R1 — fix-round semantics unverified | Resolved (CF-18). |
| R2 — description-level dependencies are not dependencies | Planner rule 5 (file by tranche) until the pilot; after it, relations are enforced by Sortyard itself (TRK-006). |
| R3 — one lane is the programme's clock | The board now has 2 lanes; sizes and the elapsed-time estimate are in [13-milestones.md](13-milestones.md); OD-11. |
| R4 — decision-gated work must not look like lane work | [15-open-decisions.md](15-open-decisions.md); planner rule 8. |
| R5 — the shadow baseline moves | Each recorded pass carries the legacy revision (MIG-002). |
| R6 — pipeline purity binds the corpus itself | Every behaviour is tested on fakes (QLT-010, CIH-013, EXT-003); live proof only in MS7 operations. |
| R7 — connective tissue is scheduled work | The three threads at the end of [13-milestones.md](13-milestones.md). |

## 5. Board actions for the planner

1. **Now:** move SORTYARD-70, 71, 79 and 13 to the head of Todo. Close SORTYARD-1 with a link to CF-18. Close 68 and 69. Cancel 73.
2. **File MS0:** the milestone parent, its three work-package parents (WP0.1–WP0.3) and their requirement tasks (rules 1 and 2 in [13-milestones.md](13-milestones.md)); link 13, 70, 71, 72, 74, 76, 79, 80 under them.
3. **Replace SORTYARD-7** with the MS1 milestone parent, its work-package parents WP1.1–WP1.7 and their tasks; move 17, 19 and 20's MS1 parts under WP1.5; file in Todo when MS0's gate passes.
4. **Cancel** 25, 26, 27, 35, 51, 52, 53, 55, 57, 59, 64, each with its reason from §2.
5. **Retitle or replace** the remaining Backlog items when their milestone becomes next (rule 5 in [13-milestones.md](13-milestones.md)). Until then they stay in Backlog untouched.
6. **File the decisions** OD-1 to OD-11 as `decision` items with their defaults and dates.
7. **Consider turning task release on for the SORTYARD board** (`tasks: on` in `repos.yaml`) before MS1 is filed. Today its work enters only as items labelled by hand, so nothing applies the blocked-by relations that rule 1 relies on (rule 5). With about a hundred tasks in a milestone, releasing each by hand is the weak point; with release on, the legacy system applies the ready rules, preflight and relations itself. Not verified: whether anything else depends on the board being `tasks: off`.
