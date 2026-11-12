# Sortyard requirements specification

**Status:** draft for the owner's review, 2026-11-12, revised the same day for the owner's two
directions on it (below). It supersedes the phase plan in `MILESTONES.md` and `CORPUS.md` as
the thing to schedule from, and it proposes changes to `DESIGN.md` (v6) that are listed in
[11-coherence.md](11-coherence.md). Nothing outside this directory has been changed.

**Purpose.** State what the consolidated product must do, in numbered, testable requirements
with stable ids, so that a planner can turn it into scheduled board items without design
judgment, and so that nothing the current estate does well is lost without a recorded reason.

**The goal it answers** (the owner, 2026-11-12): consolidate the board, the conductor, the
dispatcher, the sync, the dashboards and the rest into "a single, self-hosted, open source
project that's at least as high quality as the plane repo", with requirements that are
"concrete, milestone based, and schedulable".

**Two rules that cut across everything** (the owner, 2026-11-12):

1. *"Anywhere sortyard diverges from the cobbled solution we have in hand, the divergence needs
   to evolve into something that's demonstrably better in as many ways possible."* Every
   divergence states its legacy baseline, the dimensions on which it is better, and a measured
   demonstration; otherwise the legacy behaviour is kept (QLT-050).
2. *"Why not plan for the best outcome imaginable and be ready to accept we might miss the mark
   by a little."* Every measured criterion has a target the plan is sized for and a floor a
   gate enforces (QLT-051).

Both are recorded, with the baselines, the scorecard and the audit of every cut, in
[18-divergences.md](18-divergences.md).

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
| Where Sortyard differs from today's system, why that is better, and how it is shown; the targets and floors | [18-divergences.md](18-divergences.md) |

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
| [18-divergences.md](18-divergences.md) | The two rules; legacy baselines BL-01 to BL-28; the scorecard; the divergence register DIV-01 to DIV-42; the audit of the cuts | — |
| [requirements.json](requirements.json) | Machine-readable index of every requirement | — |
| [tools/gen.py](tools/gen.py) | Validates this directory and refreshes its generated parts | — |

## Conventions

**Ids are stable.** `AREA-NNN`. An id is never reused or renumbered; a withdrawn requirement
keeps its id and is marked withdrawn. Other id families: `CF-nn` (coherence findings), `OD-n`
(open decisions), `LP-nnn` (legacy parity rows), `MSn` (milestones), `WPn.m` (work packages),
`BL-nn` (legacy baselines), `DIV-nn` (divergences).

**Every requirement has the same shape:**

```
### AREA-NNN — Title
**MSn** · WPn.m · PRIORITY · ORIGIN

Statement.

- AC1: an acceptance criterion that can be checked
- AC2: <what is measured>. Target: <best imaginable>. Floor: <what a gate enforces>.
- AC3: Demonstration (<method>, MSn) — <the comparison>. Target: …. Floor: … (BL-nn).

Baseline: what the estate does today, with its evidence (BL-nn).

Better on: dimension, dimension.

Source: where it comes from in the estate, or "inference"
```

- **Milestone / work package** — the one place it is delivered. `LATER` means after 1.0.
- **Priority** — `MUST` (the milestone cannot exit without it), `SHOULD` (belongs in the milestone and may slip to the next; no exit criterion depends on one), `LATER`. A `SHOULD` that preserves an estate behaviour (origin `KEEP` or `FIX`) is still owed to the estate: it is delivered, or waived by the owner in the conformance ledger (MIG-010), before the projects that rely on it are cut over (MS7b).
- **Origin**, relative to the estate as it runs — `KEEP` (the estate behaves this way and Sortyard preserves it), `FIX` (the estate does this differently and Sortyard changes it on purpose: a divergence), `NEW` (nothing in the estate occupies this place). A `FIX` requirement carries a `Baseline:` line citing a legacy baseline, a `Better on:` line naming dimensions from the closed list in [18-divergences.md](18-divergences.md) §1.3, and at least one `Demonstration` criterion; no other requirement has those two lines.
- **Acceptance criteria** are written to become tests. A criterion that states a quantity as a bar has two levels: `Target:`, the best outcome imaginable, which the work is sized for, and `Floor:`, which a gate enforces. A quantity that is a shipped policy default says "default" and has no levels. A `Demonstration (<method>, MSn)` criterion is a measured comparison against a legacy baseline, due at the exit of MSn.

