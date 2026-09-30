"""Validate retained full base layers and record observed local image identities."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

FLUJO = "51ff39fc5bac84cbbb49bbd2b21b5ab89de8b14b"
BANKING = "71ac0f020303abfd0073302a148752f0d2c9f23b"
CHECKPOINT = "banking-package-issue21/v2"
SAFE_RUNTIME_FIELDS = ("Cmd", "Entrypoint", "WorkingDir", "User", "Healthcheck")
PUBLIC_STOP_SIGNALS = frozenset(("", "SIGTERM", "15"))


def daemon_compatibility_observations(config: dict) -> dict:
    """Observe a small safe subset, without deciding OCI compatibility."""
    observations = {}
    for key in ("ArgsEscaped", "StopSignal", "Volumes"):
        if key not in config:
            observations[key] = {"type": "missing"}
            continue
        value = config[key]
        observation = {"type": type(value).__name__}
        if key == "ArgsEscaped":
            if value is None or type(value) is bool:
                observation["value"] = value
        elif key == "StopSignal":
            if value is None or (type(value) is str and value in PUBLIC_STOP_SIGNALS):
                observation["value"] = value
            else:
                observation["review"] = "unreviewed"
        elif value is None:
            observation["state"] = "null"
        elif type(value) in (dict, list):
            observation["state"] = "nonempty" if value else "empty"
            observation["count"] = len(value)
        else:
            observation["state"] = "unreviewed"
        observations[key] = observation
    return observations


def record(base: dict, final: dict, candidate: str) -> dict:
    expected = {"org.opencontainers.image.revision": FLUJO, "io.flujo.application.version": "3.46.1"}
    for image in [base, final]:
        labels = image["Config"]["Labels"]
        for key, value in expected.items():
            if labels.get(key) != value:
                raise ValueError(f"Image {key} mismatch")
        if "FLUJO_BUILD_REVISION=" + FLUJO not in image["Config"]["Env"]:
            raise ValueError("Image build revision env mismatch")
    if final["Config"]["Labels"].get("io.flujo.banking.source.revision") != BANKING:
        raise ValueError("Banking image source label mismatch")
    base_layers = base["RootFS"]["Layers"]
    final_layers = final["RootFS"]["Layers"]
    if not base_layers or final_layers[:len(base_layers)] != base_layers or len(final_layers) <= len(base_layers):
        raise ValueError("Final image must retain every exact full base layer and extend it")
    if final["Config"]["User"] != "node" or final["Config"]["Cmd"] != base["Config"]["Cmd"]:
        raise ValueError("Runtime user/launcher changed")
    if (final["Config"].get("Entrypoint") != base["Config"].get("Entrypoint")
            or final["Config"].get("WorkingDir") != base["Config"].get("WorkingDir")):
        raise ValueError("Runtime entrypoint/working directory changed")
    if final["Config"].get("Healthcheck") != base["Config"].get("Healthcheck"):
        raise ValueError("Runtime healthcheck changed")
    return {"schema": "banking-full-image-package/v2", "schema_version": 2,
        "checkpoint": CHECKPOINT, "candidateRevision": candidate,
        "flujoSourceRevision": FLUJO, "bankingSourceRevision": BANKING,
        "baseImageId": base["Id"], "finalImageId": final["Id"],
        "baseLayers": base_layers, "finalLayers": final_layers,
        "baseLayersRetained": True, "launcherRetained": True,
        "baseRuntime": {key: base["Config"].get(key) for key in SAFE_RUNTIME_FIELDS},
        "finalRuntime": {key: final["Config"].get(key) for key in SAFE_RUNTIME_FIELDS},
        "baseDaemonCompatibility": daemon_compatibility_observations(base["Config"]),
        "finalDaemonCompatibility": daemon_compatibility_observations(final["Config"]),
        "repoDigests": final.get("RepoDigests", []),
        "imageIdentityScope": "Docker daemon images only; not OCI config identity or archive Healthcheck preservation",
        "scope": "private packaging only; no deployment, model readiness or joined acceptance"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-inspect", type=Path, required=True)
    parser.add_argument("--final-inspect", type=Path, required=True)
    parser.add_argument("--candidate-revision", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    base, final = [json.loads(p.read_text())[0] for p in [args.base_inspect, args.final_inspect]]
    receipt = record(base, final, args.candidate_revision)
    args.out.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
