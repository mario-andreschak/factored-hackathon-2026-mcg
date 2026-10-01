"""One-command preview preparation binds only fictional owners and never overwrites."""

from __future__ import annotations

import hashlib
import json
import os
import stat

import duckdb
import pytest

from pipeline.common import current_build, sql_path
from pipeline.prepare_release_preview import prepare
from pipeline.prototype_fixture import MARKER, PERSONAS, PUBLISHED_MARKER


def test_fresh_preview_has_matching_provenance_private_owner_invites_and_no_overwrite(tmp_path):
    root = tmp_path / "preview"
    config_path, codes_path = prepare(root)
    build = current_build(root / "snapshot")
    source_marker = json.loads((root / "source" / MARKER).read_text(encoding="utf-8"))
    provenance = json.loads((build / PUBLISHED_MARKER).read_text(encoding="utf-8"))
    snapshot = json.loads((build / "snapshot.json").read_text(encoding="utf-8"))
    config = json.loads(config_path.read_text(encoding="utf-8"))
    codes = json.loads(codes_path.read_text(encoding="utf-8"))

    assert source_marker["synthetic"] is True
    assert source_marker["origin"] == "team-generated-prototype"
    assert provenance == {
        "kind": "team_synthetic_fixture", "build_id": build.name,
        "source_fingerprint": snapshot["source_fingerprint"],
    }
    assert config["expected_snapshot"] == provenance
    assert config["auth_mode"] == "invite" and config["chat"] == {}
    assert config["public_origin"] == "http://localhost:43801"
    assert set(codes) == {person.profile for person in PERSONAS}
    assert len(set(codes.values())) == len(PERSONAS)
    assert {hashlib.sha256(code.encode()).hexdigest(): profile
            for profile, code in codes.items()} == config["invites"]
    assert all(code not in config_path.read_text(encoding="utf-8") for code in codes.values())
    if os.name == "posix":
        assert stat.S_IMODE(config_path.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(config_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(codes_path.stat().st_mode) == 0o600

    with duckdb.connect() as con:
        gold = sql_path(build / "gold" / "transactions_by_customer")
        for person in PERSONAS:
            binding = config["profiles"][person.profile]
            assert binding["customer_id"] == person.customer_id
            assert binding["country"] == person.country
            owned = con.execute(f"""SELECT count(*), count(*) FILTER (WHERE ownership_valid),
                count(*) FILTER (WHERE transaction_id = ? AND product_id = ?)
                FROM read_parquet('{gold}/**/*.parquet') WHERE customer_id = ?""",
                [person.candidate_id, person.card_id, person.customer_id]).fetchone()
            assert owned == (21, 21, 1)

    previous_config, previous_codes = config_path.read_bytes(), codes_path.read_bytes()
    with pytest.raises(FileExistsError, match="new or empty directory"):
        prepare(root)
    assert config_path.read_bytes() == previous_config
    assert codes_path.read_bytes() == previous_codes
    assert not (root / ".preview-preparing").exists()

    occupied = tmp_path / "occupied"
    occupied.mkdir()
    sentinel = occupied / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError, match="new or empty directory"):
        prepare(occupied)
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert list(occupied.iterdir()) == [sentinel]
