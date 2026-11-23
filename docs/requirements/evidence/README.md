# Real local Appwrite2.6.1 primitive qualification

The [sanitized receipt](appwrite-qualification.json) records actual disposable-replica results.
All calls used synthetic users/projects on localhost. No deployed Appwrite data, credentials,
settings or existing Docker volumes were used. The owned Compose resources were removed and
synthetic private files deleted. The detailed runners, image identities, raw sanitized results
and failed fixture diagnostics are retained at
`~/artifacts/sortyard-requirements-consolidation/appwrite-proof/`.

Passed constructions:

- Six same-task contenders with capacity6: one committed, five bound failures; one matching
  chain, event, audit and receipt, occupancy1.
- Six distinct tasks competing for capacity1: one winner, no orphan records.
- Forced event collision rolled back task state and receipt.
- Twenty-four immutable-writer checks: direct PATCH/DELETE, transactional update/delete/upsert,
  table grants and row-security changes were denied, including malicious creator row grants.
- Runtime used a non-admin service-user session with table read/create and rowSecurity=false
  for immutable records; no runtime API key.
- Stale-owner revision fencing preserved the new owner and emitted no stale release event.
- Committed-transaction status/receipt recovery and scratch command-hash dedup prevented repeat
  writes and refused conflicting payload reuse.
- Session/JWT worked; a different Appwrite project with coincident user IDs rejected session,
  JWT and project key. Revoking the session invalidated both session and derived JWT.

Actual bound failures returned400 `attribute_limit_exceeded`; the Sortyard adapter must map the
classified provider error into its domain conflict/refusal. A repeated committed transaction
also returned400, with committed status and receipt available for recovery.

This qualifies primitives, not a shipped Sortyard adapter, end-to-end domain collaborator/
delegation isolation, complete lease recovery, credential renewal, physical socket-loss/process-
crash recovery, upgrade behavior or production migration. The lost-response construction
intentionally discarded a response; it did not inject a network fault. Failed nullable/input
fixture runs were retained and corrected without relaxing the invariant assertions.

Remaining acceptance is linked to SUB-001 to SUB-004, IAM/AGT and the implementation slices.
