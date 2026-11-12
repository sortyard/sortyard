# 15 — Open decisions for the owner

Only choices that are the owner's to make: licence, publication, scope, custody, hosting. Each
has a recommended default, what follows from it, what follows from the alternative, and the
milestone by which silence means the default applies. All work in this specification is written
against the defaults.

Three decisions in the existing record are treated as settled and are not reopened: the stack
(SY-DEC-001), the repository's home (SY-DEC-003), and the native board instead of bundling or
forking Plane (DESIGN §5.2 option C, assumed throughout the corpus and consistent with the
owner's goal of 2026-11-12).

| # | Decision | Default | Decide by |
|---|---|---|---|
| OD-1 | Licence and contribution terms | Apache-2.0, DCO, no CLA | MS3 gate |
| OD-2 | When the repository becomes public | As a preview at v0.4 (MS3) | MS3 gate |
| OD-3 | What is cut from 1.0 | The list below | MS1 start |
| OD-4 | Plane after a project cuts over | Archive and link; no outbound projection | MS2 gate |
| OD-5 | Where definitions are edited | In the product for fresh installs; locked to git on the owner's installation | MS3 start |
| OD-6 | Where the Git host write credential lives | A GitHub App key in the cluster, mounted only in the integrator | MS4 start |
| OD-7 | Pilot and cutover order | SORTYARD first; HARNESS never; then smallest first | MS5 gate |
| OD-8 | Hosting assumption | Kubernetes only | MS1 start |
| OD-9 | Merging past a quarantined flaky job | Off by default | MS5 start |
| OD-10 | Must tasks carry named acceptance tests? | Yes for `feature` and `fix`, as policy | MS2 start |
| OD-11 | Lanes for the SORTYARD board | Raise 2 → 3 for the build | now |

---

## OD-1 — Licence and contribution terms

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

**Default.** The following are out of 1.0. Each is recorded so it can return.

| Cut | Why | Where recorded |
|---|---|---|
| Extension registry with six kinds, SDK, scaffold | Extension by definitions, containers and HTTP covers the need without foreign code in the control plane | CF-05, EXT-001 |
| Archetypes, roles as objects, skills, context recipes | The running conductor uses fixed packet templates and the repository's own agent guide | CF-05, EXE-015 |
| Template workflows (Frame → Judge → Shape …), design-first chains, chain self-repair | Overridden by the owner's "Delivery lanes"; the engine can express them later | CF-04, FLW-017 |
| Definitions sync controller and dual git/database modes | One home for definitions | CF-06, DEF-002 |
| Eval runner, scorecard battery, eval grid, experiment rig | Reviews and required checks are the gates that run; the rig gets its own fate | CF-23, MIG-013 |
| Proposals task type, public roadmap projection, publish-back, fork-PR lane as product features | Project governance with standard tooling | CF-22, QLT-013, QLT-042 |
| Embedded concierge | The operator's own agent reaches the same data over MCP | UI-026 |
| Plane outbound projection | See OD-4 | CF-16 |
| Importing historical evidence | The frozen snapshot stays the record | MIG-014 |
| Multi-workspace, non-GitHub hosts, Docker Compose install, translations, attachments | Scope | [01-product-definition.md](01-product-definition.md) §6 |

**If the default stands.** Of the corpus's 50 tasks still in Backlog, 11 are cancelled outright
and several more are re-scoped smaller ([14-mapping.md](14-mapping.md)); what remains is the
system that actually runs today plus what a stranger needs to install it.

**Alternative.** Keep any of them. The two the owner is most likely to want back are the
concierge (it exists and is liked) and design-first workflows. Either can be added after MS6
without reworking anything: the API and MCP tools it needs are already required.

## OD-4 — Plane after a project cuts over

**Default.** At cutover the Plane project is archived read-only with a pointer to Sortyard.
Rollback during hypercare restores from the frozen snapshot. Sortyard never writes to Plane.

**If the default stands.** No sync to build, watch or explain; the operator moves to the new
console at once. For a week per project, rollback means re-enabling the old driver from a
snapshot rather than flipping a switch.

**Alternative.** The standing default of 2026-11-06, "Plane read-only projection for one
milestone": a one-way projection keeps Plane current. It costs a large task (the corpus's M3.12)
and keeps two places to look.

## OD-5 — Where definitions are edited

**Default.** The database is the single home for definitions. On a fresh install an operator
edits them in the console, with versions, audit and export. On the owner's installation
definitions are locked to a git repository: changes arrive only by `apply` from reviewed
commits, and the console shows them read-only.

**If the default stands.** "Definition edits via git PRs" remains true for the owner, as a
setting rather than an architecture; strangers get a product that works without a definitions
repository; there is no synchroniser.

**Alternative.** Git as the system of record with a sync controller (DESIGN §5.1). It keeps
review in git for everyone and reintroduces a second source of truth with a degraded mode.

## OD-6 — Where the Git host write credential lives

**Default.** A GitHub App installed on the driven repositories; its private key is a Secret
mounted only in the integrator pod; tokens are minted per operation with the narrowest
permissions and expire in minutes. Today's arrangement — the owner's personal token in a cluster
Secret, with an expiry date to track — is replaced.

**If the default stands.** Least privilege, no personal token, per-repository scoping, no expiry
date to remember. A long-lived App key is in the cluster, protected by the integrator's
isolation; installing the App on each organisation is the owner's action.

**Alternative.** Keep the write credential outside the cluster (the design's original stance):
the integrator would run operator-side. More isolation, and the factory stops whenever that
host does.

## OD-7 — Pilot and cutover order

**Default.** The pilot is the SORTYARD project itself. HARNESS is not migrated: its remaining
items are maintenance of the system being retired and stay on Plane until it is. Then, one at a
time with a 7-day window each: WALWARDEN, CRANK, CLOSER, NONCE, ROVE, LOOP, CPV2 — smallest and
least entangled first, Cortexplane last because it needs release verification (DLV-003).

**If the default stands.** "Sortyard builds Sortyard" is the first proof and the lowest-risk
one. Nine cutovers become eight. The four projects the corpus omitted are accounted for.

**Alternative.** The corpus's order (HARNESS, then Rove, Loopmentum, Cortexplane). It migrates a
board that is about to die and leaves four driven projects without a plan.

## OD-8 — Hosting assumption

**Default.** Kubernetes only for 1.0 (kind and k3s for small installs). No Docker Compose
bundle.

**If the default stands.** One install path to make excellent. The audience is narrower than
Plane's — people without a cluster must start one — and the one-command kind replica is the
answer for them.

**Alternative.** Also ship Compose. Workers are Kubernetes Jobs, so a Compose install needs a
second executor implementation and a second set of isolation guarantees.

## OD-9 — Merging past a quarantined flaky job

**Default.** Off. A pull request held only by a quarantined job waits and says so; the fix is
to make that job non-required at the source.

**If the default stands.** "Never bypass a gate" has no exception in the product. Until
repositories adapt their required checks, some approved pull requests wait where today they
merge.

**Alternative.** Keep today's behaviour as an opt-in policy: an admin merge, once per head, when
every other required check is accepted. It needs a credential with bypass rights — the most
powerful permission in the system — and is the one place the rule "never `--admin`" is already
broken.

## OD-10 — Must tasks carry named acceptance tests?

**Default.** Yes for `feature` and `fix`, as a per-project policy that defaults on. This matches
the ready rules as they run and leaves the estate's open `DEC-ACCEPTANCE` decision free to turn
it off per project.

**If the default stands.** Nothing changes for the estate at cutover. The design record's
statement that tasks carry "no acceptance tests" is not implemented as a rule.

**Alternative.** Outcome only, verification left to workflows. Shorter tasks; it removes the
handle that sizing ("at most three tests") and scoped review hang on.

## OD-11 — Lanes for the SORTYARD board

**Default.** Raise SORTYARD from 2 to 3 lanes while the product is being built, taking the lane
from whichever project the owner ranks lowest.

**If the default stands.** The plan's lane time drops by about a third. Another project slows.

**Alternative.** Stay at 2. Nothing else changes; the estimate in
[13-milestones.md](13-milestones.md) is for 2 lanes.
