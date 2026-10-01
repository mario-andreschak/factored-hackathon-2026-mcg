"""Prepare a fresh, fictional standalone banking preview in one command.

Run ``python -m pipeline.prepare_release_preview <new-output-root>`` from the
repository root. This generates source CSVs, a published snapshot, provenance,
and private owner-bound invitations. It does not start any service.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import urlsplit

from .__main__ import main as pipeline_main
from .prepare_invite_preview import prepare as prepare_invitations
from .prototype_fixture import stamp_published_snapshot, write_prototype_source


def prepare(root: Path, origin: str = "http://localhost:43801") -> tuple[Path, Path]:
    """Build only into an absent or empty root; never replace a previous preview."""
    root = Path(root).expanduser()
    if root.is_symlink() or (root.exists() and (not root.is_dir() or any(root.iterdir()))):
        raise FileExistsError(f"preview output must be a new or empty directory: {root}")
    # Validate before creating files. The invitation writer enforces the same
    # exact loopback-origin policy before it writes private configuration.
    parsed = urlsplit(origin)
    if (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.port is None or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment or origin.endswith("/")):
        raise ValueError("preview origin must be an exact loopback HTTP origin with a port")

    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root = root.resolve()
    # The exclusive marker also refuses a concurrent call that passed the
    # initial emptiness check. A failed build remains visibly incomplete, and
    # its nonempty root cannot be silently reused.
    marker = root / ".preview-preparing"
    with marker.open("x", encoding="utf-8"):
        pass
    source, snapshot, reports, private = (root / name for name in
                                          ("source", "snapshot", "reports", "secrets"))
    try:
        if any(path != marker for path in root.iterdir()):
            raise FileExistsError(f"preview output must be a new or empty directory: {root}")
        write_prototype_source(source)
        result = pipeline_main(["run", "--source", str(source), "--out", str(snapshot),
                                "--reports", str(reports)])
        if result != 0:
            raise RuntimeError(f"synthetic pipeline did not publish (exit {result})")
        stamp_published_snapshot(source, snapshot)
        private.mkdir(mode=0o700)
        return prepare_invitations(source, snapshot, private, origin)
    finally:
        marker.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="new or empty output directory")
    parser.add_argument("--origin", default="http://localhost:43801",
                        help="exact loopback origin for the standalone preview")
    args = parser.parse_args()
    config, codes = prepare(args.root, args.origin)
    print("\nSynthetic preview prepared (services were not started).")
    print(f"Snapshot: {config.parent.parent / 'snapshot'}")
    print(f"Reports: {config.parent.parent / 'reports'}")
    print(f"Private configuration: {config}")
    print(f"Private invitation codes: {codes} (keep private)")
    print("To run the existing standalone preview from frontend/:")
    print(f"  BANKING_DATA_DIR = {config.parent.parent / 'snapshot'}")
    print(f"  BANKING_CONFIG_FILE = {config}")
    print(f"  BANKING_PORT = {urlsplit(args.origin).port}")
    print(f"  BANKING_PUBLIC_ORIGIN = {args.origin}")
    print("  docker compose -p savia-synthetic -f compose.yaml up -d --build --wait")
    print("See frontend/README.md for shell-specific environment commands and limits.")


if __name__ == "__main__":
    main()
