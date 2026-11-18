# Checkout flywheel qualification

The checkout incident went through the real Ranker and Closer HTTP services on localhost. Both
used Postgres 17 with their own migrations. The running harness revision's policy store and resolver
ran against an isolated database. The consumer resolved the opted-in policy from the store and used
that version to select the retry strategy. No production assignment was created.

1. Ranker captured the sanitized `DEVOPS-184` fixture and retained its content hash. We seeded two
   candidate items and a comparison rubric in Ranker's qualification database because this Ranker
   revision does not serve the classification routes. The capture, score and top-N calls used its
   HTTP API. Ranker ranked owner-first first, with score 5 versus 4 under the declared rubric.
2. Closer accepted a commitment to reduce retries with unchanged independent verification and
   unrelated progress. The policy store resolved version 1 for the baseline, then version 3 for
   the opted-in run after the candidate edit and local promotion. Decision receipts name the
   policy used. A separate project received no policy binding.
3. Owner-first issued zero retry commands versus one in the baseline. Independent checks verified
   the affected repo at simulation tick 20 and the unrelated repo at tick 1 in both runs. The later
   observation was the same in both arms, so the demonstrated effect is one avoided command on this fixture.
   The observed recovery time was unchanged.
4. Closer closed from the verified outcome event and deduplicated redelivery. Ranker captured the
   measured outcome, linked to the initial evidence and the Closer loop. After restarting both
   HTTP processes, the ranked view matched, Closer's persisted loop remained closed, and the
   feedback bytes matched their stored hash.

The [proof receipt](checkout-flywheel.json) includes the source revisions, policy history, ranking,
closure event and restart readback. Ranker used a filesystem object-store adapter in this run.
The experiment did not exercise shared cluster rollout or S3-compatible storage.

## Shared deployment findings

Neither service had a Deployment or Service in the inspected `aks-obs-01` or harness clusters, or
an installed Argo Application in the inspected estate project. Both have source manifests for the
estate. Image publication jobs remain outstanding ([Ranker publish][ranker-ci], [Closer publish][closer-ci]).

Ranker loads API keys at boot, but its [request router][ranker] does not apply the service's declared
per-principal operation scopes to capture, score, or top-N. Its shared service needs a reviewed
request authorization implementation before it is admitted. Closer's [image workflow][closer]
requires four registry and OpenBao configuration variables. Neither its repository variable list
nor the matching organization variable names supplied them, and its target GHCR package was not
visible through the inspected identity. The estate needs the existing scoped publisher setup and
an available immutable image before syncing its overlay. Production adoption remains pending a
qualified installation and a scoped, opted-in policy assignment.

[ranker-ci]: https://github.com/noncelogic/corpus-ranker/actions/runs/44232728109
[closer-ci]: https://github.com/noncelogic/loop-closer/actions/runs/44230701889
[ranker]: https://github.com/noncelogic/corpus-ranker/blob/b8abc1043a8f6afedc1346ea97eb7cf9450cff11/src/server.ts
[closer]: https://github.com/noncelogic/loop-closer/blob/565ffdd71b281874550c055ce37fc9ff302a0aa4/.github/workflows/estate-image.yml
