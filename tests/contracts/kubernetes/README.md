# Kubernetes contract fragment

`openapi.json` is a fragment of the Kubernetes OpenAPI (Swagger 2.0) document, cut by
`extract.py` in this directory. The jobs port (`src/sortyard/lane/jobs.py`) and its fake
(`tests/fake_jobs.py`) are held to it by `tests/test_jobs_contract.py`.

- Source: <https://raw.githubusercontent.com/kubernetes/kubernetes/v1.31.4/api/openapi-spec/swagger.json>
- Version: Kubernetes v1.31.4 (the version the local replica is tested with).
- Contents: the nine operations the port uses (create, read and delete a batch/v1 Job; create
  and delete a core/v1 ConfigMap; create, read and delete a core/v1 Secret; list core/v1 Pods)
  with their parameters resolved, and every definition those operations reach.
- Changes: `description` texts are dropped. Nothing else is edited.

To refresh it, download the document for the new version, set `VERSION` in `extract.py`, and
run `python tests/contracts/kubernetes/extract.py path/to/swagger.json`.

Two things the port relies on are not in that document, so the fake states them itself:

- Error answers (404, 409, 403, 422) are a `meta/v1 Status`. The document lists only the
  success responses of each operation; the Status shape is in the fragment and errors are held
  to it. Reference:
  <https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.31/#status-v1-meta>
- A read with `Accept: application/json;as=PartialObjectMetadata;g=meta.k8s.io;v=v1` answers
  the object's metadata only (`apiVersion`, `kind: PartialObjectMetadata`, `metadata`). The
  port reads Secrets this way so that it never receives their data. The type is
  `PartialObjectMetadata` in
  <https://github.com/kubernetes/apimachinery/blob/v0.31.4/pkg/apis/meta/v1/types.go>; its
  schema here is composed from the fragment's `ObjectMeta`.

The fake holds bodies more strictly than the published schemas do: a field a schema does not
name is refused, so a misspelt field in a manifest fails a test.
