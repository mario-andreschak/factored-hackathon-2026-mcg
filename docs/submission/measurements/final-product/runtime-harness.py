"""Read-only, credential-free source/config proof of an exact running image."""
from pathlib import Path
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument("revision")
parser.add_argument("image")
args = parser.parse_args()
repo = Path("C:/Users/Moe/.codex/worktrees/savia-score-90/factored-hackathon-2026")
context = Path("C:/Users/Moe/.codex/tmp") / ("savia-final-runtime-" + args.revision[:12])
manifest = json.loads((context / "application/source-manifest.json").read_text())
retained = json.loads((context / "retained-runtime.json").read_text())
assert manifest["git_head"] == args.revision
assert manifest["components"]["portal"]["git_head"] == args.revision
assert manifest["components"]["analytics_cli"]["git_head"] == args.revision
machine = next(m for m in json.loads(subprocess.check_output(
    ["flyctl.exe", "machine", "list", "--app", "savia-rc-2026", "--json"])) if m["id"] == "851d7dc4460048")
config = machine["config"]
actual_image = config["image"]
assert actual_image.split("@")[-1] == args.image.split("@")[-1], actual_image
assert machine["state"] == "started"
previous = json.loads(Path("C:/Users/Moe/.codex/tmp/savia-pitch-preserved-config.private.json").read_text())
if "config" in previous:
    previous = previous["config"]
assert {k: v for k, v in config.items() if k != "image"} == {k: v for k, v in previous.items() if k != "image"}
code = '''from pathlib import Path
import hashlib,json
root=Path('/srv/savia')
manifest=json.loads((root/'source-manifest.json').read_text())
retained=json.loads(Path('/tmp/release/retained-runtime.json').read_text())
def hashes(files,base):
 result={}
 for name,wanted in files.items():
  path=(base/name) if base else Path(name)
  assert path.is_file() and not path.is_symlink(),name
  actual=hashlib.sha256(path.read_bytes()).hexdigest()
  assert actual==wanted,name
  result[name]=actual
 return result
sources=hashes(manifest['files'],root)
browser=hashes(retained['browser'],root/'frontend/dist')
native=hashes(retained['native'],None)
print(json.dumps({'manifest':manifest,'source_hashes':sources,'served_ui':browser,'retained_runtime_hashes':native,
 'source_manifest_sha256':hashlib.sha256((root/'source-manifest.json').read_bytes()).hexdigest(),
 'portal_source_manifest':json.loads((root/'portal-source-manifest.json').read_text()),
 'native_exact_configured':"'native_exact'" in (root/'deploy/rc/run.py').read_text() or '"native_exact"' in (root/'deploy/rc/run.py').read_text()}))
'''
encoded = base64.b64encode(code.encode()).decode()
command = 'python -c "import base64;exec(base64.b64decode(\'' + encoded + '\'))"'
execution = subprocess.run(["flyctl.exe", "ssh", "console", "--app", "savia-rc-2026", "--machine", "851d7dc4460048",
    "--command", command], check=True, capture_output=True, text=True)
observed = json.loads(next(line for line in execution.stdout.splitlines() if line.startswith('{"manifest"')))
assert observed["manifest"] == manifest
assert observed["source_hashes"] == manifest["files"]
assert observed["served_ui"] == retained["browser"]
assert observed["retained_runtime_hashes"] == retained["native"]
assert observed["native_exact_configured"] is True
observed.update({"schema": "savia-final-public-runtime/v1", "image": actual_image,
    "machine_id": machine["id"], "machine_state": machine["state"], "reverified_at_utc": datetime.now(timezone.utc).isoformat(),
    "preserved_machine_configuration": True, "guest": config["guest"], "volume_mounts": config["mounts"],
    "preserved_native_and_browser": True})
out = context / "runtime-verification.json"
out.write_text(json.dumps(observed, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"application_source": args.revision, "image": actual_image, "healthy_started": True,
    "source_files_verified": len(observed["source_hashes"]), "browser_files_retained": len(observed["served_ui"]),
    "native_files_retained": len(observed["retained_runtime_hashes"]), "configuration_preserved": True,
    "receipt": str(out)}))
