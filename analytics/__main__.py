"""CLI: python -m analytics {build,report,feedback}."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .extract import add_feedback, build, discover
from .report import render, summarize


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m analytics", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    build_cmd = commands.add_parser("build", help="rebuild the analytics database from operational state")
    build_cmd.add_argument("--state-dir", type=Path, help="directory holding the Savia/Gloria *.sqlite3 files")
    build_cmd.add_argument("--workflow-db", type=Path, action="append", default=[], help="explicit gloria_turns store")
    build_cmd.add_argument("--chat-db", type=Path, action="append", default=[], help="explicit chat_messages store")
    build_cmd.add_argument("--out", type=Path, required=True, help="analytics SQLite output (separate file)")
    build_cmd.add_argument("--key", type=Path, help="pseudonym HMAC key file (default: <out>.key)")

    report_cmd = commands.add_parser("report", help="print agent performance indicators")
    report_cmd.add_argument("--db", type=Path, required=True)
    report_cmd.add_argument("--json", action="store_true", help="machine-readable output")

    feedback_cmd = commands.add_parser("feedback", help="record a reviewer or customer judgement")
    feedback_cmd.add_argument("--db", type=Path, required=True)
    target = feedback_cmd.add_mutually_exclusive_group(required=True)
    target.add_argument("--turn")
    target.add_argument("--conversation")
    feedback_cmd.add_argument("--source", choices=("reviewer", "customer"), default="reviewer")
    feedback_cmd.add_argument("--rating", type=int, choices=(-1, 0, 1))
    feedback_cmd.add_argument("--label", help="short category, e.g. intent_incorrect")

    args = parser.parse_args(argv)
    if args.command == "build":
        workflow, chat = list(args.workflow_db), list(args.chat_db)
        if args.state_dir:
            found_workflow, found_chat = discover(args.state_dir)
            workflow += found_workflow
            chat += found_chat
        if not workflow and not chat:
            parser.error("no gloria_turns or chat_messages store found; pass --state-dir or explicit databases")
        counts = build(args.out, workflow_dbs=workflow, chat_dbs=chat, key_path=args.key)
        print(json.dumps({"sources": {"workflow": [str(path) for path in workflow],
                                      "chat": [str(path) for path in chat]}, **counts}, indent=2))
    elif args.command == "report":
        summary = summarize(args.db)
        print(json.dumps(summary, indent=2, ensure_ascii=False) if args.json else render(summary))
    else:
        if args.rating is None and not args.label:
            parser.error("feedback needs --rating and/or --label")
        feedback_id = add_feedback(args.db, source=args.source, turn_id=args.turn,
                                   conversation_id=args.conversation, rating=args.rating, label=args.label)
        print(json.dumps({"feedback_id": feedback_id}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
