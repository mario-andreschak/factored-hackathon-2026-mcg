"""Combine one recorded fixed ES case with bounded paired PT cases.

Preserve exact replies and source evidence. Screening is an agent review,
not independent human adjudication or evidence of a banking resolution.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
import time

from measure_customer import baseline, CASES, MinimizedFacts


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("capture", type=Path)
    p.add_argument("pt_comparison", type=Path)
    p.add_argument("--output-directory", type=Path, required=True)
    p.add_argument("--observations-private", type=Path)
    args = p.parse_args()
    capture = json.loads(args.capture.read_text(encoding="utf-8"))
    result = json.loads(args.pt_comparison.read_text(encoding="utf-8"))
    events = capture["events"]
    start = datetime.fromisoformat(capture["started_at"].replace("Z", "+00:00"))
    request = next(e for e in events if e.get("kind") == "http-request" and e.get("path") == "/api/chat/messages")
    reply = next(e for e in events if e.get("kind") == "http" and e.get("path") == "/api/chat/messages")
    history = [e for e in events if e.get("path") == "/api/chat/history" and e.get("public_response", {}).get("messages")][-1]
    messages = history["public_response"]["messages"]
    fixed = next(c for c in CASES if c[0] == "es-selected")
    if messages[0]["text"] != fixed[2]:
        raise ValueError("recorded ES question must match frozen paired case")
    facts_dict = deepcopy(result["cases"][0]["display_facts"])
    facts = MinimizedFacts(**facts_dict)
    before = time.perf_counter()
    deterministic = baseline(fixed[2], "es", facts)
    baseline_ms = round((time.perf_counter() - before) * 1000, 3)
    row = deepcopy(result["cases"][0])
    row.update(case=fixed[0], language="es", message=fixed[2], expected_behavior=fixed[4], display_facts=facts_dict,
        baseline={"kind": "repository deterministic display copy + frozen selection/human rule", "reply": deterministic,
                  "latency_ms": baseline_ms, "model_calls": 0, "tool_calls": 0},
        actual={"response": reply["public_response"], "http_status": reply["status"],
            "latency_ms": reply["at_ms"] - request["at_ms"], "latency_kind": "browser request to response-header event",
            "history_status": history["status"], "history_message_count": len(messages),
            "exact_reply_in_history": any(m.get("text") == reply["public_response"]["reply"] for m in messages),
            "model_call_count": None, "tool_call_count": None},
        http_calls=[{"path": "/api/chat/messages", "method": "POST", "http_status": reply["status"],
            "started_at": (start + timedelta(milliseconds=request["at_ms"])).isoformat(),
            "completed_at": (start + timedelta(milliseconds=reply["at_ms"])).isoformat()}],
        artifact=str(args.capture.as_posix()))
    result["cases"].insert(0, row)
    result.update(sample_size=3, runtime=capture["runtime"], browser_recorded_es_case=True,
                  source_note="Backend startup receipt is preserved. UI received final builds during recording; see team-story-summary provenance notes.")
    notes = {
        "es-selected": (True, True, "Correct merchant, date, amount/currency and existing simulated folio; no duplicate case. Chat gives limited next-step detail; team result supplies receipt comparison and folio advice."),
        "pt-selected": (False, True, "Selected date/amount were supplied, but two rewritten subqueries needlessly ask for them again; no useful selected-fact explanation."),
        "pt-ambiguous": (True, True, "Correct Portuguese clarification asks for the missing date and amount; no completion or handoff is asserted."),
    }
    for case in result["cases"]:
        useful, language, note = notes[case["case"]]
        case.update(useful_outcome=useful, language_correct=language,
                    grounding="selected facts correct" if case["case"] == "es-selected" else "not established" if case["case"] == "pt-selected" else "no bank facts asserted",
                    agent_screening={"useful": useful, "language_correct": language, "note": note}, human_adjudication="pending")
    result["limits"].extend(["n=3 fixed AI-authored examples; two languages and two behavior types, no population estimate or causal improvement claim.",
        "One ES case reuses its actual browser request; PT cases use urllib timing through body read. Timing boundaries differ slightly.",
        "Useful outcome is agent screening; independent human review remains pending. The original PT selected-fact failure is retained."])
    save(args.output_directory / "final-comparison.json", result)

    created = next(e for e in events if e.get("path") == "/api/assistant/cases" and e.get("method") == "POST" and e.get("status") == 202)
    created_request = next(e for e in events if e.get("kind") == "http-request" and e.get("method") == "POST" and e.get("path") == "/api/assistant/cases")
    cases = [(e, item) for e in events for item in e.get("public_response", {}).get("items", []) if item.get("id") == created["public_response"]["id"]]
    completed_event, completed = next((e, item) for e, item in cases if item["state"] == "team_completed")
    closed_event, closed = next((e, item) for e, item in cases if item["state"] == "informational_resolved")
    summary = {"schema": "savia-current-team-story/v1", "capture": str(args.capture.as_posix()),
        "actual_browser": True, "mocked_requests": 0, "fictional_bank": True,
        "actual_provider": capture["runtime"]["language"], "bank_authority": False,
        "actual_model_workers": 2, "completed_workers": sum(w["state"] == "completed" for w in completed["workers"]),
        "worker_output_scope": "Two real bounded structured model choices; trusted server facts and reviewed copy form the suggestions.",
        "case_id": completed["id"], "submit_to_first_completed_ui_response_ms": completed_event["at_ms"] - created_request["at_ms"],
        "queued_to_completed_event_seconds": completed["updated_at"] - completed["created_at"],
        "completed_case": completed, "customer_closed_case": closed, "customer_closed_at_ms": closed_event["at_ms"],
        "archive_preserved_case": True, "reload_preserved_case": True, "history_exact": row["actual"]["exact_reply_in_history"],
        "new_bank_confirm_requests": sum(e.get("kind") == "http-request" and e.get("path") == "/api/action/confirm" for e in events),
        "bank_resolution_observed": False,
        "markers": [{k: s[k] for k in ("name", "at_ms")} for s in capture["snapshots"]],
        "ui_provenance": {"initial_loaded_asset": "Not independently captured by recorder; startup served_ui metadata predates final source-owner build notices.",
            "source_owner_final_build_before_reload": "index-DDMU2raD.js; 9b081a47966ea56f37ec7cb98ab937f8160220f910411398f9057b3f353cc852",
            "source_owner_saved_answer_reload_build": "index-iXDcoSnQ.js; 5ce55fd2c41c28ae3ec170ccff0572830a58b5b107990eaba063081345c0c85e",
            "note": "Historical capture.runtime fields are unchanged. UI retention was fixed between snapshots 10 and 11; same persisted case, no paid repetition."},
        "limits": ["Customer helpful acknowledgment closes an informational inquiry only.", "No human worker, bank resolution, refund, or week-long reliability is demonstrated.", "This model profile is direct OpenRouter, not native FLUJO execution.", "Browser event times need visual frame verification when editing WebM."]}
    if args.observations_private:
        low = start + timedelta(milliseconds=created_request["at_ms"])
        high = start + timedelta(milliseconds=completed_event["at_ms"])
        observed = [json.loads(line) for line in args.observations_private.read_text(encoding="utf-8").splitlines() if line]
        workers = [o for o in observed if o.get("kind") == "model" and o.get("stage", "").startswith("inquiry_")
                   and low <= datetime.fromisoformat(o["observed_at"]) <= high]
        summary["observed_worker_calls"] = [{k: o[k] for k in ("stage", "model", "status", "latency_ms", "prompt_tokens", "completion_tokens", "cost_usd") if k in o} for o in workers]
        summary["observed_worker_attempts"] = len(workers)
        summary["observed_worker_transport_completions"] = sum(o["status"] == "ok" for o in workers)
    marker_map = {s["name"]: s["at_ms"] / 1000 for s in capture["snapshots"]}
    save(args.output_directory / "team-story-summary.json", summary)
    transcript = ["# Actual team inquiry and saved result", "", f"One fictional customer's two-agent request completed in {summary['submit_to_first_completed_ui_response_ms']/1000:.3f}s from POST start to the first completed poll response.", "", "Two real structured model choices selected reviewed guidance. Server facts supply the amount and date. No bank action or human work occurred.", "", "Actual customer request:", "", completed["message"], "", "Actual suggestions:", ""]
    transcript += ["- " + w["suggestion"] for w in completed["workers"] if w["suggestion"]]
    transcript += ["", "The customer marked the explanation helpful. The informational inquiry and suggestions survive a new chat and reload; the previous exact conversation remains available.", "", f"Useful saved-result movie insert: snapshot 11 at {marker_map.get('11-saved-useful-result')}s. Selected-answer insert: snapshot 04 at {marker_map.get('04-grounded-answer')}s. Verify event markers against actual WebM frames and duration.", "", "UI retention was fixed between snapshots 10 and 11 without rerunning either agent. Startup UI metadata is older than the final build notices; exact source-owner bundle hashes and this limitation are retained in the JSON.", "", "A separate actual receipt check repeated after 1,800 seconds; see actual-half-hour-followup.json. This does not establish day/week reliability or bank resolution.", ""]
    (args.output_directory / "team-story-summary.md").write_text("\n".join(transcript), encoding="utf-8")
    print(json.dumps({"comparison_n": 3, "agent_screened_useful": 2, "team_ms": summary["submit_to_first_completed_ui_response_ms"], "workers": summary["completed_workers"]}))


if __name__ == "__main__":
    main()
