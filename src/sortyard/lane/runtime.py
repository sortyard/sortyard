"""The lane runtime: every owner of the shipped table, and how each one's work is observed.

`build` puts the pieces of a lane together on one database, one GitHub port and one jobs port
(HARNESS-V3 section 6, phase 1): the scheduler, the preflight with its probes and its gap
registry and result sink in Postgres, the worker launcher, the ci-adapter and the
merge-adapter, the decision policy and the ledger recorder. Each owner finds an item's lane,
repository, base branch, needs and spec in what admission stored. The result registers on an
engine worker (`Runtime.register`, which refuses a table owner it has no function for) and
gives the observer its looks (`Runtime.observer`).

Three things happen here that no single adapter owns:

- **The pull request.** When a build or a fix is observed as done and the item's branch has no
  open pull request, the runtime opens one, with the item's title and a body naming the item,
  before the outcome is sent. Finding it first, and looking again when GitHub refuses the
  create, keeps that to one pull request however often it runs.
- **A wait that closed while no one was told.** The need's look asks the gap registry whether
  every gap item the item waits on has closed, so an item whose `closed` was lost (the service
  stopped between closing the gap item and telling the item) still returns to preflight.
- **An item that ends without merging** (withdrawn). The record step itself cleans up, since
  a terminal state has no owner and no open stay for the observer to see: it records the
  transition, naming the item's branch and its open pull request (which is left open), then
  deletes every Job of the item with its per-job secret. The engine retries that step until it
  succeeds, across restarts, and both halves are safe to repeat.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sortyard.engine import Engine, Registry
from sortyard.kernel import policy as policies
from sortyard.kernel.capabilities import REPOSITORY, Lane
from sortyard.kernel.item import Decide, Owner, Payload, Record, register
from sortyard.kernel.ledger import Ledger
from sortyard.kernel.observer import Look, Observer
from sortyard.kernel.preflight import NEED_OWNER, Preflight, Probe, TaskNeeds
from sortyard.kernel.scheduler import SCHEDULER_OWNER, Scheduler
from sortyard.kernel.states import StateTable
from sortyard.kernel.store import Connect, Items, ItemSpec, PgGapRegistry
from sortyard.lane import worker
from sortyard.lane.github import (
    CI_OWNER,
    MERGE_OWNER,
    CiAdapter,
    GitHub,
    GitHubError,
    MergeAdapter,
    RepositoryProbe,
    Target,
    branch_of,
)
from sortyard.lane.jobs import Jobs
from sortyard.lane.worker import EXECUTOR_OWNER, REVIEWER_OWNER, Launcher, Work, WorkerConfig
from sortyard.lane.worker import probes as worker_probes

# The outcomes of a worker that mean a change is on the item's branch.
PUSHED = frozenset({"built", "fixed"})


def ensure_pull(port: GitHub, spec: ItemSpec) -> None:
    """Open the item's pull request unless its branch has one that is open or merged."""
    token = port.token(spec.repository, {"pull_requests": "write"})
    branch = branch_of(spec.item)

    def there() -> bool:
        found = port.find_pull(token, spec.repository, branch)
        return found is not None and (found.open or found.merged)

    if there():
        return
    body = f"Sortyard item {spec.item}.\n\n{spec.spec.get('outcome', '')}\n"
    try:
        port.open_pull(
            token, spec.repository, branch=branch, base=spec.base, title=spec.title, body=body
        )
    except GitHubError as error:
        # Refused because another pass opened it a moment ago: then it is there now.
        if error.status != 422 or not there():
            raise


@dataclass(frozen=True)
class Runtime:
    """The owners, looks, decision step and recorder of one kernel service."""

    owners: Mapping[str, Owner]
    looks: Mapping[str, Look]
    decide: Decide
    record: Record
    items: Items
    gaps: PgGapRegistry
    table: StateTable | None = None

    def register(self, registry: Registry) -> None:
        register(
            registry, owners=self.owners, decide=self.decide, record=self.record, table=self.table
        )

    def observer(self, engine: Engine) -> Observer:
        return Observer(engine, self.items.open_stays, self.looks)


