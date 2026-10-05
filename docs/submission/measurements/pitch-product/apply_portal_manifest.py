"""Retain source verification while publishing a separately pinned public portal."""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json

APPLICATION = "f3c57b26d07c1e96b6e61a25befcbbc5fd51a17f"
BASE_IMAGE = "registry.fly.io/savia-rc-2026@sha256:c38f3af736defdf55c7de47b0e1597ad361b3f748c845176b920377fd12b307f"
PREFIX = "web/submission/"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(root, files):
    for name, wanted in files.items():
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name:
            raise ValueError("nonrelative source path")
        path = root / name
        if not path.is_file() or any(part.is_symlink() for part in (path, *path.parents)):
            raise ValueError("nonregular source file: " + name)
        if digest(path) != wanted:
            raise ValueError("immutable source mismatch: " + name)


def apply(root, phase):
    manifest_path = root / "source-manifest.json"
    original_hash = digest(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    if manifest["git_head"] != APPLICATION:
        raise ValueError("unexpected retained application revision")
    original_files = dict(manifest["files"])
    if phase == "verify-base":
        verify(root, original_files)
        print(json.dumps({"base_source_files_verified": len(original_files),
                          "base_manifest_sha256": original_hash}))
        return

    portal_path = root / "portal-source-manifest.json"
    portal = json.loads(portal_path.read_text())
    if portal["application_source"] != APPLICATION or portal["retained_runtime_image"] != BASE_IMAGE:
        raise ValueError("portal application/base pin mismatch")
    portal_files = portal["files"]
    inherited_portal = {name for name in original_files if name.startswith(PREFIX)}
    if set(portal_files) != inherited_portal or len(portal_files) != 28:
        raise ValueError("public inventory differs; explicit stale-file handling required")
    disk_portal = {path.relative_to(root).as_posix()
                   for path in (root / PREFIX).rglob("*") if path.is_file()}
    if disk_portal != set(portal_files):
        raise ValueError("unreferenced public asset")
    retained = {name: sha for name, sha in original_files.items() if not name.startswith(PREFIX)}
    verify(root, retained)
    verify(root, portal_files)
    served = json.loads((root / PREFIX / "portal-manifest.json").read_text())["files"]
    if len(served) != 27 or {PREFIX + name for name in served} | {PREFIX + "portal-manifest.json"} != set(portal_files):
        raise ValueError("served public inventory mismatch")
    if any(portal_files[PREFIX + name] != sha for name, sha in served.items()):
        raise ValueError("served public digest mismatch")

    manifest.update({
        "schema": "savia-public-rc-components/v2",
        "git_head_scope": "retained application component; excludes web/submission/",
        "retained_image": BASE_IMAGE,
        "retained_source_manifest_sha256": original_hash,
        "portal_source_manifest_sha256": digest(portal_path),
        "components": {
            "application": {"git_head": APPLICATION, "git_tree": manifest["git_tree"],
                            "source_files": len(retained), "scope": "all inherited nonportal sources"},
            "portal": {"git_head": portal["git_head"], "git_tree": portal["git_tree"],
                       "source_files": len(portal_files), "served_assets": len(served),
                       "scope": PREFIX},
        },
        "files": {**retained, **portal_files},
    })
    if {name: sha for name, sha in manifest["files"].items() if not name.startswith(PREFIX)} != retained:
        raise ValueError("application source inventory changed")
    verify(root, manifest["files"])
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"source_files_verified": len(manifest["files"]),
                      "retained_application_files": len(retained),
                      "portal_files": len(portal_files), "startup_guard_unchanged": True}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("verify-base", "apply"))
    parser.add_argument("--root", type=Path, default=Path("/srv/savia"))
    args = parser.parse_args()
    apply(args.root, args.phase)
