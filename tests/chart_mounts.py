"""What a rendered container would see, put on disk: its mounted files and its environment.

`as_started` takes a workload of a `helm template` render and gives the environment its
container starts with, with every mounted ConfigMap and Secret written under a directory of the
test's and every path in the environment pointing there. A service's own settings loader can
then read exactly what the chart would hand it. Secrets are not in a render: the test supplies
the content of each one the workload refers to, and a reference to one it did not supply fails.
"""

from __future__ import annotations

import pathlib
from collections.abc import Mapping
from typing import Any

Manifest = dict[str, Any]
Secrets = Mapping[str, Mapping[str, str]]


def named(docs: list[Manifest], kind: str, name: str) -> Manifest:
    (doc,) = [d for d in docs if d["kind"] == kind and d["metadata"]["name"] == name]
    return doc


def container_of(workload: Manifest, name: str) -> Manifest:
    pod = workload["spec"]["template"]["spec"]
    every: list[Manifest] = [*pod.get("initContainers", []), *pod["containers"]]
    (container,) = [each for each in every if each["name"] == name]
    return container


def as_started(
    docs: list[Manifest],
    workload: Manifest,
    container: str,
    root: pathlib.Path,
    secrets: Secrets,
) -> dict[str, str]:
    """The container's environment, its volumes written under `root`."""
    pod, made = workload["spec"]["template"]["spec"], container_of(workload, container)
    volumes = {volume["name"]: volume for volume in pod.get("volumes", [])}
    at: dict[str, pathlib.Path] = {}
    for mount in made.get("volumeMounts", []):
        volume = volumes[mount["name"]]
        directory = at[mount["mountPath"]] = root / container / mount["name"]
        directory.mkdir(parents=True, exist_ok=True)
        if "configMap" in volume:
            source = volume["configMap"]
            files: Mapping[str, str] = named(docs, "ConfigMap", source["name"])["data"]
        elif "secret" in volume:
            source = volume["secret"]
            files = secrets[source["secretName"]]
        else:
            assert "emptyDir" in volume, volume
            continue
        assert source.get("optional") is not True, f"{mount['name']} is optional"
        items = source.get("items") or [{"key": key, "path": key} for key in files]
        for item in items:
            target = directory / item["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(files[item["key"]])
    env: dict[str, str] = {}
    for entry in made.get("env", []):
        if "valueFrom" in entry:
            ref = entry["valueFrom"]["secretKeyRef"]
            assert ref.get("optional") is not True, f"{entry['name']} is optional"
            env[entry["name"]] = secrets[ref["name"]][ref["key"]]
            continue
        value = str(entry["value"])
        under = [path for path in at if value == path or value.startswith(path + "/")]
        if under:
            path = max(under, key=len)
            value = str(at[path]) + value[len(path) :]
        env[entry["name"]] = value
    return env
