# 17 — Evidence and method

What this specification was built from, at which revisions, how much of each source was read,
and what was not verified. Where a requirement rests on reasoning rather than a source, its
Source line says "inference".

## Revisions

| Source | Revision | Date read |
|---|---|---|
| `sortyard/sortyard`, branch `spec-requirements` (= `main`) | `721a16b` | 2026-11-12 |
| `noncelogic/k3s-harness`, `origin/pilot-dispatcher` | `5536fe3` | 2026-11-12 |
| `noncelogic/meta-harness`, `main` | `0fda5da0` | 2026-11-12 |
| `makeplane/plane` | `0b9ca51` | 2026-11-12 |
| SORTYARD Plane project (80 items) | read-only listing | 2026-11-12 |

The local k3s-harness checkout was 59 commits behind `origin/pilot-dispatcher`; the branch was
read from a read-only export of the remote ref, not from the working tree.

## Abbreviations used in Source lines

| Abbreviation | File |
|---|---|
| DRV, "driver" | meta-harness `operations/k8s-harness-driver.md` (the delivery driver handoff and its dated release notes) |
| K3D, "k3s driver" | k3s-harness `operations/k8s-harness-driver.md` (running-system delivery, discharging needs) |
| TP, "task-pickup" | meta-harness `operations/task-pickup.md` |
| TR, "task-ready" | meta-harness `operations/task-ready.md` |
| CR, "conductor README" | k3s-harness `control-plane/conductor/README.md` |
| SH | k3s-harness `control-plane/conductor/SELF-HEAL.md` |
| MECH | k3s-harness `control-plane/MECHANISMS.md` and `mechanisms.yaml` |
| TRV, DRVW, JQ | k3s-harness `control-plane/TEST-REVIEW.md`, `DESIGN-REVIEW.md`, `JOB-QUARANTINE.md` |
| RC | k3s-harness `control-plane/k8s/CI-RELEASE.md` |
| FD | k3s-harness `control-plane/FACTORY-DASHBOARD-DESIGN.md` |
| MH, "`mh.py` (notes)" | k3s-harness `control-plane/mh.py`, from working notes (see below) |
| "drive note N" | The numbered code comments of `drive.py`, which the repository keeps in `control-plane/DESIGN.md` under "mh.py comment notes" |
| HC, "harness-console" | meta-harness `projects/harness-console/` (VISION, journeys, decided, architecture) and k3s-harness `control-plane/console/` |
| "measurement contract" | meta-harness `operations/factory-measurement-contract.md` |
| AGENTS.md | meta-harness `AGENTS.md` |
| DESIGN, CORPUS, MILESTONES, DECISIONS, INTENDED-USE | The files of those names in this repository; the newer DECISIONS in meta-harness `projects/sortyard/` |
| spec NOTES, PERMISSIONS | meta-harness `projects/sortyard/spec/NOTES.md`, `PERMISSIONS.md` |
| goldfish GF1-nn | `docs/goldfish/phase-1-install-smoke.md` |
| HARNESS-n, CPV2-n, ROVE-n, LOOP-n | Plane item ids cited by those documents; not re-read on the board |

## How much of each source was read

| Source | Coverage |
|---|---|
| This repository: README, DESIGN, CORPUS, MILESTONES, DECISIONS, INTENDED-USE, goldfish report, CI workflow, chart values and migration runner | Read in full |
| This repository: `spec/` schemas and OpenAPI | Summarised by script (object fields, operation counts); NOTES and the first part of PERMISSIONS read |
| This repository: `src/` and `tests/` | Structure and sizes; `api.py` head, migration head |
| meta-harness `projects/sortyard/` prototypes | READMEs and sizes; code not reviewed |
| Driver log, task-ready, task-pickup, in-flight-steering, onboarding | Read in full |
| Conductor README (78 KB), SELF-HEAL, MECHANISMS | Read in full |
| TEST-REVIEW, DESIGN-REVIEW, JOB-QUARANTINE, CI-RELEASE, FACTORY-DASHBOARD-DESIGN, measurement contract | Read in the parts quoted; not in full |
| `drive.py` (2,589 lines) | Module head, constants and packet templates read; behaviour taken from the conductor README and from the numbered code notes extracted for every function |
| `mh.py` (8,050 lines) | Lines 1–5,052 through working notes with line references (work model, request validation, result builder, worker template, Job render, proof worker, ledger protocol, schema, store, credential pool); `caps_allow` and `_drive_order` read directly; lines 5,052 onward mapped by function name only |
| `plane_sync.py`, `plane_tasks.py`, `grooming.py`, `preflight.py`, `causes.py`, `self_heal.py`, `release_verify.py`, `delivery.py`, `drift.py`, `test_review.py`, `design_review.py` | Not read as code; behaviour taken from the conductor README, which documents each. For the audit of 2026-11-12 two points were checked in the code: `grooming.py` excludes the method directories (roles, skills, contracts) from inputs, and `design_review.py` reads its checklist from a skill file |
| `api.py`, `auth.py`, `ship.py`, `cred_sync.py`, `mechanism_health.py` and the continuity monitors | Not read as code; `ship.py`'s fence is taken from DESIGN §3.7a |
| Kubernetes manifests | Object inventory by script; `deployment.yaml` strategy and resources |
| Legacy console | Route list, component list, API endpoints used, end-to-end spec names (26 files, journeys 1 to 13), bundle budget; for the audit, that the concierge is implemented (`concierge.py`, `components/concierge/`, its end-to-end specs) |
| `metrics/analyze.py` | The first 60 lines (the definitions used) |
| meta-harness `AGENTS.md` | "Delivery lanes", "The rule", "Testing model", "Green main" read; the rest by heading |
| meta-harness `repos.yaml` | The driver entries: project keys, lanes, build and task-release switches; that the conductor reads it from a clone on every pass |
| meta-harness templates, skills, scripts, MANUAL | Directory listings only |
| Plane | Repository layout, workflows, Dockerfiles, self-host bundle, settings and counts by script; release and advisory data from the GitHub API |
| The live cluster, `state.json`, the dispatcher database | Not read |

