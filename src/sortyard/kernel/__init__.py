"""The workflow kernel (HARNESS-V3 section 3): work as durable workflows over a state table.

`states` loads and checks the state table; `item` is the one generic workflow that moves a work
item through it. `capabilities` loads a lane's capability file and `preflight` exercises a
task's needs against it before any build (section 3.3). `admission` lets an item in,
`scheduler` owns the queue, `observer` reports outside work and `store` keeps specs, gap items
and probe results in Postgres. The kernel reaches the workflow
engine only through `sortyard.engine`.
"""