**Generated parts.** [tools/gen.py](tools/gen.py) reads every requirement and refreshes
`requirements.json`, the requirement lists, totals and comparison lists in
[13-milestones.md](13-milestones.md), the scorecard and the divergence index in
[18-divergences.md](18-divergences.md), and the table below. Generated text sits between
`<!--gen:…-->` and `<!--/gen-->` markers and is never edited by hand. To move a requirement,
change its tag line and run the tool; to resize a work package, change its row in
[13-milestones.md](13-milestones.md) and run the tool.

```
python3 docs/requirements/tools/gen.py           # refresh
python3 docs/requirements/tools/gen.py --check   # validate only; non-zero exit on any problem
```

The check fails on a duplicate or malformed id, a requirement with no acceptance criterion or no
source, a reference to a requirement, criterion, finding, decision, baseline, divergence or file
that does not exist, a work package with no row in the plan, a size letter that disagrees with
its estimate, and generated text that is out of date. For the two rules it also fails when:

- a `FIX` requirement lacks its `Baseline:` (with a `BL` id), its `Better on:` (with known
  dimensions) or a `Demonstration` criterion, or is missing from the divergence register;
- a `Demonstration` criterion is malformed: an unknown method, a milestone earlier than its
  requirement's or than the one its method exists from, no target, no floor or no baseline;
- a legacy parity row that is not `KEEP`, a replaced or dropped row of
  [01-product-definition.md](01-product-definition.md) §5, or a cut listed under OD-3 cites no
  divergence entry, or cites one whose verdict does not fit;
- a finding in [11-coherence.md](11-coherence.md) has no `Divergence` line;
- a divergence entry lacks the fields its verdict needs, or its demonstrations do not resolve;
- a requirement deferred past 1.0 is not covered by a divergence entry;
- an acceptance criterion or a milestone exit states a quantity as a bar without both
  `Target:` and `Floor:`, or a requirement's statement does so with no measured criterion;
- a milestone exit omits its comparisons;
- an open decision lacks its status, or one of OD-1 to OD-4 lacks its confirm-by milestone.

It needs only the Python standard library and passes the repository's `ruff` settings. Running
it in CI belongs with QLT-012.

What it cannot check: whether a baseline is true, whether a floor really is better than its
baseline, or whether a target is the best imaginable. It recognises a bar by a number with a
unit, a percentage or a percentile, so a bar written in words escapes it; and the word
"default" exempts a criterion. Those are for the reviewer.

**`requirements.json`** holds, for each requirement: `id`, `title`, `area`, `file`, `milestone`,
`work_package`, `priority`, `origin`, the statement, the acceptance criteria, the source line,
the baseline and dimensions of a divergence, and each measured criterion with its target, floor,
method and due milestone; for each work package: its milestone, name, dependencies, size,
estimated tasks and requirement ids; for each milestone: its name, release, dependencies,
estimated tasks, work packages, requirement ids and the demonstrations due; and the baselines
and divergence entries. A planner can file from this file alone, with the rules in
[13-milestones.md](13-milestones.md).

## Size of the specification

<!--gen:areas-->

| Area | Name | Requirements | MUST | SHOULD | LATER | KEEP | FIX | NEW |
|---|---|---|---|---|---|---|---|---|
| TRK | Work tracking | 19 | 16 | 2 | 1 | 11 | 5 | 3 |
| RDY | Readiness, preflight, release | 15 | 9 | 6 | 0 | 14 | 1 | 0 |
| GRM | Grooming and shaping | 8 | 4 | 3 | 1 | 7 | 1 | 0 |
| SCH | Scheduling | 19 | 19 | 0 | 0 | 10 | 8 | 1 |
| EXE | Execution | 22 | 19 | 3 | 0 | 19 | 3 | 0 |
| CRD | Credentials | 10 | 5 | 5 | 0 | 8 | 1 | 1 |
| FLW | Workflows and chains | 19 | 14 | 4 | 1 | 18 | 1 | 0 |
| MRG | Landing and merge safety | 13 | 10 | 3 | 0 | 12 | 0 | 1 |
| CIH | CI and main-branch health | 13 | 10 | 3 | 0 | 12 | 0 | 1 |
| DLV | Delivery verification | 4 | 1 | 3 | 0 | 4 | 0 | 0 |
| REC | Recovery and no silent failure | 26 | 24 | 2 | 0 | 17 | 8 | 1 |
| API | REST API | 18 | 15 | 3 | 0 | 11 | 2 | 5 |
| MCP | MCP | 5 | 5 | 0 | 0 | 3 | 1 | 1 |
| CLI | CLI | 5 | 4 | 1 | 0 | 5 | 0 | 0 |
| IAM | Identity, authorisation, audit | 12 | 11 | 1 | 0 | 7 | 2 | 3 |
| UI | Console | 26 | 23 | 3 | 0 | 18 | 1 | 7 |
| OBS | Observability | 18 | 14 | 3 | 1 | 11 | 3 | 4 |
| DEF | Definitions and configuration | 9 | 8 | 1 | 0 | 5 | 2 | 2 |
| EXT | Extension points | 7 | 5 | 2 | 0 | 1 | 1 | 5 |
| DEP | Install, upgrade, operate | 21 | 17 | 4 | 0 | 4 | 6 | 11 |
| MIG | Migration | 17 | 16 | 0 | 1 | 10 | 0 | 7 |
| QLT | Quality bar | 27 | 26 | 1 | 0 | 8 | 1 | 18 |
| | **Total** | **333** | 275 | 53 | 5 | 215 | 47 | 71 |