## Method notes

- A first attempt to inventory the legacy code with parallel sub-agents was cut off by a usage
  limit. Two of them left working notes on disk (function-by-function notes on `mh.py` up to
  line 5,052, and an extract of every numbered code note of `drive.py`). Those notes were used
  and spot-checked against the code (`caps_allow`, the constants). The remaining scope was
  covered by reading the documents that describe the code, as listed above. No sub-agent
  conclusions were taken on trust.
- The SORTYARD board was listed once with a read-only request using the operator's cached board
  key, to obtain item numbers, titles and states. Nothing was written.
- This directory is checked by [tools/gen.py](tools/gen.py) (`--check` passes at the time of
  writing). The tool was linted and formatted with `ruff` 0.17.4 under this repository's
  settings; it has not run in the repository's CI.
- The revision of 2026-11-12 applied the owner's two directions (QLT-050, QLT-051). Every
  requirement's origin was re-read against the estate rather than against the design, and each
  cut was re-examined; the outcome is in [18-divergences.md](18-divergences.md) §5 and
  [11-coherence.md](11-coherence.md) Part C. The evidence for each legacy baseline is the
  source already cited by the requirement it belongs to.
- Constants quoted in requirements are the values in the sources at the revisions above. Some
  differ between documents written at different times (for example the heavy caps: 4/3/2 in the
  driver log, 6/5/2 in task-pickup); DEF-005 records them as deployment-specific.

## What was not verified, and should be before relying on it

1. **The legacy system as it runs today.** It changes daily. Nothing here was checked against
   the live cluster or the running bundle; "released" versus "merged" differences noted in
   task-pickup may have moved.
2. **Behaviours in code the documents do not describe.** `plane_sync.py`, `grooming.py` and the
   second half of `mh.py` were not read line by line. [16-legacy-parity.md](16-legacy-parity.md)
   is a seed; MIG-010 completes it.
3. **Whether design chains are still used.** The conductor does not call them; other callers
   were not traced (FLW-017 says "inference").
4. **Plane beyond its repository.** Its hosted documentation, its commercial edition and any CLA
   bot were not examined. "Not found" in [12-quality-bar.md](12-quality-bar.md) means not found
   in the repository.
5. **Throughput and sizes.** The work-package sizes in [13-milestones.md](13-milestones.md) are
   judgement. Its elapsed-time estimate rests on one week's estate-wide item count, today's lane
   configuration and four merged pull requests in this repository; it is labelled as inference
   and is to be replaced by measurement at the MS1 gate.
6. **The prototype code.** The six Phase 1 prototypes were sized and their READMEs read; their
   fitness for porting was not reviewed.
7. **The legacy baselines.** [18-divergences.md](18-divergences.md) §2 states what the sources
   already say and marks the rest "to capture". Nothing was measured for this specification:
   no figure for merges a day, release-to-merge time, operator interventions, delivery cost,
   stage start or journey steps exists yet. Whether each can be measured from the frozen
   evidence is itself unverified; MIG-016 finds out, and a demonstration whose baseline cannot
   be measured falls back to its absolute floor.
8. **Use of the legacy features that are not carried.** Design chains, sentence-to-task
   requests, projected issue items, the experiment rig, the concierge, the improvement ledger,
   attachments and the other Plane features were judged unused or little used by inference
   from the documents. None was counted. Every such cut is conditional on the usage census
   (MIG-017).
9. **The targets.** Targets in the acceptance criteria are judgement about the best outcome
   for a product of this kind. They were not derived from a measurement of any other product,
   and no product other than Plane was examined. The floors that refer to a legacy baseline
   are only as good as that baseline.
10. **Who holds the board key.** That the sync and the driver share one key is in the sources;
    that the filing tools use the same key is inference.
