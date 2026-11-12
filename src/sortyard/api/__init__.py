"""The API service's REST surface (design §4: the only door; §7: service accounts).

- ``permissions`` — the §7 permission matrix in code: every routed operation of
  spec/openapi.json with the roles that may invoke it (tests hold it to the spec).
- ``auth`` — bearer tokens: service-account issuance (the create+claim refusal) and lookup.
- ``store`` — Postgres access over the §3 tables, with the AuditLog + event-ledger writes
  every mutation makes.
- ``handlers`` — one function per operation.
- ``http`` — request parsing, routing, authorization and problem responses.
"""
