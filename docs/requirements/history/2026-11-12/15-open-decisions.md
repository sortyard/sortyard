# 15 — Open decisions for the owner

Only choices that are the owner's to make: licence, publication, scope, custody, hosting. Each
has a recommended default, what follows from it, and what follows from the alternative. All
work in this specification is written against the defaults.

**Status, 2026-11-12.** The owner's answer to the draft: "I can't make all these decisions
right now and for the ones I can, the defaults look ok." Every default below is therefore
**adopted as a planning assumption**: work proceeds against it and nothing waits for an answer.
Four decisions are public or hard to reverse — the licence (OD-1), publication (OD-2), the cut
list (OD-3) and the fate of Plane (OD-4). They **stay open**: each must be confirmed by the
owner at the milestone gate named, and no irreversible step is taken on it before then. For the
others the last column is the point after which changing the default costs rework.

Three decisions in the existing record are treated as settled and are not reopened: the stack
(SY-DEC-001), the repository's home (SY-DEC-003), and the native board instead of bundling or
forking Plane (DESIGN §5.2 option C, assumed throughout the corpus and consistent with the
owner's goal of 2026-11-12).

| # | Decision | Default | Status | Confirm by, or last cheap change |
|---|---|---|---|---|
| OD-1 | Licence and contribution terms | Apache-2.0, DCO, no CLA | Planning assumption; **stays open** | **Confirm by the MS3 gate** |
| OD-2 | When the repository becomes public | As a preview at v0.4 (MS3) | Planning assumption; **stays open** | **Confirm by the MS3 gate** |
| OD-3 | What is cut from 1.0 | The list below, as audited | Planning assumption; **stays open** | **Confirm by the MS3 gate** |
| OD-4 | Plane after a project cuts over | Freeze, then archive; a rehearsed rollback; no outbound projection | Planning assumption; **stays open** | **Confirm by the MS4 gate** |
| OD-5 | Where definitions are edited | In the product for fresh installs; locked to git and pulled on the owner's installation | Planning assumption | MS3 start |
| OD-6 | Where the Git host write credential lives | A GitHub App key in the cluster, mounted only in the integrator | Planning assumption | MS4 start |
| OD-7 | Pilot and cutover order | SORTYARD first; HARNESS never; then smallest first | Planning assumption | MS5 gate |
| OD-8 | Hosting assumption | Kubernetes only | Planning assumption | MS1 start |
| OD-9 | Merging past a quarantined flaky job | On for the estate, as today; off by default for new installations | Planning assumption | MS5 start |
| OD-10 | Must tasks carry named acceptance tests? | Yes for `feature` and `fix`, as policy | Planning assumption | MS2 start |
| OD-11 | Lanes for the SORTYARD board | Raise 2 → 3 for the build | Planning assumption | now |

---

## OD-1 — Licence and contribution terms

**Status.** Default adopted as planning assumption (2026-11-12). Stays open: a licence is public and relicensing needs every contributor's consent. The owner must confirm by the MS3 gate, before the repository is published; until then the repository stays private and no outside contribution is accepted.

**Default.** Apache-2.0; contributions under the Developer Certificate of Origin, checked by
CI; no contributor licence agreement; name and logo protected as trademarks; no dual licensing.

**If the default stands.** Lowest friction for people and agents contributing; patent grant;
the usual licence of the Kubernetes ecosystem. Anyone may run a hosted Sortyard, including
competitors. Relicensing later would need every contributor's consent.

**Alternative.** AGPL or a source-available licence to protect a future hosted business. It
would chill exactly the experimentation the owner wants ("throw their agents at it"), and it is
the model that made Plane unusable as a base for this project.

Affects: QLT-040, QLT-041.

## OD-2 — When the repository becomes public

**Status.** Default adopted as planning assumption (2026-11-12). Stays open: publication cannot be undone. The owner must confirm by the MS3 gate; the repository is not made public before that confirmation.

**Default.** Public as a labelled preview when MS3 ships (v0.4): the quickstart demo works and
the install is honest. Announce at 1.0. The trademark search and namespace claims (QLT-043), a
history secret scan (QLT-025) and the reduction of this directory's estate references
([README.md](README.md), "Before this directory is public") are done first.

**If the default stands.** Outside eyes and installs arrive while the design can still bend.
The repository must be clean of internal names from MS0 (MIG-006). Early visitors will see
unfinished software.

**Alternative.** Stay private until 1.0 (the corpus's Phase 6B). No exposure of rough edges, but
the first outside install happens after every decision is expensive to change, and the goldfish
runs stay the only test of legibility.

## OD-3 — What is cut from 1.0

**Status.** Default adopted as planning assumption (2026-11-12). Stays open: the list fixes what 1.0 is and what the architecture leaves out. The owner must confirm by the MS3 gate, with the usage census (MIG-017) in hand, before the public preview says what 1.0 contains. Until then nothing on the list is removed from the estate, and every conditional cut follows its census count.

**Default.** The following are out of 1.0. Each is recorded so it can return. The list was
audited against the divergence rule on 2026-11-12: the third column is the verdict, and the
entry named in the last column gives the baseline and the measured case
([18-divergences.md](18-divergences.md)).

| Cut | Why | Verdict | Where recorded |
|---|---|---|---|
| Extension registry with six kinds, SDK, scaffold | Extension by definitions, containers and HTTP covers the need without foreign code in the control plane | Stands: the estate never had one | CF-05, EXT-001, DIV-31 |
| Archetypes, roles as objects, skills as objects, context recipes | The running conductor uses fixed packet templates and the repository's own agent guide; skill files reach workers through the image and the repository, as today | Stands: not a divergence | CF-05, EXE-015, DIV-29 |
| Template workflows (Frame → Judge → Shape …) | Overridden by the owner's "Delivery lanes" | Stands: not a divergence | CF-04, DIV-30 |
| Design-first chains, chain self-repair | Not on the conductor path; the engine can express a design-first workflow | Conditional on the usage census; self-repair is replaced by Sortyard building Sortyard | FLW-017, DIV-27 |
| Two-way definitions sync and dual git/database modes | One home for definitions. The one-way pull from Git is kept (DEF-003) | Reshaped | CF-06, DEF-002, DIV-09 |
| Eval runner as a service | Reviews and required checks are the gates that run | Stands: plan-only | CF-23, DIV-31 |
| Scorecard battery, eval grid, experiment rig, inside the product | The rig stays as its own deployment unless the census shows no use | Legacy kept, outside the product | MIG-013, DIV-28 |
| Proposals task type, public roadmap projection, publish-back, fork-PR lane as product features | Project governance with standard tooling | Stands: plan-only | CF-22, QLT-013, QLT-042, DIV-31 |
| Plane outbound projection | See OD-4 | Reshaped; stays open | CF-16, DIV-32 |
| Importing historical evidence | The frozen snapshot stays the record; the baselines are loaded for comparison | Legacy kept | MIG-014, DIV-39 |
| Sentence-to-task intake, issue projection, the improvement ledger | Inferred unused | Conditional on the usage census | DIV-25, DIV-24, DIV-41 |
| Plane features the tracker does not carry, attachments and multiple workspaces included | Inferred unused | Conditional on the usage census | [01-product-definition.md](01-product-definition.md) §5.1, DIV-38 |
| Non-GitHub hosts, Docker Compose install, translations | Scope for strangers: the estate runs on GitHub and Kubernetes, in English | Stands: not a divergence | [01-product-definition.md](01-product-definition.md) §6, DIV-31 |

**Removed from this list on 2026-11-12.** The embedded concierge and approval mode: they are
built and shipped in the legacy console, and no measured case showed that removing them is
better. They are now UI-026 and IAM-012 in MS6 (DIV-26).

**If the default stands.** Of the corpus's 50 tasks still in Backlog, 10 are cancelled outright
and several more are re-scoped smaller ([14-mapping.md](14-mapping.md)); what remains is the
system that actually runs today plus what a stranger needs to install it.

**Alternative.** Keep any of them. The one the owner is most likely to want back is
design-first workflows; the census decides it if the owner does not. It can be added without
reworking anything: the engine already expresses it.

## OD-4 — Plane after a project cuts over

**Status.** Default adopted as planning assumption (2026-11-12). Stays open: it departs from the owner's own standing default of 2026-11-06. The owner must confirm by the MS4 gate, the last point at which a projection could still be built before the pilot. No Plane project is archived before that confirmation.

**Default.** At cutover the Plane project is frozen, with a pointer to Sortyard, and it is
archived read-only at the hypercare verdict. Rollback during hypercare replays what changed
since the cutover from a rollback export written by the cutover kit, and is rehearsed before
the pilot (MIG-009). Sortyard itself never writes to Plane.

**If the default stands.** No sync to build, watch or explain; the operator moves to the new
console at once. For a week per project, rollback is a rehearsed procedure of minutes rather
than a switch, and it loses nothing done since the cutover.

**Alternative.** The standing default of 2026-11-06, "Plane read-only projection for one
milestone": a one-way projection keeps Plane current. It costs a large task (the corpus's M3.12)
and keeps two places to look.

## OD-5 — Where definitions are edited

**Status.** Default adopted as planning assumption (2026-11-12).

**Default.** The database is the single home for definitions. On a fresh install an operator
edits them in the console, with versions, audit and export. On the owner's installation
definitions are locked to a git repository: Sortyard pulls them from reviewed commits, as the
legacy conductor does today, and the console shows them read-only (DEF-003).

**If the default stands.** "Definition edits via git PRs" remains true for the owner, as a
setting rather than an architecture; strangers get a product that works without a definitions
repository; there is no two-way synchroniser.

**Alternative.** Git as the system of record with a sync controller (DESIGN §5.1). It keeps
review in git for everyone and reintroduces a second source of truth with a degraded mode.

## OD-6 — Where the Git host write credential lives

**Status.** Default adopted as planning assumption (2026-11-12).

**Default.** A GitHub App installed on the driven repositories; its private key is a Secret
mounted only in the integrator pod; tokens are minted per operation with the narrowest
permissions and revoked when the operation ends. Today's arrangement — the owner's personal token in a cluster
Secret, with an expiry date to track — is replaced.

**If the default stands.** Least privilege, no personal token, per-repository scoping, no expiry
date to remember. A long-lived App key is in the cluster, protected by the integrator's
isolation; installing the App on each organisation is the owner's action.

**Alternative.** Keep the write credential outside the cluster (the design's original stance):
the integrator would run operator-side. More isolation, and the factory stops whenever that
host does.

## OD-7 — Pilot and cutover order

**Status.** Default adopted as planning assumption (2026-11-12).

**Default.** The pilot is the SORTYARD project itself. HARNESS is not migrated: its remaining
items are maintenance of the system being retired and stay on Plane until it is. Then, one at a
time with a 7-day window each: WALWARDEN, CRANK, CLOSER, NONCE, ROVE, LOOP, CPV2 — smallest and
least entangled first, Cortexplane last because it needs release verification (DLV-003).

**If the default stands.** "Sortyard builds Sortyard" is the first proof and the lowest-risk
one. Nine cutovers become eight. The four projects the corpus omitted are accounted for.

**Alternative.** The corpus's order (HARNESS, then Rove, Loopmentum, Cortexplane). It migrates a
board that is about to die and leaves four driven projects without a plan.

## OD-8 — Hosting assumption

**Status.** Default adopted as planning assumption (2026-11-12).

**Default.** Kubernetes only for 1.0 (kind and k3s for small installs). No Docker Compose
bundle.

**If the default stands.** One install path to make excellent. The audience is narrower than
Plane's — people without a cluster must start one — and the one-command kind replica is the
answer for them.

**Alternative.** Also ship Compose. Workers are Kubernetes Jobs, so a Compose install needs a
second executor implementation and a second set of isolation guarantees.

## OD-9 — Merging past a quarantined flaky job

**Status.** Default adopted as planning assumption (2026-11-12).

**Default.** The behaviour is a policy. The estate bundle ships it on, as today: an admin
merge, once per head, when every other required check is accepted. The default bundle for new
installations ships it off: a pull request held only by a quarantined job waits and says so.

**If the default stands.** Nothing changes for the estate at cutover. The product still needs
a credential with bypass rights on the estate's installation — the most powerful permission in
the system — and "never `--admin`" keeps its one exception there.

**Alternative.** Off for the estate too. "Never bypass a gate" then has no exception, and until
repositories make their flaky jobs non-required, some approved pull requests wait where today
they merge. The earlier draft proposed this; it was withdrawn because nothing measured showed
the wait to be worth it (DIV-33).

## OD-10 — Must tasks carry named acceptance tests?

**Status.** Default adopted as planning assumption (2026-11-12).

**Default.** Yes for `feature` and `fix`, as a per-project policy that defaults on. This matches
the ready rules as they run and leaves the estate's open `DEC-ACCEPTANCE` decision free to turn
it off per project.

**If the default stands.** Nothing changes for the estate at cutover. The design record's
statement that tasks carry "no acceptance tests" is not implemented as a rule.

**Alternative.** Outcome only, verification left to workflows. Shorter tasks; it removes the
handle that sizing ("at most three tests") and scoped review hang on.

## OD-11 — Lanes for the SORTYARD board

**Status.** Default adopted as planning assumption (2026-11-12).

**Default.** Raise SORTYARD from 2 to 3 lanes while the product is being built, taking the lane
from whichever project the owner ranks lowest.

**If the default stands.** The plan's lane time drops by about a third. Another project slows.

**Alternative.** Stay at 2. Nothing else changes; the estimate in
[13-milestones.md](13-milestones.md) is for 2 lanes.
