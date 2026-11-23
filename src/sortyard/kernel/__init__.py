"""The workflow kernel (HARNESS-V3 section 3): work as durable workflows over a state table.

`states` loads and checks the state table; `item` is the one generic workflow that moves a work
item through it. The kernel reaches the workflow engine only through `sortyard.engine`.
"""
