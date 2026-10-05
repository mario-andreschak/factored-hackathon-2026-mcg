"""Read-only exact-session audit; only the root-owned /tmp binding is written."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
import time


def require(condition):
    if not condition:
        raise ValueError("Audit precondition failed")


def read_json(filename, private=False):
    metadata = filename.lstat()
    require(stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1)
    require(filename.resolve() == filename and metadata.st_size < 1024 * 1024)
    if private:
        require(metadata.st_uid == 0 and stat.S_IMODE(metadata.st_mode) == 0o600)
    with filename.open(encoding="utf-8") as source:
        value = json.load(source)
    require(isinstance(value, dict))
    return value


def database(filename):
    require(filename.is_file() and not filename.is_symlink())
    db = sqlite3.connect(filename.as_uri() + "?mode=ro", uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    db.execute("BEGIN")
    return db


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def receipt_at(filename):
    receipt = read_json(filename, private=True)
    require(receipt.get("version") == 1)
    require(isinstance(receipt.get("runId"), str) and len(receipt["runId"]) <= 128)
    require(re.fullmatch(r"[a-f0-9]{64}", receipt.get("bankSessionTokenHash", "")))
    return receipt


def bind(receipt, filename, state_dir):
    require(filename.parent == Path("/tmp") and filename.name.startswith("savia-verification-"))
    with database(state_dir / "frontend.sqlite3") as db:
        rows = db.execute("SELECT id,profile_id,expires_at FROM sessions WHERE token_hash=?",
                          (receipt["bankSessionTokenHash"],)).fetchall()
    require(len(rows) == 1 and rows[0]["expires_at"] > int(time.time()))
    row = rows[0]
    binding = {"version": 1, "runId": receipt["runId"],
               "bankSessionTokenHash": receipt["bankSessionTokenHash"],
               "sessionId": row["id"], "profileId": row["profile_id"],
               "expires": row["expires_at"]}
    if filename.exists() or filename.is_symlink():
        require(read_json(filename, private=True) == binding)
    else:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        descriptor = os.open(filename, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(binding, output)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
    return {"bindingSaved": True, "exactBrowserSessionCount": len(rows), "sessionUnexpired": True}


def worker_record(namespace, kind, session_id):
    filename = namespace / kind / (digest(session_id) + ".json")
    try:
        return read_json(filename)
    except FileNotFoundError:
        return None


def check(receipt, filename, state_dir):
    binding = read_json(filename, private=True)
    require(binding.get("version") == 1 and binding.get("runId") == receipt["runId"])
    require(binding.get("bankSessionTokenHash") == receipt["bankSessionTokenHash"])
    session_id, expires = binding["sessionId"], binding["expires"]
    require(isinstance(session_id, str) and 16 <= len(session_id) <= 128)
    require(type(expires) is int)
    with database(state_dir / "frontend.sqlite3") as db:
        browser_count = db.execute("SELECT COUNT(*) FROM sessions WHERE token_hash=? OR id=?",
                                   (receipt["bankSessionTokenHash"], session_id)).fetchone()[0]
        profiles = db.execute("SELECT customer_id FROM profiles WHERE id=?", (binding["profileId"],)).fetchall()
    with database(state_dir / "frontend-chat.sqlite3") as db:
        chats = db.execute("SELECT owner,expires,conversation_id,revoked,active_id,active_until,subject,customer_id "
                           "FROM chat_sessions WHERE session_id=?", (session_id,)).fetchall()
        revokes = db.execute("SELECT owner,subject,expires,state,lease_token,lease_until,last_error_code "
                             "FROM pending_revocations WHERE session_id=?", (session_id,)).fetchall()
        counts = {row["role"]: row["total"] for row in db.execute(
            "SELECT role,COUNT(*) AS total FROM chat_messages WHERE session_id=? GROUP BY role", (session_id,))}
    require(len(chats) == 1 and len(revokes) == 1 and len(profiles) == 1)
    chat, revoke = chats[0], revokes[0]
    policy = read_json(Path("/run/banking-runtime/policy.json"))
    frontend = read_json(Path("/run/frontend/frontend.json"))["chat"]
    namespace = Path(policy["stateDir"]) / digest(policy["deploymentId"])
    session = worker_record(namespace, "sessions", session_id)
    revoked = worker_record(namespace, "revoked", session_id)
    conversation = chat["conversation_id"]
    owner = worker_record(namespace, "owners", conversation) if isinstance(conversation, str) else None
    expected_owner = digest(json.dumps([frontend["frontend_issuer"], chat["subject"], frontend["model"]],
                                      separators=(",", ":")))
    checks = {
        "browserSessionRemoved": browser_count == 0,
        "exactFrontendSessionRevoked": chat["revoked"] == 1 and chat["expires"] == expires,
        "frontendSessionInactive": chat["active_id"] is None and chat["active_until"] == 0,
        "frontendIdentityMatches": profiles[0]["customer_id"] == chat["customer_id"]
            and frontend["principal_customers"].get(chat["subject"]) == chat["customer_id"]
            and frontend["frontend_issuer"] == policy["frontendIssuer"] and chat["owner"] == expected_owner,
        "exactWorkerRevokeConfirmed": revoke["state"] == "confirmed" and revoke["owner"] == chat["owner"]
            and revoke["subject"] == chat["subject"] and revoke["expires"] == expires,
        "revocationLeaseCleared": revoke["lease_token"] is None and revoke["lease_until"] == 0
            and revoke["last_error_code"] is None,
        "workerSessionBindingMatches": session == {"issuer": policy["frontendIssuer"],
            "subject": chat["subject"], "expires": expires},
        "workerRevocationPresent": revoked == {"revoked": True},
        "workerConversationOwnerMatches": owner == {"issuer": policy["frontendIssuer"],
            "subject": chat["subject"], "graph": policy["graphHash"],
            "deployment": policy["deploymentId"], "workspace": policy["workspace"]},
        "exactSessionUserMessagePresent": counts.get("user", 0) >= 1,
        "exactSessionAssistantMessagePresent": counts.get("assistant", 0) >= 1,
    }
    return {**checks, "exactFrontendSessionCount": len(chats), "exactRevocationCount": len(revokes),
            "exactSessionUserMessages": counts.get("user", 0),
            "exactSessionAssistantMessages": counts.get("assistant", 0), "auditPassed": all(checks.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["bind", "check"])
    parser.add_argument("--receipt", type=Path, default=Path("/tmp/savia-verification-session.json"))
    parser.add_argument("--binding", type=Path, default=Path("/tmp/savia-verification-binding.json"))
    args = parser.parse_args()
    try:
        require(sys.platform == "linux" and os.getuid() == 0)
        receipt = receipt_at(args.receipt)
        operation = bind if args.phase == "bind" else check
        result = operation(receipt, args.binding, Path("/data/frontend-state"))
        print(json.dumps(result))
        return 0 if result.get("auditPassed", True) else 1
    except Exception:
        # SQL, identity, configuration and key contents never enter diagnostics.
        print(json.dumps({"auditCompleted": False, "auditPassed": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
