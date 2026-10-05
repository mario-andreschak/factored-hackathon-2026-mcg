"""Read-only exact-conversation banking MCP audit. Outputs booleans/counts only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat


def require(value):
    if not value:
        raise ValueError("Audit precondition failed")


def read_json(filename, private=False, max_bytes=16 * 1024 * 1024):
    info = filename.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and filename.resolve() == filename)
    require(info.st_size <= max_bytes)
    if private:
        require(info.st_uid == 0 and stat.S_IMODE(info.st_mode) == 0o600)
    return json.loads(filename.read_text(encoding="utf-8"))


def database(filename):
    require(filename.is_file() and not filename.is_symlink())
    connection = sqlite3.connect(filename.as_uri() + "?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("BEGIN")
    return connection


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def audit(receipt_file, binding_file, list_only=False):
    require(os.getuid() == 0)
    receipt, binding = read_json(receipt_file, True), read_json(binding_file, True)
    require(receipt["runId"] == binding["runId"] and receipt["bankSessionTokenHash"] == binding["bankSessionTokenHash"])
    with database(Path("/data/frontend-state/frontend-chat.sqlite3")) as db:
        rows = db.execute("SELECT conversation_id,subject,customer_id FROM chat_sessions WHERE session_id=?",
                          (binding["sessionId"],)).fetchall()
    require(len(rows) == 1)
    chat = rows[0]
    conversation = chat["conversation_id"]
    require(isinstance(conversation, str) and re.fullmatch(r"[a-f0-9-]{36}", conversation))
    policy = read_json(Path("/run/banking-runtime/policy.json"))
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", policy["workspace"]))
    workspace = Path("/data/flujo/workspaces") / policy["workspace"]
    state = read_json(workspace / "db/conversations" / (conversation + ".json"))
    require(state.get("conversationId") == conversation and state.get("flowId") == policy["flowId"])
    tool_map = state.get("toolNameMap", {})
    require(isinstance(tool_map, dict))
    log = workspace / "db/conversation-logs" / (conversation + ".jsonl")
    require(log.is_file() and not log.is_symlink() and log.stat().st_size < 32 * 1024 * 1024)
    events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]
    require(all(event.get("conversationId") == conversation for event in events))
    calls = {event["toolCallId"]: event for event in events if event.get("type") == "tool:call"}
    successful = []
    for event in events:
        if event.get("type") != "tool:result" or event.get("isError") is not False:
            continue
        call = calls.get(event.get("toolCallId"))
        if not call or call.get("name") != event.get("name") or call.get("seq", 0) >= event.get("seq", 0):
            continue
        decoded = tool_map.get(call["name"])
        if not decoded and call["name"].startswith("_-_-_"):
            parts = call["name"].split("_-_-_")
            decoded = {"server": parts[1], "tool": parts[2]} if len(parts) == 3 else None
        if decoded and decoded.get("server") == policy["bankServerName"]:
            successful.append((decoded.get("tool"), call))
    # Native Codex's MCP bridge persists assistant/tool message pairs rather
    # than ModelHandler's tool:call/tool:result events. Decode its readable names
    # against this conversation's advertised map; never infer from answer text.
    native_map = {}
    for decoded in tool_map.values():
        if isinstance(decoded, dict) and decoded.get("server") == policy["bankServerName"]:
            readable = re.sub(r"[^a-zA-Z0-9_-]", "_", decoded["server"]) + "__" + re.sub(r"[^a-zA-Z0-9_-]", "_", decoded["tool"])
            native_map[readable[:64]] = decoded
    messages = state.get("messages", [])
    native_results = {message.get("tool_call_id"): message for message in messages
                      if isinstance(message, dict) and message.get("role") == "tool"}
    native_successful = []
    listing_handles = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls", []) or []:
            function = call.get("function", {})
            decoded = native_map.get(function.get("name")) or tool_map.get(function.get("name"))
            reply = native_results.get(call.get("id"))
            if not decoded or decoded.get("server") != policy["bankServerName"] or not reply:
                continue
            try:
                payload = json.loads(reply.get("content", ""))
                data = payload.get("structuredContent", {})
                require(payload.get("isError") is not True and data.get("read_only") is True
                        and data.get("synthetic") is False and data.get("operator_test") is False)
                tool = decoded["tool"]
                if tool == "list_my_transactions":
                    require(isinstance(data.get("transactions"), list))
                    listing_handles.extend(transaction["selection_handle"] for transaction in data["transactions"])
                native_successful.append((tool, {"toolCallId":call["id"],"args":function.get("arguments", "{}")}))
            except (ValueError, TypeError, KeyError):
                continue
    successful.extend(native_successful)
    listings = [call for tool, call in successful if tool == "list_my_transactions"]
    selections = [call for tool, call in successful if tool == "get_my_transaction"]
    bank_config = read_json(Path(policy["bankConfigFile"]))
    require(bank_config.get("mode") == "delegated")
    # The trusted worker namespaces the frontend session before signing MCP
    # assertions (authority.ts bankSessionId). Compare the derived identity,
    # never the raw frontend session, against the bank's authority database.
    bank_session = digest(json.dumps([policy["deploymentId"], policy["frontendIssuer"], binding["sessionId"]],
                                    separators=(",", ":"), ensure_ascii=False))
    principal_binding = digest(json.dumps({"sub": chat["subject"], "customer": chat["customer_id"],
        "session": bank_session, "conversation": conversation}, sort_keys=True,
        separators=(",", ":"), ensure_ascii=False))
    with database(Path(bank_config["state_db"])) as db:
        sessions = db.execute("SELECT subject,customer FROM sessions WHERE session=?", (bank_session,)).fetchall()
        selection_bindings = []
        listing_bindings = []
        for handle in listing_handles:
            if isinstance(handle, str) and 32 <= len(handle) <= 64:
                row = db.execute("SELECT kind,binding FROM capabilities WHERE id=?", (digest(handle),)).fetchone()
                listing_bindings.append(row is not None and row["kind"] == "selection" and row["binding"] == principal_binding)
        for call in selections:
            arguments = json.loads(call.get("args", "{}"))
            handle = arguments.get("selection_handle")
            if isinstance(handle, str) and 32 <= len(handle) <= 64:
                row = db.execute("SELECT kind,binding FROM capabilities WHERE id=?", (digest(handle),)).fetchone()
                selection_bindings.append(row is not None and row["kind"] == "selection" and row["binding"] == principal_binding)
    checks = {
        "exactConversationBinding": True,
        "successfulBankListCall": len(listings) > 0,
        "mcpSessionCustomerBindingMatches": len(sessions) == 1 and sessions[0]["subject"] == chat["subject"]
            and sessions[0]["customer"] == chat["customer_id"],
        "listedHandlesConversationCustomerBindingMatches": bool(listing_bindings) and all(listing_bindings),
    }
    if not list_only:
        checks["successfulSelectedMovementCall"] = len(selections) > 0
        checks["selectedHandleConversationCustomerBindingMatches"] = bool(selection_bindings) and all(selection_bindings)
    counts = {name:sum(1 for event in events if event.get("type")==name)
              for name in ["tool:call","tool:result","model:dispatch","model:dispatch-result","run:start","run:done"]}
    counts["toolMapEntries"] = len(tool_map)
    counts["exactMcpSessionRows"] = len(sessions)
    counts["exactLogEvents"] = len(events)
    counts["nativeSuccessfulBankToolCalls"] = len(native_successful)
    counts["verifiedListedHandleBindings"] = sum(listing_bindings)
    return {**checks, **counts, "successfulBankListCalls": len(listings), "successfulSelectedMovementCalls": len(selections),
            "verifiedSelectedHandleBindings": sum(selection_bindings), "auditPassed": all(checks.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--binding", required=True, type=Path)
    parser.add_argument("--list-only", action="store_true")
    args = parser.parse_args()
    try:
        result = audit(args.receipt, args.binding, args.list_only)
        print(json.dumps(result))
        return 0 if result["auditPassed"] else 1
    except Exception:
        print(json.dumps({"auditCompleted": False, "auditPassed": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
