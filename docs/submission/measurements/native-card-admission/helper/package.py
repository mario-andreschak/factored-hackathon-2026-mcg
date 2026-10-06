"""Copy only named evidence; record public derivatives without executing release helpers."""
from pathlib import Path
import argparse
import base64
import hashlib
import json
import re
import struct


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


SENSITIVE = {"machine_id", "machineId", "turn_id", "turnId", "pending_handle",
             "pendingHandle", "product_reference", "transaction_reference", "request_id",
             "cookie", "cookies", "storage_state", "storageState", "auth", "authorization",
             "headers", "demo_code", "api_key", "apiKey", "provider_key", "config",
             "private_binding", "binding", "bindingPath", "privateBindingPath"}


def scrub(value, changes):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in SENSITIVE:
                changes.append("Removed private/capability field: " + key)
            else:
                result[key] = scrub(item, changes)
        return result
    if isinstance(value, list):
        return [scrub(item, changes) for item in value]
    if isinstance(value, str):
        cleaned, count = re.subn(r"[A-Za-z]:[\\/](?:Users|Temp)[\\/][^\n\"']*", "[private-local-path]", value)
        if count:
            changes.append("Replaced identifying absolute local path")
        return cleaned
    return value


def register(root, original, destination, origin_label, transform=None):
    raw = original.read_bytes()
    data, changes = transform(raw) if transform else (raw, ["Identity; exact original bytes"])
    target = root / destination
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    manifest_path = root / "artifacts.json"
    manifest = read_json(manifest_path) if manifest_path.exists() else {"schema": "savia-card-admission-public-derivations/v1", "artifacts": []}
    manifest["artifacts"] = [row for row in manifest["artifacts"] if row["public"] != destination]
    manifest["artifacts"].append({"original": origin_label, "public": destination,
        "original_sha256": sha(raw), "public_sha256": sha(data),
        "original_bytes": len(raw), "public_bytes": len(data),
        "transformations": changes})
    manifest["artifacts"].sort(key=lambda row: row["public"])
    manifest_path.write_bytes(encoded(manifest))


def json_transform(raw):
    changes = []
    result = scrub(json.loads(raw.decode("utf-8-sig")), changes)
    return (encoded(result), ["JSON parsed and serialized as UTF-8 with two-space indentation and terminal LF"] + sorted(set(changes))) if changes else (raw, ["Identity; exact original bytes"])


def text_transform(raw):
    changed, count = re.subn(rb"[A-Za-z]:[\\/](?:Users|Temp)[\\/][^\r\n\"']*", b"[private-local-path]", raw)
    return changed, ["Replaced identifying absolute local path literals"] if count else ["Identity; exact original bytes"]


def seed(args):
    root, helper, offline = args.output, args.helper_root, args.offline_root
    ready = read_json(helper / "readiness.json")
    assert ready["source"] == "f2fa597a481a87b5301531cf180f8f61d1f3ba70"
    assert len(ready["helper_files"]) == 18 and len(ready["build_files"]) == 7
    for item in sorted(offline.iterdir()):
        assert item.is_file()
        register(root, item, "offline/" + item.name, "approved-offline/" + item.name)
    assert len(list(offline.iterdir())) == 16
    common = (helper / "release_common.py").read_bytes()
    match = re.search(rb"MACHINE\s*=\s*['\"]([^'\"]+)['\"]", common)
    assert match
    machine_id = match.group(1)

    def helper_transform(raw):
        changed = raw.replace(machine_id, b"[private-machine-id]")
        changes = []
        if changed != raw:
            changes.append("Replaced bound deployment machine ID literal with [private-machine-id]")
        # Literal source copies remain readable but deliberately lose private local bindings.
        replaced, count = re.subn(rb"[A-Za-z]:[\\/](?:Users|Temp)[\\/][^\r\n\"']*", b"[private-local-path]", changed)
        if count:
            changes.append("Replaced identifying absolute local path literals")
        return replaced, changes or ["Identity; exact original bytes"]

    for name, expected in sorted(ready["helper_files"].items()):
        source = helper / name
        assert sha(source.read_bytes()) == expected
        register(root, source, "release-helper/" + name, "release-helper/" + name,
                 json_transform if name.endswith(".json") else helper_transform)
    context = helper / "contexts/f2fa597a481a/build"
    for name, expected in sorted(ready["build_files"].items()):
        source = context / name
        assert sha(source.read_bytes()) == expected
        register(root, source, "build-context/" + name, "build-context/" + name,
                 json_transform if name.endswith(".json") else helper_transform)
    register(root, helper / "readiness.json", "release-helper/readiness.json", "release-helper/readiness.json", json_transform)
    register(root, context.parent / "preparation-receipt.json", "build-context/preparation-receipt.json", "build-context/preparation-receipt.json", json_transform)


def native(args):
    changes = []
    raw = args.input.read_bytes()
    events = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
    public_events = [scrub(event, changes) for event in events]
    derivative = b"".join((json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n").encode() for event in public_events)
    register(args.output, args.input, args.destination, args.origin,
             lambda data: (derivative, ["NDJSON parsed and serialized as compact UTF-8 with one terminal LF per event"] + sorted(set(changes))))
    audio = b"".join(base64.b64decode(event["data"], validate=True) for event in events if event.get("type") == "audio")
    starts = [event for event in events if event.get("type") == "start"]
    assert len(starts) == 1
    rate = starts[0]["sample_rate"]
    assert rate == 24000 and len(audio) % 2 == 0
    if audio:
        header = b"RIFF" + struct.pack("<I", 36 + len(audio)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
        wav = header + b"data" + struct.pack("<I", len(audio)) + audio
        wav_name = str(Path(args.destination).with_suffix(".wav")).replace("\\", "/")
        register(args.output, args.input, wav_name, args.origin, lambda data: (wav,
            ["Decoded original audio.data base64 chunks in event order; concatenated exact PCM bytes; wrapped mono 24000 Hz PCM16 little-endian WAV header",
             "PCM SHA256: " + sha(audio), "PCM samples: " + str(len(audio) // 2)]))


def seal(args):
    root = args.output
    rows = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path != root / "SHA256SUMS.txt":
            rows.append(sha(path.read_bytes()) + "  " + path.relative_to(root).as_posix())
    (root / "SHA256SUMS.txt").write_text("\n".join(rows) + "\n", encoding="ascii", newline="\n")
    print(json.dumps({"files": len(rows) + 1, "manifest_sha256": sha((root / "artifacts.json").read_bytes()), "sums_sha256": sha((root / "SHA256SUMS.txt").read_bytes())}))


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("mode", choices=["seed", "json", "text", "native", "seal"])
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--helper-root", type=Path)
parser.add_argument("--offline-root", type=Path)
parser.add_argument("--input", type=Path)
parser.add_argument("--destination")
parser.add_argument("--origin")
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
if args.mode == "seed":
    seed(args)
elif args.mode == "json":
    register(args.output, args.input, args.destination, args.origin, json_transform)
elif args.mode == "text":
    register(args.output, args.input, args.destination, args.origin, text_transform)
elif args.mode == "native":
    native(args)
else:
    seal(args)
