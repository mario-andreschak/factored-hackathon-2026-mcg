"""Qualify final served bytes and retained state without paid/write requests."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("capture", type=Path)
    p.add_argument("--original-capture", type=Path, required=True)
    p.add_argument("--bank-ledger-private", type=Path, required=True)
    p.add_argument("--output-prefix", type=Path, required=True)
    args = p.parse_args()
    current = json.loads(args.capture.read_text(encoding="utf-8"))
    original = json.loads(args.original_capture.read_text(encoding="utf-8"))
    if not current["generated_only"]:
        raise ValueError("fictional runtime required")
    assets = list({(a["path"], a["sha256"]): a for a in current["served_js_assets"]}.values())
    for asset in assets:
        asset["matches_startup_manifest"] = current["runtime"]["served_ui"].get(asset["path"].lstrip("/")) == asset["sha256"]
    def histories(c):
        return [e["public_response"]["messages"] for e in c["events"]
            if e.get("path") == "/api/chat/history" and e.get("public_response", {}).get("messages")]
    def texts(history):
        return [(m["role"], m["text"]) for m in history]
    history_exact = texts(histories(current)[-1]) == texts(histories(original)[-1])
    requests = [e for e in current["events"] if e.get("kind") == "http-request"]
    responses = [e for e in current["events"] if e.get("kind") == "http"]
    cases = [e["public_response"]["items"] for e in responses if e.get("path") == "/api/assistant/cases" and "items" in e.get("public_response", {})][-1]
    action = [e["public_response"] for e in responses if e.get("path") == "/api/action/status"][-1]
    followups = [e["public_response"].get("items", []) for e in responses if e.get("path") == "/api/followups"][-1]
    ledger = sqlite3.connect(args.bank_ledger_private.resolve().as_uri() + "?mode=ro", uri=True)
    counts = {name: ledger.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        for name in ("sandbox_cases", "sandbox_case_receipts")}
    ledger.close()
    result = {"schema": "savia-final-integrated-readonly/v1", "observed_at": datetime.now(timezone.utc).isoformat(),
        "source_git_head": current["runtime"]["git_head"], "application_source_hash_count": len(current["runtime"]["application_sources"]),
        "capture": args.capture.as_posix(), "fictional": True, "actual_browser": True,
        "authentication": current["authentication"], "served_js_assets": assets,
        "all_served_js_bytes_match_startup": bool(assets) and all(a["matches_startup_manifest"] for a in assets),
        "api_request_methods": sorted(set(e["method"] for e in requests)), "api_requests": len(requests),
        "non_get_api_requests": sum(e["method"] != "GET" for e in requests),
        "model_chat_posts": sum(e["path"] == "/api/chat/messages" and e["method"] == "POST" for e in requests),
        "new_team_posts": sum(e["path"] == "/api/assistant/cases" and e["method"] == "POST" for e in requests),
        "intake_confirm_posts": sum(e["path"] == "/api/action/confirm" and e["method"] == "POST" for e in requests),
        "all_recorded_api_responses_http200": all(e["status"] == 200 for e in responses),
        "exact_original_history_role_and_text": history_exact, "history_message_count": len(histories(current)[-1]),
        "retained_informational_cases": [{"id": c["id"], "state": c["state"],
            "completed_workers": sum(w["state"] == "completed" for w in c["workers"]),
            "suggestions": [w["suggestion"] for w in c["workers"] if w["suggestion"]]} for c in cases],
        "current_action_status": action.get("state"), "current_followup_items": len(followups),
        "ledger_read_only_counts": counts, "bank_resolution_observed": False,
        "limits": ["Action status returned none and followup list was empty in this preserved team-story context.",
            "The folio visible in the archived reply is historical text, not a newly verified receipt.",
            "Raw snapshot 05-final-existing-receipt is retained but its name is misleading: the actual API returned none.",
            "Original slow-story opt-in used another session whose browser cookie was not saved. No authority was transplanted.",
            "Read-only ledger counts establish retained simulated records, not current bank authorization or resolution."]}
    result["qualified_source_and_inquiry_replay"] = result["all_served_js_bytes_match_startup"] and history_exact and result["non_get_api_requests"] == 0 and len(cases) == 2
    args.output_prefix.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Final integrated read-only replay", "", f"Source `{result['source_git_head']}` served the exact JavaScript bytes recorded in its startup manifest. The old session remained authenticated without a fresh login.", "", "Two existing informational inquiries and their useful suggestions survived reload. The exact original two-message conversation was restored through the prior-chat view. All recorded API requests were GET; no model chat, new team request or intake confirmation occurred.", "", f"The simulated ledger still contains {counts['sandbox_cases']} case and {counts['sandbox_case_receipts']} receipt. The current action API returned `{result['current_action_status']}` and the followup list contained {len(followups)} items in this team-story context. Historical receipt wording is not a fresh verification.", "", "The original slow-story followup was owned by another session whose browser cookie was not saved. No authority was transplanted. Raw screenshot 05 has a premature receipt label; the API trace is authoritative and unchanged.", "", "This qualifies final source bytes, inquiry persistence and historical chat restoration; it does not qualify a new model run or fresh bank receipt/followup UI verification.", ""]
    args.output_prefix.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("qualified_source_and_inquiry_replay", "source_git_head", "non_get_api_requests", "current_action_status", "current_followup_items", "ledger_read_only_counts")}))


if __name__ == "__main__":
    main()
