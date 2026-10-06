"""Replay the frozen eight-case automated policy-label audit with the standard library.

This verifies artifact identity, prespecified sampling and label agreement. It
does not run a classifier or establish human ground truth for the 120-case set.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import sys


DATASET_SHA256 = "3c4f68d880146915d7fb27c7884733190c1d87d84e1fee6d066afeed85538684"
PACKET_SHA256 = "cb7cd689f9ee2543f3c32eca33d9ea8a0efa772c28f20dc72164037a65551d62"
SEED = "savia-human-sample-v1-20261005"
EVIDENCE = Path("docs/submission/measurements/router-policy-audit")
CLASSES = frozenset({"inquiry", "dispute", "human", "other"})
IDS = tuple("ABCDEFGH")
FROZEN_INPUTS = {
    "human-adjudication-sample.json": PACKET_SHA256,
    "policy-label-audit-a.json": "2a488bbc77a14e364a32e0809f720dfba53be7699dbfd30e90c764f05a13bd38",
    "policy-label-audit-b.json": "579ec5d7fd191bca830ec2d725edcd66c79df3cdaa5c1f9815b49f65cb4737cc",
}
REVIEWERS = (
    ("a", "policy-label-audit-a.json", "label", "input_packet_sha256",
     "savia-ai-semantic-policy-label-audit/v1", "policy-label-audit-a"),
    ("b", "policy-label-audit-b.json", "class", "packet_sha256",
     "savia-automated-policy-label-audit/v1", "b"),
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def read_file(path: Path) -> bytes:
    require(path.is_file() and not path.is_symlink(), f"regular_file_required:{path.name}")
    return path.read_bytes()


def audit(repo: Path) -> dict:
    evidence = repo / EVIDENCE
    manifest = json.loads(read_file(evidence / "manifest.json"))
    require(manifest.get("schema") == "savia-router-policy-audit-manifest/v1", "manifest_schema_mismatch")
    require(manifest.get("frozen_inputs_sha256") == FROZEN_INPUTS, "frozen_input_manifest_mismatch")
    frozen = {}
    for name, expected in FROZEN_INPUTS.items():
        raw = read_file(evidence / name)
        require(sha256(raw) == expected, f"frozen_input_hash_mismatch:{name}")
        frozen[name] = json.loads(raw)

    packet = frozen["human-adjudication-sample.json"]
    require(packet.get("schema") == "savia-blind-human-sample/v1", "packet_schema_mismatch")
    require(packet.get("dataset_sha256") == DATASET_SHA256 and packet.get("seed") == SEED,
            "packet_dataset_or_seed_mismatch")
    cases = packet.get("cases")
    require(isinstance(cases, list) and len(cases) == len(IDS), "packet_case_count_mismatch")
    require([case.get("id") for case in cases] == list(IDS), "packet_case_ids_mismatch")
    require(all(set(case) == {"id", "text", "lang"} for case in cases), "packet_labels_not_withheld")

    # The raw auditors' hashes are locked above before accessing the proposed
    # CSV labels. The auditors received only the fixed packet and protocol.
    audit_labels = {}
    for reviewer, name, label_key, packet_key, schema, audit_id in REVIEWERS:
        review = frozen[name]
        require(review.get("schema") == schema and review.get("audit_id") == audit_id,
                f"reviewer_identity_mismatch:{reviewer}")
        require(review.get(packet_key) == PACKET_SHA256, f"reviewer_packet_mismatch:{reviewer}")
        reviewed = review.get("cases")
        require(isinstance(reviewed, list) and len(reviewed) == len(IDS),
                f"reviewer_case_count_mismatch:{reviewer}")
        require([case.get("id") for case in reviewed] == list(IDS), f"reviewer_case_ids_mismatch:{reviewer}")
        require(all(set(case) == {"id", label_key, "confidence", "literal_english_gloss", "policy_reason"}
                    and case.get(label_key) in CLASSES
                    and all(isinstance(case.get(key), str) and case[key].strip()
                            for key in ("confidence", "literal_english_gloss", "policy_reason"))
                    for case in reviewed), f"reviewer_class_or_reason_invalid:{reviewer}")
        audit_labels[reviewer] = {case["id"]: case[label_key] for case in reviewed}

    dataset_raw = read_file(repo / "ml/data/router_test.csv")
    require(sha256(dataset_raw) == DATASET_SHA256, "frozen_dataset_hash_mismatch")
    reader = csv.DictReader(io.StringIO(dataset_raw.decode("utf-8"), newline=""))
    require(reader.fieldnames == ["text", "label", "lang", "author"], "dataset_schema_mismatch")
    rows = list(reader)
    require(len(rows) == 120 and len({row["text"] for row in rows}) == 120, "dataset_case_count_mismatch")
    require(all(row["label"] in CLASSES and row["lang"] in {"es", "pt"}
                and row["author"] == "codex_blind_holdout_20260928" for row in rows),
            "dataset_class_language_or_author_mismatch")

    key = lambda row: sha256((SEED + row["text"]).encode("utf-8"))
    selected = []
    for label in sorted(CLASSES):
        for lang in ("es", "pt"):
            stratum = [row for row in rows if row["label"] == label and row["lang"] == lang]
            require(len(stratum) == 15, "dataset_stratum_count_mismatch")
            selected.append(min(stratum, key=key))
    selected.sort(key=key)
    reproduced = [{"id": case_id, "text": row["text"], "lang": row["lang"]}
                  for case_id, row in zip(IDS, selected)]
    require(reproduced == cases, "prespecified_sample_mismatch")

    comparison = [{"id": case_id, "lang": row["lang"], "proposed_label": row["label"],
                   "audit_a": audit_labels["a"][case_id], "audit_b": audit_labels["b"][case_id]}
                  for case_id, row in zip(IDS, selected)]
    return {
        "schema": "savia-router-policy-audit-replay/v1",
        "scope": "automated semantic policy-label agreement on eight fixed synthetic requests",
        "dataset_sha256": DATASET_SHA256,
        "dataset_rows": len(rows),
        "packet_sha256": PACKET_SHA256,
        "seed": SEED,
        "sample_selection_reproduced": True,
        "audited_cases": len(comparison),
        "total_label_language_strata": len(selected),
        "reviewer_agreement_count": sum(case["audit_a"] == case["audit_b"] for case in comparison),
        "agreement_with_proposed_labels": {
            reviewer: sum(case[f"audit_{reviewer}"] == case["proposed_label"] for case in comparison)
            for reviewer in ("a", "b")},
        "cases": comparison,
        "human_adjudication": False,
        "classifier_predictions_or_training": False,
        "new_holdout_accuracy_measurement": False,
        "limits": [
            "Both semantic audits are AI-generated; agreement is not independent human truth.",
            "One case per original class/language stratum covers 8 of 120 synthetic requests.",
            "The reproducibility script checks identity, sampling and agreement, not semantic correctness.",
            "No inference about the remaining 112 labels, real customer quality or intent prevalence follows.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    try:
        result = audit(args.repo.resolve())
        evidence = args.repo.resolve() / EVIDENCE
        manifest = json.loads(read_file(evidence / "manifest.json"))
        require(sha256(read_file(Path(__file__))) == manifest.get("reproduction_script_sha256"),
                "reproduction_script_hash_mismatch")
        recorded = read_file(evidence / "comparison.json")
        require(sha256(recorded) == manifest.get("comparison_sha256"), "comparison_hash_mismatch")
        require(recorded == json_bytes(result), "comparison_replay_mismatch")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Policy sample audit failed: {exc}", file=sys.stderr)
        return 1
    sys.stdout.buffer.write(json_bytes(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
