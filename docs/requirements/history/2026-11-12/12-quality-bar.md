# 12 — Quality bar

Area: **QLT**. The owner's bar: "at least as high quality as the plane repo (should be much
higher)". This file turns that into checkable requirements. Section 1 records what Plane does,
verified in a clone; section 2 states where Sortyard matches and where it must exceed; the
requirements follow.

## 1. The benchmark, as verified

Source: `github.com/makeplane/plane` cloned at `0b9ca51` on 2026-11-12, plus
`makeplane/helm-charts`, the repository's tag list, and its published security advisories
(GitHub API). Counts are from `find`/`grep` on the clone. "Not found" means not found in the
repository; it does not prove absence elsewhere.

| Dimension | Plane, as found | Evidence |
|---|---|---|
| Deployable units | 13 services in the community self-host bundle: web, space, admin, live, api, worker, beat-worker, migrator, proxy, Postgres, Redis, RabbitMQ, MinIO | `deployments/cli/community/docker-compose.yml` |
| Stateful dependencies | 4 (Postgres, Redis, RabbitMQ, MinIO) | same |
| Configuration surface | 58 variables in the self-host env file | `deployments/cli/community/variables.env` |
| Stated minimum | 2 vCPU, 4 GB RAM | `deployments/cli/community/README.md` |
| Install and operate | A menu-driven `setup.sh`: install, start, stop, restart, upgrade, logs, backup; restore scripts including an air-gapped one | same directory |
| Kubernetes | A separate chart repository (`plane-ce`), with values for each service and dependency | `makeplane/helm-charts` |
| Pull-request gates | API: `ruff check`. Web: format, build, lint, types. Also: migration check, CodeQL, i18n sync check, copyright check, version check before release | `.github/workflows/*.yml` |
| Tests run in CI | No workflow invokes `pytest`, `vitest`, `jest` or a `test` task | `grep` over `.github/workflows` |
| Tests in the repo | About 140 `test_*.py` files beside about 450 API source files; 52 test/spec files across the web apps and packages beside about 2,100 TS/TSX source files; no browser end-to-end suite found | `find` counts |
| Published security advisories | 89, of which 83 in 2026; 8 critical, 39 high. By weakness: 29 authorisation bypass through a user-controlled key, 16 missing authorisation, 8 improper access control, 4 incorrect authorisation, 9 server-side request forgery | GitHub advisories API |
| Container user | No `USER` directive in the API, web and live Dockerfiles | `apps/*/Dockerfile.*` |
| Telemetry | Instance telemetry field defaults to enabled | `plane/license/migrations/0001_initial.py` |
| Accessibility | Static only: the `jsx-a11y` lint plugin is enabled with lint categories at warning level, and a third-party scan (React Doctor) comments on pull requests. No runtime scan (axe, pa11y, Lighthouse, Playwright) in the workflows or package manifests; no accessibility statement found | `.oxlintrc.json`; `.github/workflows/react-doctor.yml`; `grep` |
| Locales | 22 | `packages/i18n/src/locales` |
| Licence | AGPL-3.0; open-core with a commercial edition | `LICENSE.txt`; `plane-enterprise` chart |
| Contribution terms | Neither a CLA nor DCO sign-off is mentioned in `CONTRIBUTING.md` | `grep` |
| Security policy | Private reporting; acknowledgement within three business days | `SECURITY.md` |
| Releases | 28 stable releases since the first tag; about one a month since 1.0 (2025-09); some release notes under 100 characters | tag list and release data |
| API | OpenAPI through drf-spectacular; API-key rate limit default 60/minute; HMAC-signed webhooks | `apps/api/pyproject.toml`, `settings/common.py`, `bgtasks/webhook_task.py` |
| Agent guidance | A 59-line `AGENTS.md` | repository root |
| Migrations | 126 Django migration files; a migrator container; one version-specific shell migration (`0.13 → 0.14`) | `apps/api/plane/db/migrations`, `deployments/cli/community` |

## 2. Match, exceed, and one place to stay behind

**Match:** private vulnerability reporting with a stated response time; CodeQL and dependency
scanning; lint, format and type gates; a migration check; a generated OpenAPI document; signed
webhooks; an agent guide in the repository; backup and restore tooling.

**Exceed, because the evidence shows room:**