def build(
    *,
    connect: Connect,
    lanes: Mapping[str, Lane],
    github: GitHub,
    jobs: Jobs,
    config: WorkerConfig,
    probes: Mapping[str, Probe],
    policy: policies.Policy | None = None,
    clock: Callable[[], float] = time.time,
    table: StateTable | None = None,
) -> Runtime:
    """`probes` gives the probes this module cannot make: the runner pool's, and any that
    replaces the repository, secret, service or worker-image probe of the two ports."""
    items, gaps = Items(connect), PgGapRegistry(connect)

    def lane_of(spec: ItemSpec) -> Lane:
        return lanes[spec.lane]

    def needs(tenant: str, item: str) -> TaskNeeds:
        spec = items.spec(tenant, item)
        return TaskNeeds(lane_of(spec), spec.needs)

    def work(tenant: str, item: str) -> Work:
        spec = items.spec(tenant, item)
        return Work(lane_of(spec), spec.repository, spec.spec, spec.base)

    def target(tenant: str, item: str) -> Target:
        spec = items.spec(tenant, item)
        declared = lane_of(spec).repositories[spec.repository]
        return Target(spec.repository, spec.base, declared.workflow_files, declared.checks)

    preflight = Preflight(
        lookup=needs,
        probes={REPOSITORY: RepositoryProbe(github), **worker_probes(jobs, config), **probes},
        gaps=gaps,
        sink=items.record_probe,
    )
    launcher = Launcher(
        jobs=jobs,
        lookup=work,
        tokens=lambda repository, permissions: github.token(repository, permissions).value,
        config=config,
        clock=clock,
    )
    scheduler = Scheduler(connect, lanes, table)
    ci, merge = CiAdapter(github, target), MergeAdapter(github, target)

    def worked(stay: Payload) -> Payload | None:
        reply = launcher.observe(stay)
        if reply is not None and reply["outcome"] in PUSHED:
            ensure_pull(github, items.spec(str(stay["tenant"]), str(stay["item"])))
        return reply

    def waited(stay: Payload) -> Payload | None:
        return preflight.wait({**stay, "action": None})

    looks: dict[str, Look] = {
        SCHEDULER_OWNER: scheduler,
        NEED_OWNER: waited,
        EXECUTOR_OWNER: worked,
        REVIEWER_OWNER: launcher.observe,
        CI_OWNER: lambda stay: ci.observe(stay).reply(),
        MERGE_OWNER: lambda stay: merge.observe(stay).reply(),
    }
    owners: dict[str, Owner] = {
        SCHEDULER_OWNER: scheduler,
        **preflight.owners(),
        **launcher.owners(),
        CI_OWNER: ci,
        MERGE_OWNER: merge,
    }
    ledger = Ledger(connect)

    def record(transition: Payload) -> None:
        if transition["state_kind"] != "terminal" or transition.get("lifecycle") == "merged":
            return ledger.record(transition)
        tenant, item = str(transition["tenant"]), str(transition["item"])
        spec, branch = items.spec(tenant, item), branch_of(item)
        try:
            token = github.token(spec.repository, {"pull_requests": "read"})
            found = github.find_pull(token, spec.repository, branch)
            pull: Any = found.number if found is not None and found.open else None
        except GitHubError as error:  # the item ends all the same; the record says why not
            pull = f"not read: {error}"
        left = {"repository": spec.repository, "branch": branch, "pull_request": pull}
        ledger.record({**transition, "detail": {**transition["detail"], "left_open": left}})
        gaps.settle(tenant, item)  # it waits on no capability-gap item any more
        jobs.delete_earlier(worker.item_label(tenant, item), 2**31)

    decide: Any = (policy or policies.shipped()).decide
    return Runtime(owners, looks, decide, record, items, gaps, table)
