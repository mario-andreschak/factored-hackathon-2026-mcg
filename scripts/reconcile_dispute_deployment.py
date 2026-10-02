"""Offline retained-ledger transition. Never run against an active old authority."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from frontend.server.deployment_transition import plan, apply, verify


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    dry = commands.add_parser("plan", help="read only original state; write a private plan")
    for key in ("bank-config-file", "legacy-frontend-state-dir", "legacy-worker-state-dir",
                "native-state-dir", "new-frontend-state-dir", "native-authority-dir",
                "operator-evidence", "source-root", "output"):
        dry.add_argument("--" + key, type=Path, required=True)
    commit = commands.add_parser("apply", help="operator gated explicit adoption")
    for key in ("plan", "bank-config-file", "operator-evidence", "receipt"):
        commit.add_argument("--" + key, type=Path, required=True)
    commit.add_argument("--native-reader-group", type=int)
    check = commands.add_parser("verify", help="read only startup reconciliation")
    for key in ("receipt", "bank-config-file", "source-root", "native-state-dir"):
        check.add_argument("--" + key, type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            result = plan(output=args.output, bank_config_file=args.bank_config_file,
                legacy_frontend_state_dir=args.legacy_frontend_state_dir,
                legacy_worker_state_dir=args.legacy_worker_state_dir,
                native_state_dir=args.native_state_dir,
                new_frontend_state_dir=args.new_frontend_state_dir,
                native_authority_dir=args.native_authority_dir,
                operator_evidence=args.operator_evidence, source_root=args.source_root)
        elif args.command == "apply":
            result = apply(plan_file=args.plan, bank_config_file=args.bank_config_file,
                operator_evidence=args.operator_evidence, receipt=args.receipt,
                native_reader_group=args.native_reader_group)
        else:
            result = verify(receipt=args.receipt, bank_config_file=args.bank_config_file,
                source_root=args.source_root, native_state_dir=args.native_state_dir)
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        parser.exit(2, f"transition refused: {type(error).__name__}: {error}\n")
    print(json.dumps({"status": "verified" if args.command == "verify" else args.command,
                      "schema": result["schema"]}, sort_keys=True))


if __name__ == "__main__":
    main()
