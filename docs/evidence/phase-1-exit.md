# Phase 1 exit: Walwarden items admitted to merged with no hand action, 2026-11-25 (SORTYARD-180)

The phase 1 exit test of HARNESS-V3 (section 6, phase 1 "Kernel to merge") is: one Walwarden item
goes admitted to merged with no hand action, then 10 in a row. It was met on 2026-11-25 at
04:45:58Z (ledger time; GitHub's mergedAt is 04:45:57Z), when the eleventh consecutive hands-off
Walwarden item merged.

- **The first item:** WALWARDEN-177, merged 03:05:44Z.
- **The ten after it:** WALWARDEN-188 through WW-NAV-OVERLAY-TEST-SETTLES.
- **Breaks in the run:** none. No item in the run was ended by a request or an operator action, and
  none ended without merging.

## The run

All eleven items are on the estate kernel: namespace `sortyard` on aks-obs-01, workspace
`ws-estate`, project and lane `walwarden`.

- **How they reached the kernel:** 177 and 188 were admitted by the lane move (SORTYARD-179). The rest
  were filed through the SORTYARD-207 path (estate-gitops `sortyard-lane/file_item.py`, with
  `walwarden-file.sh` from 04:09Z).
- **Where the times come from:** the ledger (below). Pull request numbers and merge commits are from
  GitHub, and deploy runs from `deploy.yml` of noncelogic/walwarden. All were read on 2026-11-25.
- **Deploys:** a merge to `main` of noncelogic/walwarden deploys production. noncelogic/walwarden-context
  has no deployment (GitHub deployments API: 0).

| # | Item | Pull request | Admitted | Merged | Production deploy of the merge |
|---|---|---|---|---|---|
| 1 | WALWARDEN-177 | [noncelogic/walwarden#1167](https://github.com/noncelogic/walwarden/pull/1167) (`42ef2fc`) | 2026-11-25T03:03:34Z | 2026-11-25T03:05:44Z | 45537556238 success |
| 2 | WALWARDEN-188 | [noncelogic/walwarden#1168](https://github.com/noncelogic/walwarden/pull/1168) (`be06997`) | 2026-11-25T03:03:33Z | 2026-11-25T03:07:14Z | 45537732562 success |
| 3 | WW-PR-DEPLOY-GATE | [noncelogic/walwarden#1169](https://github.com/noncelogic/walwarden/pull/1169) (`d3fad9c`) | 2026-11-25T03:31:18Z | 2026-11-25T03:37:23Z | 45541250106 success |
| 4 | WW-MERGE-UNIT-ONLY | [noncelogic/walwarden-context#58](https://github.com/noncelogic/walwarden-context/pull/58) (`72d17fe`) | 2026-11-25T03:31:17Z | 2026-11-25T03:45:49Z | no deployment (gate1 / ci on main green) |
| 5 | WW-DEPLOY-QUEUE | [noncelogic/walwarden-context#59](https://github.com/noncelogic/walwarden-context/pull/59) (`0370d92`) | 2026-11-25T03:31:17Z | 2026-11-25T03:48:59Z | no deployment (ci on main green) |
| 6 | WW-DEPLOY-BATCH | [noncelogic/walwarden-context#60](https://github.com/noncelogic/walwarden-context/pull/60) (`4b46fa0`) | 2026-11-25T03:31:17Z | 2026-11-25T04:12:22Z | no deployment (ci on main green) |
| 7 | WW-CONTRACTS-AZURE-DEPLOY | [noncelogic/walwarden#1170](https://github.com/noncelogic/walwarden/pull/1170) (`b8d6d5c`) | 2026-11-25T04:09:38Z | 2026-11-25T04:17:00Z | 45545712867 success |
| 8 | WW-CONTRACTS-LIVE-WORKFLOWS | [noncelogic/walwarden#1171](https://github.com/noncelogic/walwarden/pull/1171) (`d25d953`) | 2026-11-25T04:09:38Z | 2026-11-25T04:23:12Z | 45546417693 success (live proof 04:51:20Z) |
| 9 | WW-CTX-CLI-TESTS | [noncelogic/walwarden-context#61](https://github.com/noncelogic/walwarden-context/pull/61) (`f2884a6`) | 2026-11-25T04:09:38Z | 2026-11-25T04:25:18Z | no deployment (ci on main green) |
| 10 | WW-CTX-SDK-SURFACE | [noncelogic/walwarden-context#62](https://github.com/noncelogic/walwarden-context/pull/62) (`11a41ee`) | 2026-11-25T04:09:38Z | 2026-11-25T04:32:04Z | no deployment (ci on main green) |
| 11 | WW-NAV-OVERLAY-TEST-SETTLES | [noncelogic/walwarden#1173](https://github.com/noncelogic/walwarden/pull/1173) (`4d8e535`) | 2026-11-25T04:09:39Z | 2026-11-25T04:45:58Z | 45549002910 cancelled while pending: superseded by the deploy of the next merge (9939241, run 45549233010, pending at 04:50Z); deploy.yml's queue keeps one pending run |

Six of the eleven went through review fix rounds, reviewing to fixing, with no person involved:
WW-PR-DEPLOY-GATE, WW-MERGE-UNIT-ONLY, WW-DEPLOY-BATCH, WW-CONTRACTS-AZURE-DEPLOY,
WW-CONTRACTS-LIVE-WORKFLOWS and WW-CTX-CLI-TESTS. SY-V3-PHASE1-EXIT allows that. Its must_allow
reads "items that went through fix rounds ... without a person".

## Report output

`kubectl -n sortyard exec deploy/sortyard-api -- sortyard-exit-report --workspace ws-estate --project walwarden --since 2026-11-24T23:00:00Z`,
run read-only at 04:47:55Z. The two items still open at that time were WW-UNIT-STALE-AFTER-RETIRE
and WW-PR-DEPLOY-GATE-RUNS. WW-PR-DEPLOY-GATE-RUNS merged at 04:48:01Z as walwarden#1174.

```
exit report: workspace ws-estate, project walwarden, ended in [2026-11-24T23:00:00+00:00, 2026-11-25T04:47:55.258317+00:00)

WALWARDEN-177: hands-off
  admitted 2026-11-25T03:03:34.429527Z
  merged   2026-11-25T03:05:44.856409Z
  from a request: no; operator action: no
  transitions (ts  from -> to  owner  cause):
    2026-11-25T03:03:34.429527Z  - -> admitted  scheduler  start
    2026-11-25T03:03:34.526560Z  admitted -> preflight  capability-checker  outcome  [outcome dispatched]
    2026-11-25T03:03:36.985108Z  preflight -> building  executor  outcome  [outcome ready]
    2026-11-25T03:04:53.008546Z  building -> checking  ci-adapter  outcome  [outcome built]
    2026-11-25T03:04:54.449353Z  checking -> reviewing  reviewer  outcome  [outcome green]
    2026-11-25T03:05:40.278354Z  reviewing -> merging  merge-adapter  outcome  [outcome approved]
    2026-11-25T03:05:44.856409Z  merging -> merged  -  outcome  [outcome merged]

WALWARDEN-188: hands-off
  admitted 2026-11-25T03:03:33.232980Z
  merged   2026-11-25T03:07:14.793799Z
  from a request: no; operator action: no
  transitions (ts  from -> to  owner  cause):
    2026-11-25T03:03:33.232980Z  - -> admitted  scheduler  start
    2026-11-25T03:03:33.331724Z  admitted -> preflight  capability-checker  outcome  [outcome dispatched]
    2026-11-25T03:03:35.932610Z  preflight -> building  executor  outcome  [outcome ready]
    2026-11-25T03:05:25.067186Z  building -> checking  ci-adapter  outcome  [outcome built]
    2026-11-25T03:05:26.360362Z  checking -> reviewing  reviewer  outcome  [outcome green]
    2026-11-25T03:06:55.641484Z  reviewing -> merging  merge-adapter  outcome  [outcome approved]
    2026-11-25T03:07:14.793799Z  merging -> merged  -  outcome  [outcome merged]

WW-PR-DEPLOY-GATE: hands-off
  admitted 2026-11-25T03:31:18.055972Z
  merged   2026-11-25T03:37:23.186244Z
  from a request: no; operator action: no
  transitions (ts  from -> to  owner  cause):
    2026-11-25T03:31:18.055972Z  - -> admitted  scheduler  start
    2026-11-25T03:31:18.151619Z  admitted -> preflight  capability-checker  outcome  [outcome dispatched]
    2026-11-25T03:31:20.461036Z  preflight -> building  executor  outcome  [outcome ready]
    2026-11-25T03:32:20.120260Z  building -> checking  ci-adapter  outcome  [outcome built]
    2026-11-25T03:32:21.470180Z  checking -> reviewing  reviewer  outcome  [outcome green]
    2026-11-25T03:33:09.210106Z  reviewing -> fixing  executor  outcome  [outcome findings]
    2026-11-25T03:36:16.993705Z  fixing -> checking  ci-adapter  outcome  [outcome fixed]
    2026-11-25T03:36:18.681757Z  checking -> reviewing  reviewer  outcome  [outcome green]
    2026-11-25T03:37:19.091197Z  reviewing -> merging  merge-adapter  outcome  [outcome approved]
    2026-11-25T03:37:23.186244Z  merging -> merged  -  outcome  [outcome merged]

WW-MERGE-UNIT-ONLY: hands-off
  admitted 2026-11-25T03:31:17.402276Z
  merged   2026-11-25T03:45:49.909353Z
  from a request: no; operator action: no
  transitions (ts  from -> to  owner  cause):
    2026-11-25T03:31:17.402276Z  - -> admitted  scheduler  start
    2026-11-25T03:31:17.528572Z  admitted -> preflight  capability-checker  outcome  [outcome dispatched]
    2026-11-25T03:31:19.988026Z  preflight -> building  executor  outcome  [outcome ready]
    2026-11-25T03:32:52.605434Z  building -> checking  ci-adapter  outcome  [outcome built]
    2026-11-25T03:33:58.562058Z  checking -> reviewing  reviewer  outcome  [outcome green]
    2026-11-25T03:36:32.082869Z  reviewing -> fixing  executor  outcome  [outcome findings]
    2026-11-25T03:37:18.933756Z  fixing -> checking  ci-adapter  outcome  [outcome fixed]
    2026-11-25T03:38:25.033857Z  checking -> reviewing  reviewer  outcome  [outcome green]
    2026-11-25T03:40:11.010610Z  reviewing -> fixing  executor  outcome  [outcome findings]
    2026-11-25T03:41:12.570286Z  fixing -> checking  ci-adapter  outcome  [outcome fixed]
    2026-11-25T03:44:29.871679Z  checking -> reviewing  reviewer  outcome  [outcome green]
    2026-11-25T03:45:45.696543Z  reviewing -> merging  merge-adapter  outcome  [outcome approved]
    2026-11-25T03:45:49.909353Z  merging -> merged  -  outcome  [outcome merged]

WW-DEPLOY-QUEUE: hands-off
  admitted 2026-11-25T03:31:17.631312Z
  merged   2026-11-25T03:48:59.595697Z
  from a request: no; operator action: no
  transitions (ts  from -> to  owner  cause):
    2026-11-25T03:31:17.631312Z  - -> admitted  scheduler  start
    2026-11-25T03:46:00.840248Z  admitted -> preflight  capability-checker  outcome  [outcome dispatched]
    2026-11-25T03:46:03.221626Z  preflight -> building  executor  outcome  [outcome ready]
    2026-11-25T03:47:03.251384Z  building -> checking  ci-adapter  outcome  [outcome built]
    2026-11-25T03:48:25.390203Z  checking -> reviewing  reviewer  outcome  [outcome green]
    2026-11-25T03:48:55.630844Z  reviewing -> merging  merge-adapter  outcome  [outcome approved]
    2026-11-25T03:48:59.595697Z  merging -> merged  -  outcome  [outcome merged]

WW-DEPLOY-BATCH: hands-off
  admitted 2026-11-25T03:31:17.837240Z
  merged   2026-11-25T04:12:22.927168Z
  from a request: no; operator action: no
  transitions (ts  from -> to  owner  cause):
    2026-11-25T03:31:17.837240Z  - -> admitted  scheduler  start
    2026-11-25T03:49:10.729195Z  admitted -> preflight  capability-checker  outcome  [outcome dispatched]
    2026-11-25T03:49:13.246642Z  preflight -> building  executor  outcome  [outcome ready]
    2026-11-25T03:50:13.138600Z  building -> checking  ci-adapter  outcome  [outcome built]
    2026-11-25T03:52:57.066320Z  checking -> fixing  executor  outcome  [outcome red]
    2026-11-25T03:53:43.489272Z  fixing -> checking  ci-adapter  outcome  [outcome fixed]
    2026-11-25T03:58:22.812243Z  checking -> fixing  executor  outcome  [outcome red]
    2026-11-25T03:58:22.859826Z  fixing -> decision  decision-service  limit
    2026-11-25T03:58:22.960620Z  decision -> fixing  executor  decision  [decided by table]
    2026-11-25T03:59:09.092704Z  fixing -> checking  ci-adapter  outcome  [outcome fixed]
    2026-11-25T04:03:48.869812Z  checking -> reviewing  reviewer  outcome  [outcome green]
    2026-11-25T04:04:19.596058Z  reviewing -> fixing  executor  outcome  [outcome findings]
    2026-11-25T04:05:06.189718Z  fixing -> checking  ci-adapter  outcome  [outcome fixed]
    2026-11-25T04:06:28.969691Z  checking -> reviewing  reviewer  outcome  [outcome green]
    2026-11-25T04:07:44.401039Z  reviewing -> fixing  executor  outcome  [outcome findings]
    2026-11-25T04:09:01.490219Z  fixing -> checking  ci-adapter  outcome  [outcome fixed]
    2026-11-25T04:11:15.459711Z  checking -> reviewing  reviewer  outcome  [outcome green]
    2026-11-25T04:12:18.582360Z  reviewing -> merging  merge-adapter  outcome  [outcome approved]
    2026-11-25T04:12:22.927168Z  merging -> merged  -  outcome  [outcome merged]

WW-CONTRACTS-AZURE-DEPLOY: hands-off
  admitted 2026-11-25T04:09:38.112537Z
  merged   2026-11-25T04:17:00.513568Z
  from a request: no; operator action: no
  transitions (ts  from -> to  owner  cause):
    2026-11-25T04:09:38.112537Z  - -> admitted  scheduler  start
    2026-11-25T04:09:38.224220Z  admitted -> preflight  capability-checker  outcome  [outcome dispatched]
    2026-11-25T04:09:40.971600Z  preflight -> building  executor  outcome  [outcome ready]
    2026-11-25T04:11:32.534140Z  building -> checking  ci-adapter  outcome  [outcome built]
    2026-11-25T04:11:33.638704Z  checking -> reviewing  reviewer  outcome  [outcome green]
    2026-11-25T04:13:04.423138Z  reviewing -> fixing  executor  outcome  [outcome findings]
    2026-11-25T04:15:22.976267Z  fixing -> checking  ci-adapter  outcome  [outcome fixed]
    2026-11-25T04:15:24.292767Z  checking -> reviewing  reviewer  outcome  [outcome green]
    2026-11-25T04:16:56.318921Z  reviewing -> merging  merge-adapter  outcome  [outcome approved]
    2026-11-25T04:17:00.513568Z  merging -> merged  -  outcome  [outcome merged]

WW-CONTRACTS-LIVE-WORKFLOWS: hands-off
  admitted 2026-11-25T04:09:38.321311Z
  merged   2026-11-25T04:23:12.335183Z
  from a request: no; operator action: no
  transitions (ts  from -> to  owner  cause):
    2026-11-25T04:09:38.321311Z  - -> admitted  scheduler  start
    2026-11-25T04:12:33.929394Z  admitted -> preflight  capability-checker  outcome  [outcome dispatched]
    2026-11-25T04:12:36.416694Z  preflight -> building  executor  outcome  [outcome ready]
    2026-11-25T04:16:41.070058Z  building -> checking  ci-adapter  outcome  [outcome built]
    2026-11-25T04:16:42.113161Z  checking -> reviewing  reviewer  outcome  [outcome green]
    2026-11-25T04:17:27.335194Z  reviewing -> fixing  executor  outcome  [outcome findings]
    2026-11-25T04:19:55.609441Z  fixing -> checking  ci-adapter  outcome  [outcome fixed]
    2026-11-25T04:19:56.755709Z  checking -> reviewing  reviewer  outcome  [outcome green]
    2026-11-25T04:21:12.887882Z  reviewing -> merging  merge-adapter  outcome  [outcome approved]
    2026-11-25T04:21:13.986301Z  merging -> fixing  executor  outcome  [outcome conflict]
    2026-11-25T04:22:17.226499Z  fixing -> checking  ci-adapter  outcome  [outcome fixed]
    2026-11-25T04:22:18.568778Z  checking -> reviewing  reviewer  outcome  [outcome green]
    2026-11-25T04:23:07.579517Z  reviewing -> merging  merge-adapter  outcome  [outcome approved]
    2026-11-25T04:23:12.335183Z  merging -> merged  -  outcome  [outcome merged]

WW-CTX-CLI-TESTS: hands-off
  admitted 2026-11-25T04:09:38.568875Z
  merged   2026-11-25T04:25:18.047571Z
  from a request: no; operator action: no
  transitions (ts  from -> to  owner  cause):
    2026-11-25T04:09:38.568875Z  - -> admitted  scheduler  start
    2026-11-25T04:17:11.692644Z  admitted -> preflight  capability-checker  outcome  [outcome dispatched]
    2026-11-25T04:17:13.942821Z  preflight -> building  executor  outcome  [outcome ready]
    2026-11-25T04:18:15.062920Z  building -> checking  ci-adapter  outcome  [outcome built]
    2026-11-25T04:19:56.679547Z  checking -> reviewing  reviewer  outcome  [outcome green]
    2026-11-25T04:21:13.092037Z  reviewing -> fixing  executor  outcome  [outcome findings]
    2026-11-25T04:22:00.827690Z  fixing -> checking  ci-adapter  outcome  [outcome fixed]
    2026-11-25T04:23:57.921276Z  checking -> reviewing  reviewer  outcome  [outcome green]
    2026-11-25T04:25:13.975299Z  reviewing -> merging  merge-adapter  outcome  [outcome approved]
    2026-11-25T04:25:18.047571Z  merging -> merged  -  outcome  [outcome merged]

WW-CTX-SDK-SURFACE: hands-off
  admitted 2026-11-25T04:09:38.775041Z
  merged   2026-11-25T04:32:04.316085Z
  from a request: no; operator action: no
  transitions (ts  from -> to  owner  cause):
    2026-11-25T04:09:38.775041Z  - -> admitted  scheduler  start
    2026-11-25T04:23:25.241848Z  admitted -> preflight  capability-checker  outcome  [outcome dispatched]
    2026-11-25T04:23:27.415411Z  preflight -> building  executor  outcome  [outcome ready]
    2026-11-25T04:25:16.297071Z  building -> checking  ci-adapter  outcome  [outcome built]
    2026-11-25T04:27:11.663197Z  checking -> reviewing  reviewer  outcome  [outcome green]
    2026-11-25T04:30:40.171745Z  reviewing -> merging  merge-adapter  outcome  [outcome approved]
    2026-11-25T04:32:04.316085Z  merging -> merged  -  outcome  [outcome merged]

WW-NAV-OVERLAY-TEST-SETTLES: hands-off
  admitted 2026-11-25T04:09:39.003934Z
  merged   2026-11-25T04:45:58.414818Z
  from a request: no; operator action: no
  transitions (ts  from -> to  owner  cause):
    2026-11-25T04:09:39.003934Z  - -> admitted  scheduler  start
    2026-11-25T04:25:32.844789Z  admitted -> preflight  capability-checker  outcome  [outcome dispatched]
    2026-11-25T04:25:35.066033Z  preflight -> building  executor  outcome  [outcome ready]
    2026-11-25T04:45:08.673550Z  building -> checking  ci-adapter  outcome  [outcome built]
    2026-11-25T04:45:09.982211Z  checking -> reviewing  reviewer  outcome  [outcome green]
    2026-11-25T04:45:54.588601Z  reviewing -> merging  merge-adapter  outcome  [outcome approved]
    2026-11-25T04:45:58.414818Z  merging -> merged  -  outcome  [outcome merged]

merged: 11; hands-off: 11; ended without merging: 0; still open: 2
longest run of merged items with no request and no operator action: 11 (WALWARDEN-177, WALWARDEN-188, WW-PR-DEPLOY-GATE, WW-MERGE-UNIT-ONLY, WW-DEPLOY-QUEUE, WW-DEPLOY-BATCH, WW-CONTRACTS-AZURE-DEPLOY, WW-CONTRACTS-LIVE-WORKFLOWS, WW-CTX-CLI-TESTS, WW-CTX-SDK-SURFACE, WW-NAV-OVERLAY-TEST-SETTLES)
```

## What this does not show

- **Untested merges on noncelogic/walwarden.** Its lane declares no pull-request check (`checks = []`).
  The kernel therefore merges a walwarden pull request after its own review only, and the merge
  deploys production.
  - `pr-deploy-gate` was added by WW-PR-DEPLOY-GATE (#1169), but it could not run until
    WW-PR-DEPLOY-GATE-RUNS (#1174): its runner group is restricted to `deploy.yml@main`.
  - Making the lane wait for it is SORTYARD-236.
  - The run above includes walwarden#1168, which left a unit test (`sentryFlush.test.ts`) out of
    date. No check runs `npm test` on pull requests. WW-UNIT-STALE-AFTER-RETIRE repairs that test.
- **Deploys still running.** The deploys of the last walwarden merges were in progress or pending
  when this was written (see the table). They are recorded on SORTYARD-180 when they finish.
