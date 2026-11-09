# Sortyard — decision records

Decisions live here as records, not as prose inside other documents (premise policy: a premise that matters gets a decision record with an owner and a date).

## SY-DEC-001 — Tech stack (2026-11-07, decided by Joe)

- **Question:** implementation language(s) for the Sortyard backend.
- **Decision:** Python backend (one codebase; the six services as separate entry points; all-in-one single-pod profile for small installs, split services for larger ones). Console in TypeScript + React (Vite SPA, static files served by the API service). Postgres is the only database (state, event ledger, work queue — no Redis, no message broker). Data models generated from the Phase 0 JSON Schemas, so schema and implementation cannot drift. Strict typing enforced. Helm chart deployment; workers are language-agnostic Kubernetes Jobs.
- **Alternative considered:** Go backend. Rejected for v1: the working conductor/dispatcher logic is Python (thousands of proven lines), and Phase 1's shadow-mode comparison against the old conductor is only meaningful if the port stays close to the original; a rewrite risks silent behaviour drift in a language the estate doesn't use. Go's install-story advantages don't outweigh port fidelity for v1; revisit only if install weight demonstrably bites.
- **Source:** Sortyard design draft v6 §4a (~/workspace/harness-reboot/HARNESS-REBOOT-DRAFT-v6.md).
