# GitHub REST API: the vendored fragment

`fragment.json` is cut from GitHub's published OpenAPI description of its REST API. The fake
GitHub (`tests/fake_github.py`) and the HTTP client (`src/sortyard/lane/github.py`) are both
held to it by `tests/test_github_contract.py`.

- Source: <https://github.com/github/rest-api-description>
- File: `descriptions/api.github.com/api.github.com.json`
- Commit: `c9c95fe34ced05fe076001f5c55704742bc8e7f8` (read 2026-11-23)
- Description version: `1.1.4` (OpenAPI 3.0.3); the client sends `X-GitHub-Api-Version: 2022-11-28`

What is kept: for each operation the port calls (the `OPERATIONS` list in `extract.py`), its
parameters, its request body schema and its response schemas, and every component schema those
refer to. Schemas are as published, except that descriptions and examples are dropped.

To refresh, download the file at a newer commit and run:

```sh
python tests/contracts/github/extract.py api.github.com.json <commit>
```

Then update the commit above. A port call to a new endpoint needs its operation added to
`OPERATIONS` first: the fake refuses a call the fragment does not document.