1. **Tests gate merges.** Plane's public workflows run no tests. Sortyard runs its whole suite on every pull request (QLT-010 to QLT-015).
2. **Authorisation is correct by construction and proven cell by cell.** Two thirds of Plane's advisories are authorisation flaws. Sortyard has one default-deny authorisation function, object scoping in the data layer, and a generated test per operation × role (IAM-009, IAM-010, QLT-021).
3. **Install weight.** 13 services and 4 stateful dependencies against 3 workloads and Postgres (DEP-001, DEP-003); 58 variables against none required (DEP-006).
4. **Upgrades are a tested guarantee**, not a script (DEP-008, QLT-031).
5. **Supply chain.** Signed images, SBOM and build provenance on every release; non-root, restricted pods (QLT-022 to QLT-025, DEP-014).
6. **No telemetry** (OBS-015) and **no open-core split** (QLT-041).
7. **Documentation is executed.** Every command in the docs runs in CI; a zero-context agent must be able to install and operate from the docs alone (QLT-001, QLT-004).
8. **Accessibility is a gate on the rendered product.** Plane lints markup; nothing scans what is rendered. Sortyard runs an automated scan and keyboard-only journeys on every route as required checks, targeting WCAG 2.2 AA (UI-019, UI-020).

**Stay behind, on purpose:** internationalisation. Plane ships 22 locales; Sortyard 1.0 ships
English with externalised strings (UI-025). The operator audience is small and technical;
translation is taken up when someone asks for it.

**Where each dimension is specified.** Some of the bar lives in other files; this is the index.

