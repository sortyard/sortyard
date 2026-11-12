# Sortyard requirements specification

**Status:** draft for the owner's review, 2026-11-12. It supersedes the phase plan in
`MILESTONES.md` and `CORPUS.md` as the thing to schedule from, and it proposes changes to
`DESIGN.md` (v6) that are listed in [11-coherence.md](11-coherence.md). Nothing outside this
directory has been changed.

**Purpose.** State what the consolidated product must do, in numbered, testable requirements
with stable ids, so that a planner can turn it into scheduled board items without design
judgment, and so that nothing the current estate does well is lost without a recorded reason.

**The goal it answers** (the owner, 2026-11-12): consolidate the board, the conductor, the
dispatcher, the sync, the dashboards and the rest into "a single, self-hosted, open source
project that's at least as high quality as the plane repo", with requirements that are
"concrete, milestone based, and schedulable".

## Read in this order

| If you want… | Read |
|---|---|
| What the product is, who it is for, what is absorbed, replaced or dropped | [01-product-definition.md](01-product-definition.md) |
| How it fits together, and what to change in the existing design | [11-coherence.md](11-coherence.md) |
| The plan | [13-milestones.md](13-milestones.md) |
| What happens to each existing board item | [14-mapping.md](14-mapping.md) |
| What the owner must decide | [15-open-decisions.md](15-open-decisions.md) |
| The requirements themselves | files 02–10 and 12, below |
| Where a behaviour of the old system went | [16-legacy-parity.md](16-legacy-parity.md) |
| What this rests on | [17-evidence.md](17-evidence.md) |

## Files

| File | Contents | Areas |
|---|---|---|
| [01-product-definition.md](01-product-definition.md) | Users, problems, principles, absorb/replace/drop tables, non-goals | — |
| [02-work-tracking.md](02-work-tracking.md) | The tracker; readiness, preflight, release; grooming | TRK, RDY, GRM |
| [03-scheduling.md](03-scheduling.md) | Eligibility, order, lanes, admission, Pickup Preview | SCH |
| [04-execution.md](04-execution.md) | Binding, Jobs, mirrors, harnesses; credentials | EXE, CRD |
| [05-delivery.md](05-delivery.md) | Workflows, reviews, landing, CI and main health, delivery verification | FLW, MRG, CIH, DLV |
| [06-recovery.md](06-recovery.md) | Stall recovery, self-heal, no silent failure | REC |
| [07-interfaces.md](07-interfaces.md) | REST API, MCP, CLI, identity and permissions | API, MCP, CLI, IAM |
| [08-console.md](08-console.md) | The operator console | UI |
| [09-observability.md](09-observability.md) | Ledger, metrics, dashboards, notifications | OBS |
| [10-platform.md](10-platform.md) | Definitions, extension points, install and upgrade, migration | DEF, EXT, DEP, MIG |
| [11-coherence.md](11-coherence.md) | One coherent install; findings CF-01 to CF-25 against DESIGN and CORPUS | — |
| [12-quality-bar.md](12-quality-bar.md) | The Plane benchmark as verified; quality requirements | QLT |
| [13-milestones.md](13-milestones.md) | MS0–MS8: increments, exit criteria, work packages, sizes | — |
| [14-mapping.md](14-mapping.md) | Old phase and each SORTYARD item → new milestone | — |
| [15-open-decisions.md](15-open-decisions.md) | OD-1 to OD-11 with defaults and consequences | — |
| [16-legacy-parity.md](16-legacy-parity.md) | Legacy behaviour → disposition → requirement (LP ids) | — |
| [17-evidence.md](17-evidence.md) | Sources, revisions, coverage, what was not verified | — |
| [requirements.json](requirements.json) | Machine-readable index of every requirement | — |
| [tools/gen.py](tools/gen.py) | Validates this directory and refreshes its generated parts | — |

## Conventions

**Ids are stable.** `AREA-NNN`. An id is never reused or renumbered; a withdrawn requirement
keeps its id and is marked withdrawn. Other id families: `CF-nn` (coherence findings), `OD-n`
(open decisions), `LP-nnn` (legacy parity rows), `MSn` (milestones), `WPn.m` (work packages).

**Every requirement has the same shape:**

```
### AREA-NNN — Title
**MSn** · WPn.m · PRIORITY · ORIGIN

Statement.

- AC1: an acceptance criterion that can be checked
- AC2: …

Source: where it comes from in the estate, or "inference"
```

- **Milestone / work package** — the one place it is delivered. `LATER` means after 1.0.
- **Priority** — `MUST` (the milestone cannot exit without it), `SHOULD` (belongs in the milestone and may slip to the next; no exit criterion depends on one), `LATER`. A `SHOULD` that preserves an estate behaviour (origin `KEEP` or `FIX`) is still owed to the estate: it is delivered, or waived by the owner in the conformance ledger (MIG-010), before the projects that rely on it are cut over (MS7b).
- **Origin** — `KEEP` (preserves something that works today), `FIX` (keeps the intent, closes a recorded gap), `NEW` (needed for a self-hostable product).
- **Acceptance criteria** are written to become tests. Numbers in them (latencies, limits, counts) are the bar unless a policy key is named, in which case the number is the shipped default.

**Generated parts.** [tools/gen.py](tools/gen.py) reads the heading and tag line of every
requirement and refreshes three things: `requirements.json`, the requirement lists and totals in
[13-milestones.md](13-milestones.md), and the table below. Generated text sits between
`<!--gen:…-->` and `<!--/gen-->` markers and is never edited by hand. To move a requirement,
change its tag line and run the tool; to resize a work package, change its row in
[13-milestones.md](13-milestones.md) and run the tool.

