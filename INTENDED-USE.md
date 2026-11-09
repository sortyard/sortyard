# Intended use — Sortyard

Founder-owned statement (Joe Graham, 2026-11-06). This is the authority every
milestone and task in this project is shaped against; a premise that
contradicts it fails shaping (premise policy, 2026-11-06).

## What it is

Sortyard is the open-source harness reboot: our own delivery harness — the
conductor, the control plane, the task manager — rethought from first
principles as an open-source package anyone can deploy, with a UI for
everything for the operator and APIs for everything for agents. We dogfood it
to replace our current harness, without losing any of the control,
tunability and flexibility we have now.

Its load-bearing principles, from the design draft: no unbound agents (work
executes only through a verified Execution Binding — workflow, context,
skills, model, place, credentials, dependencies and a bounded resource
envelope); one source of truth per domain object, everything else a labelled
projection; the conductor an explicit, derivable state machine; advance only
on observed state, never on self-report.

## What it is not

Sortyard is not a rename or a fork of the current harness, and it is not a
second harness running alongside it: it replaces it, by cutover, starting
with its own backlog. It does not bundle or fork Plane — the board is native
to the console, Plane's concepts are taken, not its business shape
(reference-clone quarantine, premise policy 2026-11-06). Standing defaults
(Joe, 2026-11-06, until he objects): Apache-2.0 + DCO, no CLA; definition
edits via git PRs; Plane read-only projection for one milestone.