<!--/gen-->

## The ten changes that matter most

Relative to DESIGN v6 and CORPUS. Detail and evidence: [11-coherence.md](11-coherence.md).

1. **Two tracks, not one line.** Building the product and migrating the estate are separated; every product milestone must be usable on a fresh cluster (CF-01).
2. **A working end-to-end chain by MS3**, on a plain Git repository with a scripted agent — instead of first execution after some 35 items (CF-02).
3. **The tracker is writable from MS1 and every capability ships with its screen**; no late "write surfaces" phase (CF-03).
4. **Ship the workflow that runs** — build, code review, test review, design review for UI, auto-merge — not the older template workflows (CF-04).
5. **Do not build what the estate never had** — the extension registry, skill and recipe objects, archetypes, a two-way definitions sync, an eval-runner service, Proposals, the fork lane — and extend through definitions, containers and HTTP (CF-05, CF-06, CF-10, CF-22, CF-23). **Keep what it has:** the concierge, the pull of definitions from Git, the quarantine merge and the experiment rig were cut or changed in the first draft and are restored ([18-divergences.md](18-divergences.md) §5).
6. **One domain layer; the controller is not an HTTP client; controller-only operations leave the public API** (CF-07). MCP and CLI get a designed layer over the generated one (CF-08).
7. **Record and replay, plus a parity suite, replace the live shadow soak** as the truth instrument (CF-13).
8. **The pilot is Sortyard itself; all nine driven projects are accounted for** (eight cut over, HARNESS retires with the legacy system)**; Plane is frozen and then archived, with a rehearsed way back, not projected to** (CF-15, CF-16; OD-4 stays open).
9. **About fifteen running behaviours the design predates are now requirements** — preflight, filing verdicts, blocking causes, the review tripwire, mechanism health, release verification and more (CF-19).
10. **Close out Phase 1 honestly**: six "Done" deliverables are not in the product repository, and the evidence snapshot has not been taken (CF-17).

Two more, from the revision of 2026-11-12:

11. **Every divergence from today's system carries a baseline, a measured demonstration and a threshold**, and each milestone exit lists the comparisons due; a baseline-capture work package opens the plan (QLT-050, WP0.4).
12. **Targets are the best outcome imaginable; floors are what gates enforce.** Zero-downtime upgrades, stalls healed in minutes with no person, a one-command install and a console that answers within 100 ms are designed for, not hoped for (QLT-051; [11-coherence.md](11-coherence.md) Part C).

## Before this directory is public

These files cite the owner's estate by name: project keys, incident ids, internal documents in
the `Source:` lines, and three files that are about the estate only
([14-mapping.md](14-mapping.md), [16-legacy-parity.md](16-legacy-parity.md),
[17-evidence.md](17-evidence.md)). That is deliberate — it is the evidence — but it conflicts
with the rule this specification sets for the public repository (MIG-006: no estate names).
Recommended, as part of the publication step (OD-2): keep files 01–13 and 15 with their
`Source:` and `Baseline:` lines reduced to public references, and move 14, 16, 17, 18 and the
unreduced originals to the private planning repository. Until then the name gate of MIG-006 does not cover this
directory.