```
python3 docs/requirements/tools/gen.py           # refresh
python3 docs/requirements/tools/gen.py --check   # validate only; non-zero exit on any problem
```

The check fails on a duplicate or malformed id, a requirement with no acceptance criterion or no
source, a reference to a requirement, finding, decision or file that does not exist, a work
package with no row in the plan, a size letter that disagrees with its estimate, and generated
text that is out of date. It needs only the Python standard library and passes the repository's
`ruff` settings. Running it in CI belongs with QLT-012.

**`requirements.json`** holds, for each requirement: `id`, `title`, `area`, `file`, `milestone`,
`work_package`, `priority`, `origin`, the statement, the acceptance criteria and the source line;
for each work package: its milestone, name, dependencies, size, estimated tasks and requirement
ids; for each milestone: its name, release, dependencies, estimated tasks, work packages and
requirement ids. A planner can file from this file alone, with the rules in
[13-milestones.md](13-milestones.md).

## Size of the specification

<!--gen:areas-->

| Area | Name | Requirements | MUST | SHOULD | LATER | KEEP | FIX | NEW |
|---|---|---|---|---|---|---|---|---|
| TRK | Work tracking | 19 | 16 | 2 | 1 | 11 | 4 | 4 |
| RDY | Readiness, preflight, release | 15 | 9 | 6 | 0 | 14 | 1 | 0 |
| GRM | Grooming and shaping | 8 | 4 | 3 | 1 | 7 | 1 | 0 |
| SCH | Scheduling | 19 | 19 | 0 | 0 | 10 | 8 | 1 |
| EXE | Execution | 22 | 19 | 3 | 0 | 19 | 1 | 2 |
| CRD | Credentials | 10 | 5 | 5 | 0 | 8 | 1 | 1 |
| FLW | Workflows and chains | 18 | 13 | 4 | 1 | 18 | 0 | 0 |
| MRG | Landing and merge safety | 13 | 10 | 3 | 0 | 11 | 1 | 1 |
| CIH | CI and main-branch health | 13 | 10 | 3 | 0 | 12 | 0 | 1 |
| DLV | Delivery verification | 4 | 1 | 3 | 0 | 4 | 0 | 0 |
| REC | Recovery and no silent failure | 25 | 23 | 2 | 0 | 19 | 4 | 2 |
| API | REST API | 18 | 15 | 3 | 0 | 9 | 4 | 5 |
| MCP | MCP | 5 | 5 | 0 | 0 | 3 | 1 | 1 |
| CLI | CLI | 5 | 4 | 1 | 0 | 5 | 0 | 0 |
| IAM | Identity, authorisation, audit | 12 | 11 | 0 | 1 | 7 | 1 | 4 |
| UI | Console | 26 | 23 | 2 | 1 | 19 | 2 | 5 |
| OBS | Observability | 18 | 14 | 3 | 1 | 14 | 0 | 4 |
| DEF | Definitions and configuration | 9 | 8 | 1 | 0 | 5 | 1 | 3 |
| EXT | Extension points | 7 | 5 | 2 | 0 | 1 | 0 | 6 |
| DEP | Install, upgrade, operate | 21 | 16 | 5 | 0 | 6 | 5 | 10 |
| MIG | Migration | 15 | 14 | 0 | 1 | 10 | 2 | 3 |
| QLT | Quality bar | 25 | 24 | 1 | 0 | 7 | 3 | 15 |
| | **Total** | **327** | 268 | 52 | 7 | 219 | 40 | 68 |

<!--/gen-->

## The ten changes that matter most

Relative to DESIGN v6 and CORPUS. Detail and evidence: [11-coherence.md](11-coherence.md).

1. **Two tracks, not one line.** Building the product and migrating the estate are separated; every product milestone must be usable on a fresh cluster (CF-01).
2. **A working end-to-end chain by MS3**, on a plain Git repository with a scripted agent — instead of first execution after some 35 items (CF-02).
3. **The tracker is writable from MS1 and every capability ships with its screen**; no late "write surfaces" phase (CF-03).
4. **Ship the workflow that runs** — build, code review, test review, design review for UI, auto-merge — not the older template workflows (CF-04).
5. **Cut the extension registry, skills, context recipes, archetypes, sync controller, eval runner, Proposals and fork lane** from 1.0; extend through definitions, containers and HTTP (CF-05, CF-06, CF-10, CF-22, CF-23).
6. **One domain layer; the controller is not an HTTP client; controller-only operations leave the public API** (CF-07). MCP and CLI get a designed layer over the generated one (CF-08).
7. **Record and replay, plus a parity suite, replace the live shadow soak** as the truth instrument (CF-13).
8. **The pilot is Sortyard itself; all nine driven projects are accounted for** (eight cut over, HARNESS retires with the legacy system)**; Plane is archived, not projected to** (CF-15, CF-16).
9. **About fifteen running behaviours the design predates are now requirements** — preflight, filing verdicts, blocking causes, the review tripwire, mechanism health, release verification and more (CF-19).
10. **Close out Phase 1 honestly**: six "Done" deliverables are not in the product repository, and the evidence snapshot has not been taken (CF-17).

## Before this directory is public

These files cite the owner's estate by name: project keys, incident ids, internal documents in
the `Source:` lines, and three files that are about the estate only
([14-mapping.md](14-mapping.md), [16-legacy-parity.md](16-legacy-parity.md),
[17-evidence.md](17-evidence.md)). That is deliberate — it is the evidence — but it conflicts
with the rule this specification sets for the public repository (MIG-006: no estate names).
Recommended, as part of the publication step (OD-2): keep files 01–13 and 15 with their
`Source:` lines reduced to public references, and move 14, 16, 17 and the unreduced originals
to the private planning repository. Until then the name gate of MIG-006 does not cover this
directory.