| Dimension | Plane, from section 1 | Sortyard's bar | Requirements |
|---|---|---|---|
| Documentation | A 59-line agent guide; hosted docs not examined | Docs built from the repository, every command executed in CI, generated references, a zero-context install at every milestone | QLT-001 to QLT-005 |
| Install time | Not measured; 13 services, 4 stateful dependencies, 58 variables | Target: one command and 3 minutes to a first task, 5 more to a finished demo chain; idle footprint 0.25 CPU and 512 MiB. Floor: 8 commands and 15 minutes, 30 minutes to the demo, 0.5 CPU and 1 GiB. No value required | DEP-005, DEP-006, DEP-013 |
| Upgrade guarantees | An upgrade option in `setup.sh`; no stated guarantee found | Tested upgrades with data from every earlier minor; one-minor rollback without a restore; work in flight survives. Target: zero failed requests and zero paused seconds in an upgrade. Floor: at most 5 s of failed requests, never silent | DEP-007 to DEP-010, REC-015, QLT-031 |
| Tests and CI | No workflow runs tests | Every test layer on every pull request; coverage targets with floors under them; no tolerated flakes; required checks in 5 minutes at p95 as the target, 15 as the floor | QLT-010 to QLT-016 |
| Security and supply chain | 89 advisories, two thirds of them authorisation flaws; no `USER` directive | One default-deny authorisation function tested cell by cell; threat model and independent review; signed images with SBOM and provenance; restricted pods | IAM-009, IAM-010, QLT-020 to QLT-025, DEP-014 |
| API stability | A generated OpenAPI document; no written deprecation policy found | `/v1` frozen at 1.0, additive only; deprecations kept two minors or six months; breaking changes fail CI | API-013, EXT-007, QLT-030 |
| Accessibility | Lint only | WCAG 2.2 AA target; automated scan and keyboard journeys as required checks; three viewport widths | UI-019, UI-020 |
| Internationalisation | 22 locales | English only, strings externalised, a pseudo-locale build in CI | UI-025 |
| Licensing and governance | AGPL-3.0, open core; neither CLA nor DCO mentioned | Apache-2.0 with DCO, nothing withheld, governance files (owner's decision OD-1) | QLT-040 to QLT-043 |
| Telemetry | Defaults to enabled | None | OBS-015 |

---

## Documentation

### QLT-001 — The docs are a tested product surface
**MS8** · WP8.1 · MUST · NEW

A docs site built from the repository, with: quickstart, install, upgrade, concepts, an
operations guide written around reason codes and absent states, troubleshooting, and generated
references (API, CLI, policy keys, reason codes, permission matrix, metrics, chart values). Every
command block in the docs is executed in CI against the replica.

- AC1: A doc command that fails breaks the build.
- AC2: The generated references are never edited by hand (drift check).
- AC3: The public docs contain no internal host, project or person names (grep gate, MIG-006).

Source: `tests/test_readme.py` (the quickstart is already tested); goldfish GF1-04; CORPUS M6.1.

### QLT-002 — README
**MS0** · WP0.1 · MUST · NEW

The README says what Sortyard is, shows the quickstart, links the docs, and states the project's
status honestly. Charter, tracking notes and internal references move out.

- AC1: Top to bottom, the README has no statement that contradicts another part of it.

Source: goldfish GF1-04 (the charter half contradicts the top half and links internal hosts).

### QLT-003 — Contributor and agent guide
**MS0** · WP0.1 · MUST · NEW

`AGENTS.md` and `CONTRIBUTING.md` at the root: the architecture map, how to run the replica and
the checks, the conventions (schema-first models, domain commands, one event per change), how to
add a requirement-bearing change, and the definition of done.

- AC1: A zero-context agent lands a small, correct change using only the repository (the goldfish test for contributors), and its friction list is empty of blockers.

Source: goldfish GF1-03 (no `AGENTS.md`); DESIGN §11.2; SORTYARD-13.

### QLT-004 — Goldfish gate at every milestone
**MS1** · WP1.7 · MUST · KEEP

At each milestone exit a zero-context agent, given only the public repository and docs, installs
the release candidate and performs the milestone's exit demonstration. Its findings are filed;
blockers hold the milestone. The run must happen on a machine that has the prerequisites and
network the docs assume.

- AC1: The report follows the existing format (run log, findings with severity and evidence, verdict).
- AC2: Findings from the previous report are fixed, not just filed, before the next one runs.

Source: `docs/goldfish/phase-1-install-smoke.md` (verdict: blocked; the cluster steps were not run because the environment had no tools or network); CORPUS R7 (the legibility thread).

### QLT-005 — Decision records and changelog
**MS0** · WP0.1 · MUST · KEEP

Architecture decisions are records with a date, an owner and a status in `DECISIONS.md` (or one
file each). `CHANGELOG.md` follows Keep a Changelog; every user-visible change has an entry.

- AC1: The product repository's `DECISIONS.md` contains SY-DEC-001 to SY-DEC-003 and the decisions this specification asks for (see [15-open-decisions.md](15-open-decisions.md)).

Source: `DECISIONS.md` in the repo holds only SY-DEC-001; the meta-harness copy also has 002 and 003.

---

## Tests and CI

### QLT-010 — Evidence by layer
**MS1** · WP1.1 · MUST · KEEP

Tests sit at the cheapest layer that proves the behaviour: **domain** — one unit test per
state-machine transition and one per refused transition; **API and persistence** — contract
tests against a real Postgres: schemas, errors, authorisation, isolation, idempotency,
migrations; **UI** — component state tests and end-to-end journeys; **deploy** — one smoke per
pull request that builds the image, installs the chart on a kind cluster and expects readiness;
**scenario** — whole chains against the Git host and CI fakes with the scripted harness.

- AC1: Each layer is a named CI job and a required check.
- AC2: No test sleeps on the wall clock; the clock is injected.
- AC3: A test that asserts only what its fixture put in is rejected in review.

Source: AGENTS.md "Testing model" (the estate's own standard, applied to Sortyard).

### QLT-011 — Coverage targets and floors
**MS1** · WP1.1 · MUST · NEW

Coverage is measured for each layer and enforced in CI: branch coverage of the domain layer,
line coverage of the whole backend, statement coverage of the console beside the journey suite.
The floors only rise.

- AC1: Coverage of the domain layer, the whole backend and the console, in that order. Target: 100%, 90% and 85%. Floor: 90%, 80% and 70%; CI fails below a floor.

Source: inference — Plane publishes no coverage figure; the legacy `test_conductor.py` (10,364 lines for 2,589 of code) sets the house standard.

### QLT-012 — Every pull request runs everything
**MS0** · WP0.1 · MUST · KEEP

Lint, format, strict type-check, generated-code and generated-document drift (including this
directory's `tools/gen.py --check`), all test layers, chart lint and render, image build and the
install smoke run on every pull request and are required. No job is `continue-on-error`.

- AC1: `main` is never red: a failing required check on `main` is treated as an incident.
- AC2: The p95 duration of the required checks on a pull request. Target: 5 minutes. Floor: 15 minutes.

Source: AGENTS.md "Green main, stop the line" (the estate's own standard, kept); `.github/workflows/ci.yml` (the `spec` job is `continue-on-error`, a gap in the prototype repository).

### QLT-013 — Fork pull requests are safe to run
**MS8** · WP8.5 · MUST · NEW

Pull requests from forks run the full required checks on provider-hosted runners with no
secrets and read-only permissions. Nothing in the required checks needs a secret.

- AC1: A fork pull request gets the same green or red as a branch pull request.

Source: DESIGN §11.2 (fork-PR verification); `ci.yml` already uses `ubuntu-latest` with `contents: read`. The estate's "no GitHub-hosted runners" rule is about estate work and does not apply to this public repository.

### QLT-014 — Flaky tests are not tolerated
**MS1** · WP1.1 · MUST · KEEP

A test that fails intermittently is quarantined with a recorded reproduction and a task within
one day, and fixed or deleted within two weeks. Nobody re-runs to get green.

- AC1: The quarantine list is in the repository and is empty at each release.

Source: AGENTS.md "Testing model" ("Never rerun just to seek a green result").

### QLT-015 — Scenario suite as a product asset
**MS3** · WP3.10 · MUST · NEW

The scripted harness and the demo repository (MS3), and the Git host fake and the CI fake (MS4,
built with their adapters in WP4.1), are shipped and documented, so that adopters and extension
authors can test against them.

- AC1: The fakes implement the adapter interfaces (EXT-003, CIH-013) and pass the same conformance tests as the real adapters where the behaviour is defined.

Source: AGENTS.md "Delivery lanes" rule 5 ("fakes encode the providers' documented behaviour").

### QLT-016 — Performance bars on a reference workload
**MS6** · WP6.4 · MUST · NEW

On the reference workload (20 projects, 50,000 tasks, 5,000 open, 200 chains in flight) the
product stays fast enough that nobody waits for it. A load job measures the bars below before
each release; console latency is in UI-009 and UI-018.

- AC1: List and detail API latency. Target: p95 at most 50 ms. Floor: p95 at most 300 ms.
- AC2: Scheduler evaluation of one project. Target: at most 200 ms. Floor: at most 2 s.
- AC3: Event-stream lag from commit to a subscribed client. Target: at most 250 ms. Floor: at most 2 s.
- AC4: The load job's results are in the release notes and the scorecard (QLT-051).

Source: harness-console J1 (2 s), J2 (10,000 rows); `architecture.md` ("datasets of ~10^3–10^4 requests").

---

## Security and supply chain

### QLT-020 — Security policy and response
**MS8** · WP8.2 · MUST · NEW

`SECURITY.md`: a private reporting channel; a stated time to acknowledge a report; a stated time
to a fix or mitigation for high and critical findings; advisories published with affected
versions.

- AC1: The reporting channel is tested before 1.0.
- AC2: Time to acknowledge a report, and time to a fix or mitigation for a high or critical finding. Target: one business day and 7 days. Floor: three business days and 30 days.

Source: Plane `SECURITY.md` (three business days) — matched, with fix targets added.

### QLT-021 — Threat model and security review before 1.0
**MS8** · WP8.2 · MUST · NEW

A written threat model covering: the permission matrix and token scopes; stage tokens and the
worker boundary; the integrator and its credential; packets carrying untrusted task text to
agents (prompt injection that tries to exfiltrate credentials or write outside the task); inbound
and outbound webhooks; the proxy-header sign-in mode. An independent adversarial review tests it;
findings are closed or accepted in writing.

- AC1: The review includes an attempt to make a worker act outside its binding and an attempt to reach another project's objects.

Source: CORPUS M6.2 ("an adversarial review of the binding path"); Plane's advisory profile.

### QLT-022 — Dependencies are pinned and scanned
**MS1** · WP1.1 · MUST · NEW

Python and JavaScript dependencies are locked with hashes. Dependency updates arrive by bot.
CodeQL, a dependency audit and a container scan run in CI; a known high or critical
vulnerability with a fix available blocks release.

- AC1: The image contains no package without a locked version.

Source: `pyproject.toml` (ranges, no lock file today); Plane benchmark (CodeQL workflow, `.trivyignore`, `uv sync --locked`).

### QLT-023 — Signed artefacts with provenance
**MS8** · WP8.2 · MUST · NEW

Each release publishes images and the chart to an OCI registry, signed (keyless), with an SBOM
and a build-provenance attestation. The docs show how to verify them, and the install test
verifies them.

- AC1: A tampered image fails verification in the install test.

Source: CORPUS M6.2 ("image signing and build provenance"); the legacy release controller's digest pinning and source-ancestry checks (CI-RELEASE.md) — the guarantee is kept, the bespoke controller is not.

### QLT-024 — Releases come from CI, from a tag
**MS1** · WP1.6 · MUST · FIX

A release is produced only by the release workflow from a signed tag on `main`, and every merge
to `main` publishes a development build the same way, so the newest merged code is always
installable. Nothing is built on a laptop. The workflow holds no cluster credential.

- AC1: The release workflow is the only identity allowed to push release artefacts.
- AC2: Demonstration (ledger, MS7) — for every merge to `main` during the pilot, the time from the merge to the running installation serving it, from the release workflow and the ledger. Target: every merge running within 10 minutes, with no person involved. Floor: no person and no hand-applied object involved, and no slower than the legacy merge-to-release time; the legacy release of 2026-11-12 needed a Role applied by hand (BL-11).

Baseline: Merged changes to the legacy control plane were not released until someone released them (task-pickup conformance row 8, HARNESS-246); the pull-based release controller that followed was blocked for about 32 minutes on 2026-11-12 by a hand-maintained Role (BL-11).

Better on: latency, operator-actions, safety.

Source: DESIGN §9 ("the reboot's own releases go through CI like everything else"); CI-RELEASE.md ("It has no Kubernetes credential or cluster network path").

### QLT-025 — Secrets never enter the repository
**MS0** · WP0.1 · MUST · NEW

A secret scanner runs on every pull request and on history before the repository is made
public.

- AC1: The pre-publication history scan is recorded with its result.

Source: the repository is private today and was seeded from an internal folder.

---

## Versioning, releases, governance

### QLT-030 — Semantic versioning with one number for app, chart and API
**MS1** · WP1.6 · MUST · NEW

The application, the image and the chart share one version. Before 1.0, minors may break with
notice; from 1.0, semantic versioning applies to the API, the CLI, the chart values, the stage
contract and the database upgrade path.

- AC1: One version string is stamped into the image, the chart and the served OpenAPI document, and CI fails when they differ. What counts as breaking is defined mechanically by the compatibility jobs when they land (API-013, DEP-008, EXT-007).

Source: DEP-020; `Chart.yaml` (`version` and `appVersion` both 0.1.0).

### QLT-031 — Release notes and upgrade notes, always
**MS1** · WP1.6 · MUST · NEW

Every release has notes generated from the changelog plus an upgrade section (migrations,
duration, anything to do by hand). Each milestone ends in a tagged pre-release.

- AC1: The release workflow fails without an upgrade section.

Source: Plane benchmark (release notes of 62–99 characters on some stable releases).

### QLT-032 — Release cadence and support window
**MS8** · WP8.5 · SHOULD · NEW

After 1.0: a minor about every six weeks; security fixes for the latest two minors.

- AC1: The policy is in `GOVERNANCE.md` and the docs.

Source: inference; Plane ships about monthly.

### QLT-040 — Licence and contribution terms
**MS8** · WP8.5 · MUST · KEEP

Apache-2.0. Contributions under the Developer Certificate of Origin, checked mechanically; no
CLA. A licence scan keeps copyleft dependencies out of the distributed image. Confirmation is
the owner's (OD-1).

- AC1: A commit without sign-off fails the DCO check.
- AC2: The licence scan is a required check.

Source: `LICENSE` (Apache-2.0, SY-DEC-001 seed); INTENDED-USE.md standing default; DESIGN §11.5.

### QLT-041 — No withheld pieces
**MS8** · WP8.5 · MUST · KEEP

Everything needed to run Sortyard as described in its docs is in the public repository under the
project licence. There is no enterprise edition of the code.

- AC1: The docs describe no feature that the public artefacts do not contain.

Source: DESIGN §11.6.

### QLT-042 — Governance files
**MS8** · WP8.5 · MUST · NEW

`GOVERNANCE.md` (who decides, how a maintainer is added), `MAINTAINERS`, `CODE_OF_CONDUCT.md`,
issue and pull-request templates, a trademark note for the name and logo, and a public roadmap
kept as milestones in the repository's own tracker.

- AC1: The roadmap is generated from, or is, the real milestone list — not a separate page.

Source: DESIGN §11.5; CORPUS M6.6.

### QLT-043 — Name clearance
**MS3** · WP3.10 · MUST · KEEP

A trademark search for "Sortyard" is completed and recorded, and the package namespaces (GitHub
organisation, PyPI, npm, container registry) are claimed, before the repository is made public.

- AC1: The record is in `DECISIONS.md`.

Source: DESIGN §10 item 1 ("Still owed before public launch: a formal trademark search"; namespaces unclaimed at check time).

---

## Divergences, targets and floors

Two rules from the owner (2026-11-12) that cut across every other requirement. The register
they govern — baselines, divergences, the audit of every cut and the scorecard of measured
criteria — is [18-divergences.md](18-divergences.md).

### QLT-050 — Every divergence from the estate is demonstrably better, or the legacy behaviour is kept
**MS0** · WP0.1 · MUST · NEW

Wherever Sortyard behaves differently from the estate's system — a requirement with origin
`FIX`, a legacy parity row that is not `KEEP`, a cut, a finding that replaces a mechanism — this
specification records the legacy baseline with its evidence, the dimensions on which the new
behaviour is better, and a demonstration: a measured comparison against the baseline with a
threshold, made by replay, the parity suite, ledger metrics, a scripted benchmark, fault
injection, a count, a drill or the usage census. "Different but equivalent" does not pass. A
divergence whose demonstration misses its floor is not shipped to the estate: the legacy
behaviour stays, as the estate bundle's setting or as the requirement itself, until the
demonstration passes.

- AC1: `tools/gen.py --check` fails when a `FIX` requirement lacks its `Baseline:`, its `Better on:` or its demonstration; when a parity row that is not `KEEP`, a cut or a replacing finding cites no divergence entry; and when a divergence entry lacks the fields its verdict needs.
- AC2: Each demonstration is a named test or job (rule 3 of [13-milestones.md](13-milestones.md)) that reads its baseline from the captured values (MIG-016) and fails below its floor.
- AC3: A change that introduces a new divergence adds its entry and its demonstration in the same pull request; review rejects it otherwise.
- AC4: Before each cutover the divergences the project relies on are listed with their measured results in the hypercare plan (MIG-009); one that missed its floor is switched to the legacy behaviour for that project.

Source: the owner, 2026-11-12 ("Anywhere sortyard diverges from the cobbled solution we have in hand, the divergence needs to evolve into something that's demonstrably better in as many ways possible").

### QLT-051 — Plan for the target, gate on the floor
**MS1** · WP1.1 · MUST · NEW

Every measured criterion has two levels. The **target** is the best outcome imaginable for a
product of this kind, set from first principles and from the best tools in the field; the
design and the work packages are sized for it. The **floor** is what a gate enforces: better
than the legacy baseline where there is one, and the stated absolute bar where there is not. A
cutover, a promotion or a milestone exit needs only the floors. Each measured value is recorded
with its target and floor in a scorecard. A value between floor and target opens one
`target-gap` task in Backlog — backlog, not failure — which closes when the target is met or
the owner retires it.

- AC1: `tools/gen.py --check` fails when an acceptance criterion or a milestone exit states a quantity as a bar without both a target and a floor. A quantity that is a shipped policy default is exempt and says so.
- AC2: Tests assert the floor and write the measured value to `scorecard.json` in the release artefacts; from MS6 a dashboard shows value, floor, target and trend for every criterion listed in [18-divergences.md](18-divergences.md) §3 (UI-015).
- AC3: At each milestone gate every criterion due is at or above its floor, and each one below its target has exactly one open `target-gap` task naming the measured value.
- AC4: A target is never lowered to fit a measurement; changing one is a change to this specification, with the reason recorded.

Source: the owner, 2026-11-12 ("Why not plan for the best outcome imaginable and be ready to accept we might miss the mark by a little").
