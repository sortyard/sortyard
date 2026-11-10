"""The shadow conductor (design draft §8 Phase 1; §4): Sortyard's claim logic in observe-only mode.

The shadow replicates the production conductor's input path — drive.py's board view,
plane_sync's register view of the board, the lane registry and the task_ready gating output —
strictly read-only, and for every production conductor pass records what it WOULD have
claimed, in what order, and what it would have refused with reason codes, as DecisionLog
entries in the event ledger. It never claims, merges, comments, or writes anywhere but its own
database: its entire output is evidence for the claim comparison (SORTYARD-9).

Modules:
  board     the canonical queue snapshot every input adapter produces, and its content hash
  sources   the read-only input adapters (board-view snapshot by file/URL; Plane REST)
  evaluate  the claim decision: a pure function over (snapshot, policy, lane state)
  ledger    writes one pass's decisions to the DecisionLog + event ledger, idempotently
"""
