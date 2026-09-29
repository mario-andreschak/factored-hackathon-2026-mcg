"""Create private, per-persona invitations for a loopback synthetic preview.

Run after ``pipeline.prototype_fixture stamp``. This command checks the source
again, generates new high-entropy invitations, and writes only to a separate
private directory. Never commit the generated frontend.json or invite-codes.json.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from .prototype_fixture import MARKER, stamp_published_snapshot


COUNTRIES = {"colombia": "Colombia", "mexico": "México", "argentina": "Argentina"}


def _private_json(path: Path, value: dict) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def prepare(source: Path, snapshot: Path, private: Path, origin: str) -> tuple[Path, Path]:
    source, snapshot, private = (Path(path).resolve() for path in (source, snapshot, private))
    parsed = urlsplit(origin)
    if (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.port is None or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment or origin.endswith("/")):
        raise ValueError("preview origin must be an exact loopback HTTP origin with a port")
    if private == source or private.is_relative_to(source) or private == snapshot or private.is_relative_to(snapshot):
        raise ValueError("private invitations must be outside the source and snapshot trees")
    config_path, codes_path = private / "frontend.json", private / "invite-codes.json"
    if config_path.exists() or codes_path.exists():
        raise FileExistsError("preview invitations already exist; use a fresh private directory")

    # This verifies every CSV against both the pipeline inventory and the exact
    # canonical team fixture before treating the build as synthetic.
    marker_path = stamp_published_snapshot(source, snapshot)
    expected = json.loads(marker_path.read_text(encoding="utf-8"))
    source_metadata = json.loads((source / MARKER).read_text(encoding="utf-8"))
    profiles = source_metadata["profiles"]
    if {item["profile"] for item in profiles} != set(COUNTRIES) or len(profiles) != len(COUNTRIES):
        raise ValueError("prototype profiles do not match the invite preview")
    with (source / "customers.csv").open(encoding="utf-8", newline="") as stream:
        customers = {row["customer_id"]: row for row in csv.DictReader(stream)}

    bindings: dict[str, dict[str, str]] = {}
    codes: dict[str, str] = {}
    invites: dict[str, str] = {}
    for item in profiles:
        profile_id, customer_id = item["profile"], item["customer_id"]
        customer = customers.get(customer_id)
        if (customer is None or customer["country"] != COUNTRIES[profile_id]
                or item["country"] != COUNTRIES[profile_id]):
            raise ValueError("prototype customer and country binding mismatch")
        code = secrets.token_urlsafe(32)
        codes[profile_id] = code
        invites[hashlib.sha256(code.encode()).hexdigest()] = profile_id
        bindings[profile_id] = {"customer_id": customer_id,
                                "alias": customer["first_name"],
                                "country": customer["country"]}

    config = {"auth_mode": "invite", "public_origin": origin,
              "expected_snapshot": expected, "profiles": bindings,
              "invites": invites, "chat": {}}
    private.mkdir(parents=True, exist_ok=True)
    created_config = False
    try:
        _private_json(config_path, config)
        created_config = True
        _private_json(codes_path, codes)
    except BaseException:
        if created_config:
            config_path.unlink(missing_ok=True)
        raise
    return config_path, codes_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("private", type=Path)
    parser.add_argument("--origin", default="http://localhost:43801")
    args = parser.parse_args()
    config, codes = prepare(args.source, args.snapshot, args.private, args.origin)
    print(f"Private frontend configuration: {config}")
    print(f"Private invitation codes: {codes}")


if __name__ == "__main__":
    main()
