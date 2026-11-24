# Estate canary, 2026-11-24 (SORTYARD-187, SORTYARD-178)

The Sortyard v3 kernel on the estate (namespace `sortyard` on aks-obs-01, Argo Application
`sortyard-kernel`, release in noncelogic/estate-gitops `sortyard-kernel/`) took two canary items
from admission to merged with no hand action. Each was admitted through the API by
estate-gitops `sortyard-kernel/canary.sh` (`POST /v1/workspaces/ws-estate/items` as the canary
operator, answered 201), which then only reads the item until it ends. The second survived its kernel pod being deleted
while it was building. Times are UTC. Every value below was read on 2026-11-24 from the
deployment, the registry, GitHub or the kernel's own event table.

## The deployment

| | |
|---|---|
| Sortyard commit | `bb90876e9184309b6e5b765f270862061ba1ffff` (PR #35) |
| Kernel image | `noncelogicci.azurecr.io/sortyard/sortyard@sha256:ee50792eab0311690d91dfc0a6eaf7154ed037888bf7d7aa63ea500249c82efa` (publish run 45469034112; the same digest read back from the registry for that commit's tag) |
| Worker image | `noncelogicci.azurecr.io/sortyard/walwarden-worker@sha256:a2b379c029b98a37b798f81713eb7279f1068e4c63ebdefdb3627a4ada3fd1a9`, built on the kernel image (its first nine layers are that image's) |
| Release | noncelogic/estate-gitops PR #6 (squash `c468803`). During both runs Argo was Synced and Healthy at `f173cc5`, the estate-gitops main that followed it (it holds `c468803`; the later commit is estate-gitops PR #2, a lane-move tool that does not change the release) |
| Removal | noncelogic/estate-gitops `sortyard-kernel/README.md`, section "Removing the deployment" |

## The defect the canary found first

The first item, `canary-20261124-a`, was built and its branch pushed, then the kernel failed
every ~16 s with `GitHub answered 422 to POST /repos/noncelogic/sortyard-canary/pulls:
Validation Failed`. GitHub's errors: `not all refs are readable`. The pull request token had
`pull_requests: write` only; GitHub also wants `contents: read` to open one. Fixed in PR #35;
the fake GitHub now refuses the same way. The item itself was then left in checking on a pull
request a diagnostic probe had opened and closed, waited out its limits into a 24 h need wait
(filed as SORTYARD-199), and was withdrawn by request. The canary was run again as new items.

## Item 1: `canary-20261124-b`

`sortyard-kernel/canary.sh canary-20261124-b`: `result: state merged, events caused by a
request: 0`, exit 0. Pull request https://github.com/noncelogic/sortyard-canary/pull/2, opened
and merged by the kernel's GitHub App (`noncelogic-conductor`), merge `8a90759`, check `check`
success, one file `notes/canary-20261124-b.txt`. Its head `1e52ef7` is the build Job's commit:
author `sortyard-worker`, 19:40:08, trailer `Co-Authored-By: Claude Sonnet 5.5`.

| At | From | To | Outcome |
|---|---|---|---|
| 19:39:33 | | admitted | |
| 19:39:34 | admitted | preflight | dispatched |
| 19:39:36 | preflight | building | ready |
| 19:40:34 | building | checking | built |
| 19:41:08 | checking | reviewing | green |
| 19:41:23 | reviewing | merging | approved |
| 19:41:28 | merging | merged | merged |

## Item 2: `canary-20261124-c`, the kernel pod deleted while it was building

The item entered building at 19:42:18. At 19:42:19 the kernel pod
`sortyard-kernel-588ff4fc7c-974sx` was deleted (`Killing: Stopping container kernel`
19:42:19). Its replacement `sortyard-kernel-588ff4fc7c-c22mx` started at 19:42:25 and logged
`serving lanes ['canary', 'walwarden']` at 19:42:26. The replacement observed the build done
at 19:42:43 and took the item to merged. `canary.sh`: `result: state merged, events caused by
a request: 0`, exit 0. Pull request https://github.com/noncelogic/sortyard-canary/pull/3,
opened and merged by `noncelogic-conductor`, merge `62a06c6`. Its head `a9cfdd3` is the build
Job's commit: author `sortyard-worker`, 19:42:25 (while no kernel was serving), trailer
`Co-Authored-By: Claude Sonnet 5.5`.

| At | From | To | Outcome |
|---|---|---|---|
| 19:42:16 | | admitted | |
| 19:42:16 | admitted | preflight | dispatched |
| 19:42:18 | preflight | building | ready |
| 19:42:43 | building | checking | built |
| 19:43:16 | checking | reviewing | green |
| 19:43:31 | reviewing | merging | approved |
| 19:43:36 | merging | merged | merged |

## The worker Jobs

Build and review ran as Jobs in namespace `sortyard-work` on k3s-azure-01, on the worker image
above. A Job's dispatch deletes the item's earlier Jobs, so the review Jobs are what was left
to read. A Job's `sortyard.dev/item` label is `sortyard.lane.worker.item_label` of the
workspace and item: `088c300152554525ab2cfca3` is `canary-20261124-b` and
`e03df39c29db7c47966c9331` is `canary-20261124-c` in `ws-estate`. The Jobs:
`sy-088c300152554525ab2cfca3-5` (19:41:08 to 19:41:20, item 1) and
`sy-e03df39c29db7c47966c9331-5` (19:43:16 to 19:43:28, item 2), both succeeded. The build
Jobs are gone; what they did is the head commits above, made by the worker with the model. Item 2's
review log ends with the model's reading of the change ("The change adds only
`notes/canary-20261124-c.txt` ... `./check.sh` exits 0. I found nothing to flag."), then
`{"verdict":"approve"}`.
