"""Collect this repository's Codex conversations from read-only local storage.

No Codex process, credentials, or interactive app API is needed. The state DB is
only an index; scanning active and archived rollouts also finds unindexed chats.
Text is never shortened. System/developer instructions, reasoning, tool inputs
and outputs, encrypted blocks, and automatic ambient context are not exported.
"""

from __future__ import annotations

from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tomllib
from typing import Any


_UTC = timezone.utc
_AMBIENT_TAGS = (
    "environment_context", "recommended_plugins", "codex_internal_context",
    "external_codex_apps_open_page", "in-app-browser-context", "browser_context",
    "app_context", "image_context", "external_codex_apps_selected_text",
)
_SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\b(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|sk-(?:proj-)?[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[A-Z0-9]{16}|AIza[A-Za-z0-9_-]{30,})\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9_.~+/-]{12,}"),
    re.compile(r"(?i)((?:[\"']?)(?:[A-Za-z0-9_]*[_-])?(?:api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|auth[_-]?token|password|client[_-]?secret|secret[_-]?access[_-]?key|secret|token)(?:[\"']?)\s*[:=]\s*[\"']?)([^\s\"'`,;<>}{]{8,})"),
    re.compile(r"(?i)([?&](?:token|key|api_key|access_token|auth|password)=)[^&\s\"'<>]+"),
    re.compile(r"(?i)(https?://)[^/\s:@]+:[^/\s@]+@"),
]


def _redact(text: str, stats: Counter) -> str:
    for pattern in _SECRET_PATTERNS:
        def replacement(match: re.Match) -> str:
            stats["redactedValues"] += 1
            return (match.group(1) if match.lastindex else "") + "[REDACTED]"
        text = pattern.sub(replacement, text)
    return text


def _normal_path(value: Any) -> str:
    path = str(value or "").replace("\\", "/")
    if path.startswith("//?/UNC/"):
        path = "//" + path[8:]
    elif path.startswith("//?/"):
        path = path[4:]
    # Resolve native directory aliases (including Windows 8.3 names). The
    # repository is resolved by collectors, but stored cwd values may use the
    # runner's short-name TEMP path. Foreign-platform paths stay lexical.
    windows_path = bool(re.match(r"^[A-Za-z]:/", path) or path.startswith("//"))
    if (os.name == "nt" and windows_path) or (os.name != "nt" and path.startswith("/") and not windows_path):
        try:
            path = os.path.realpath(path)
        except (OSError, ValueError):
            return ""
    # Case-insensitive comparison is appropriate for Windows drive/UNC paths.
    path = os.path.normpath(path).replace("\\", "/").rstrip("/")
    return path.casefold() if re.match(r"^[A-Za-z]:/", path) or path.startswith("//") else path


def _inside(value: Any, root: Path) -> bool:
    candidate, target = _normal_path(value), _normal_path(root)
    return bool(value) and (candidate == target or candidate.startswith(target + "/"))


def _local_path(value: str) -> Path:
    return Path(value.removeprefix("\\\\?\\"))


def _utc(value: Any) -> str | None:
    """Normalize explicit source timestamps; never substitute filesystem times."""
    try:
        if isinstance(value, (int, float)):
            if value > 100_000_000_000:
                instant = datetime(1970, 1, 1, tzinfo=_UTC) + timedelta(milliseconds=value)
            else:
                instant = datetime(1970, 1, 1, tzinfo=_UTC) + timedelta(seconds=value)
            return instant.isoformat(timespec="microseconds").replace("+00:00", "Z")
        if not isinstance(value, str) or not value.strip():
            return None
        raw = value.strip()
        instant = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if instant.tzinfo is None:
            return None  # An unzoned date does not establish an exact UTC instant.
        instant = instant.astimezone(_UTC)
        # Preserve source fractional precision, including nanoseconds.
        fraction = re.search(r"[T ]\d{2}:\d{2}:\d{2}(\.\d+)", raw)
        return instant.strftime("%Y-%m-%dT%H:%M:%S") + (fraction.group(1) if fraction else "") + "Z"
    except (ValueError, TypeError, OverflowError):
        return None


def _epoch(timestamp: str) -> float:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()


def _time_key(timestamp: str) -> tuple[str, Decimal]:
    # ISO text with variable fractional precision is not lexically sortable:
    # .123Z sorts after .123456Z even though it is the earlier instant.
    return timestamp[:19], Decimal("0" + timestamp[19:-1]) if timestamp[19:-1] else Decimal(0)


def _text(content: Any, stats: Counter) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for part in content:
        if not isinstance(part, dict):
            continue
        kind = str(part.get("type", "")).lower()
        if kind in {"text", "input_text", "output_text"} and isinstance(part.get("text"), str):
            parts.append(part["text"])
        elif kind in {"image", "input_image", "image_url", "local_image", "audio", "input_audio", "video"}:
            stats["attachmentsSkipped"] += 1
            parts.append(f"[{kind.replace('_', ' ')} attachment]")
        elif "encrypted" in kind:
            stats["encryptedPartsSkipped"] += 1
    return "\n\n".join(parts)


def _human_text(text: str) -> str:
    for tag in _AMBIENT_TAGS:
        text = re.sub(r"<" + re.escape(tag) + r"\b[^>]*>[\s\S]*?</" + re.escape(tag) + r">", "", text, flags=re.I)
        text = re.sub(r"<" + re.escape(tag) + r"\b[^>]*/>", "", text, flags=re.I)
    return text.strip()


def _read_index(home: Path, repo: Path, notes: list[str]) -> dict[str, dict]:
    indexed = {}
    # The newest state schema is preferred; an older DB is a fallback only.
    databases = sorted((path for path in home.glob("state_*.sqlite") if re.fullmatch(r"state_\d+\.sqlite", path.name)), key=lambda p: int(re.search(r"(\d+)\.sqlite$", p.name).group(1)), reverse=True)
    safe_fields = {"id", "rollout_path", "cwd", "name", "title", "source", "archived", "agent_nickname", "agent_path", "created_at_ms", "created_at"}
    for database in databases:
        try:
            with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)) as connection:
                connection.execute("PRAGMA query_only = ON")
                columns = {row[1] for row in connection.execute("PRAGMA table_info(threads)")}
                if not {"id", "cwd"}.issubset(columns):
                    continue
                fields = sorted(safe_fields & columns)
                for row in connection.execute("SELECT " + ",".join(fields) + " FROM threads"):
                    record = dict(zip(fields, row))
                    if _inside(record.get("cwd"), repo):
                        indexed[str(record["id"])] = record
            break
        except (sqlite3.Error, OSError) as error:
            notes.append(f"Could not read Codex state index {database.name}: {type(error).__name__}; scanning rollouts instead.")
    title_file = home / "session_index.jsonl"
    if title_file.exists():
        try:
            with title_file.open(encoding="utf-8-sig") as handle:
                for line in handle:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(entry, dict) and entry.get("id") in indexed and entry.get("thread_name"):
                        indexed[entry["id"]]["index_name"] = entry["thread_name"]
        except OSError:
            notes.append("Codex session title index was not readable; rollout messages remain available.")
    return indexed


def _first_meta(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8-sig") as handle:
            for _, line in zip(range(32), handle):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict) and record.get("type") == "session_meta" and isinstance(record.get("payload"), dict):
                    return record["payload"]
    except OSError:
        pass
    return {}


def _discovery(home: Path, repo: Path, options: dict, notes: list[str]) -> tuple[list[tuple[Path, dict]], dict]:
    index = _read_index(home, repo, notes)
    known = {_normal_path(row["rollout_path"]): row for row in index.values() if row.get("rollout_path")}
    paths: dict[str, Path] = {}
    roots = [home / "sessions", home / "archived_sessions"]
    roots.extend(Path(value).expanduser() for value in options.get("extra_roots", []))
    for root in roots:
        if root.is_file():
            paths[_normal_path(root)] = root
        elif root.is_dir():
            for path in root.rglob("*.jsonl"):
                paths[_normal_path(path)] = path
    for row in index.values():
        if row.get("rollout_path"):
            path = _local_path(row["rollout_path"])
            if path.is_file():
                paths[_normal_path(path)] = path
    selected = []
    found_ids = set()
    for key, path in sorted(paths.items()):
        meta = _first_meta(path)
        indexed = index.get(str(meta.get("id"))) or known.get(key) or {}
        if _inside(meta.get("cwd"), repo) or _inside(indexed.get("cwd"), repo):
            combined = {**indexed, **meta}
            if not combined.get("id"):
                notes.append(f"Skipped rollout without a thread ID: {path.name}.")
                continue
            # Keep the app's current title even if initial metadata contains no title.
            combined["display_name"] = indexed.get("name") or indexed.get("index_name") or indexed.get("title") or meta.get("title")
            combined["archived"] = bool(indexed.get("archived")) or "archived_sessions" in path.parts
            selected.append((path, combined))
            found_ids.add(str(combined["id"]))
    missing = sorted(set(index) - found_ids)
    if missing:
        notes.append(f"{len(missing)} indexed project chats have no readable local rollout; ephemeral, deleted, or remote-only chats cannot be recovered from this machine.")
    selected.sort(key=lambda pair: (pair[1].get("timestamp") or "", str(pair[0])))
    return selected, {"indexedThreads": len(index), "rolloutsScanned": len(paths), "missingIndexedSessions": len(missing)}


def _phase(payload: dict) -> str:
    value = str(payload.get("phase") or payload.get("channel") or "").lower().replace("-", "_")
    return "final" if value in {"final_answer", "finalanswer"} else value


def _candidate(record: dict, line: int, stats: Counter) -> dict | None:
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return None
    container, kind = record.get("type"), payload.get("type")
    representation, role, phase, item_id = "", "", "", None
    content = None
    if container == "response_item" and kind == "message":
        role, content = payload.get("role", ""), payload.get("content")
        phase, item_id, representation = _phase(payload), payload.get("id"), "response_item"
    elif container == "event_msg" and kind == "item_completed":
        item = payload.get("item", {})
        if not isinstance(item, dict):
            return None
        if item.get("type") not in {"UserMessage", "AgentMessage"}:
            return None
        role = "user" if item["type"] == "UserMessage" else "assistant"
        content, phase, item_id, representation = item.get("content"), _phase(item), item.get("id"), "item_completed"
    elif container == "event_msg" and kind in {"user_message", "agent_message"}:
        role = "user" if kind == "user_message" else "assistant"
        content, phase, item_id, representation = payload.get("message"), _phase(payload), payload.get("id"), "event_msg"
    elif container == "event_msg" and kind == "task_complete" and payload.get("last_agent_message"):
        role, phase, content, representation = "assistant", "final", payload["last_agent_message"], "task_complete"
    else:
        return None
    if role not in {"user", "assistant"} or phase in {"analysis", "reasoning", "summary"}:
        return None
    body = _text(content, stats)
    if role == "user":
        body = _human_text(body)
    if not body.strip():
        stats["ambientMessagesSkipped"] += 1
        return None
    raw_timestamp = record.get("timestamp") or payload.get("completed_at_ms") or payload.get("timestamp")
    timestamp = _utc(raw_timestamp)
    if not timestamp:
        stats["missingTimestamps"] += 1
        return None
    return {"role": role, "phase": phase, "body": body, "timestamp": timestamp, "rawTimestamp": raw_timestamp,
            "itemId": item_id, "representation": representation, "line": line, "ordinal": record.get("ordinal"),
            "turnId": payload.get("turn_id")}


def _messages(path: Path, meta: dict, stats: Counter, tool_counts: Counter, seen_tool_calls: set) -> tuple[list[dict], list[dict]]:
    candidates, tools = [], []
    thread_id = str(meta["id"])
    boundary = meta.get("subagent_history_start_ordinal")
    creation = _utc(meta.get("timestamp"))
    try:
        with path.open(encoding="utf-8-sig") as handle:
            for line_number, line in enumerate(handle, 1):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    stats["malformedLines"] += 1
                    continue
                if not isinstance(record, dict):
                    continue
                ordinal = record.get("ordinal")
                if isinstance(boundary, int) and isinstance(ordinal, int) and ordinal < boundary:
                    stats["inheritedRecordsSkipped"] += 1
                    continue
                payload = record.get("payload", {})
                if not isinstance(payload, dict):
                    continue
                # Old full-history forks copy parent records into the new file.
                timestamp = _utc(record.get("timestamp"))
                if meta.get("forked_from_id") and creation and timestamp and _epoch(timestamp) < _epoch(creation):
                    stats["inheritedRecordsSkipped"] += 1
                    continue
                if record.get("type") == "response_item" and payload.get("type") in {"function_call", "custom_tool_call"}:
                    key = payload.get("call_id") or payload.get("id") or f"{thread_id}:{ordinal}:{line_number}"
                    if key not in seen_tool_calls:
                        seen_tool_calls.add(key)
                        name = str(payload.get("name") or "tool")
                        tool_counts[name] += 1
                        stats["toolActions"] += 1
                        if timestamp:
                            tools.append({"key": key, "name": name, "timestamp": timestamp, "rawTimestamp": record.get("timestamp"), "line": line_number, "ordinal": ordinal})
                candidate = _candidate(record, line_number, stats)
                if candidate:
                    candidates.append(candidate)
    except (OSError, UnicodeError):
        stats["unreadableFiles"] += 1
        return [], []
    # Prefer the original persisted response; item-completed is an app projection
    # with another timestamp and, for user messages, sometimes a different ID.
    preference = {"response_item": 0, "item_completed": 1, "event_msg": 2, "task_complete": 3}
    candidates.sort(key=lambda item: (preference[item["representation"]], item["line"]))
    unique, by_id, by_text = [], {}, {}
    for candidate in candidates:
        identity = candidate["itemId"]
        signature = (candidate["role"], candidate["body"])
        prior = by_id.get(identity) if identity else None
        if prior is None:
            for possible in by_text.get(signature, []):
                if possible["representation"] != candidate["representation"] and abs(_epoch(possible["timestamp"]) - _epoch(candidate["timestamp"])) <= 3:
                    prior = possible
                    break
        if prior:
            if candidate["representation"] == "task_complete" and not prior["phase"]:
                prior["phase"] = "final"
            if candidate["turnId"] and not prior["turnId"]:
                prior["turnId"] = candidate["turnId"]
            if len(candidate["body"]) > len(prior["body"]) and candidate["body"].startswith(prior["body"]):
                prior["body"] = candidate["body"]
            stats["duplicates"] += 1
            continue
        unique.append(candidate)
        if identity:
            by_id[identity] = candidate
        by_text.setdefault(signature, []).append(candidate)
    return sorted(unique, key=lambda item: (_time_key(item["timestamp"]), item["line"])), tools


def _schedule(rule: Any, prompt: str) -> str:
    """Describe the saved schedule without turning it into executable actions."""
    values = {}
    for component in str(rule or "").removeprefix("RRULE:").split(";"):
        if "=" in component:
            key, value = component.split("=", 1)
            values[key] = value
    frequency = values.get("FREQ", "")
    interval = values.get("INTERVAL", "1")
    zone = re.search(r"\b(?:America|Europe|Asia|Africa|Australia|Pacific)/[A-Za-z_+-]+(?:/[A-Za-z_+-]+)?", prompt)
    suffix = f" ({zone.group(0)})" if zone else ""
    if frequency == "HOURLY":
        description = "Every hour" if interval == "1" else f"Every {interval} hours"
        if "BYMINUTE" in values:
            description += " at minutes " + values["BYMINUTE"]
    elif frequency == "DAILY":
        description = "Daily" if interval == "1" else f"Every {interval} days"
        if "BYHOUR" in values:
            description += f" at {values['BYHOUR'].zfill(2)}:{values.get('BYMINUTE', '0').zfill(2)}"
        if values.get("COUNT") == "1":
            description = "One scheduled occurrence" + (" on month " + values["BYMONTH"] if "BYMONTH" in values else "") + (", day " + values["BYMONTHDAY"] if "BYMONTHDAY" in values else "") + (" at " + values["BYHOUR"].zfill(2) + ":" + values.get("BYMINUTE", "0").zfill(2) if "BYHOUR" in values else "")
    elif frequency:
        description = f"Every {interval} {frequency.lower()} period(s)"
    else:
        description = "Schedule available in the saved automation configuration"
    return description + suffix


def _automations(home: Path, repo: Path, thread_ids: set[str], stats: Counter, notes: list[str]) -> tuple[list[dict], list[dict]]:
    automations, events = [], []
    for path in sorted((home / "automations").glob("*/automation.toml")):
        try:
            saved = tomllib.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError):
            stats["unreadableAutomationFiles"] += 1
            continue
        prompt, name = str(saved.get("prompt") or ""), str(saved.get("name") or path.parent.name)
        cwds = saved.get("cwds") or ([saved["cwd"]] if saved.get("cwd") else [])
        if isinstance(cwds, str):
            cwds = [cwds]
        target = saved.get("target_thread_id")
        explicit = bool(re.search(r"factored[- ]hackathon[- ]2026|hackathon.{0,80}\b(?:ci|release|supervis(?:e|or|ion)|prs?|pull.requests?)\b", name + "\n" + prompt, re.I | re.S))
        if not (any(_inside(cwd, repo) for cwd in cwds) or target in thread_ids or explicit):
            continue
        identity = str(saved.get("id") or path.parent.name)
        prompt, name = _redact(prompt, stats), _redact(name, stats)
        created, updated = _utc(saved.get("created_at")), _utc(saved.get("updated_at"))
        automation = {"id": identity, "name": name, "kind": saved.get("kind"), "prompt": prompt,
                      "schedule": _schedule(saved.get("rrule"), prompt), "status": saved.get("status"), "cwds": cwds,
                      "targetThreadId": target, "createdAt": created, "updatedAt": updated,
                      "configurationIsCurrentSnapshot": True}
        automations.append(automation)
        for action, timestamp, field in (("created", created, "created_at"), ("updated", updated, "updated_at")):
            if not timestamp or (action == "updated" and timestamp == created):
                continue
            body = f"Saved automation {action}: {name}.\n\nCurrent saved schedule: {automation['schedule']}\nStatus: {automation['status']}\n\n{prompt}\n\nThe settings shown are the current saved configuration; this file does not retain earlier revisions or prove any scheduled run completed."
            events.append({"id": f"codex:automation:{identity}:{action}:{timestamp}", "timestamp": timestamp, "source": "codex", "kind": f"automation_{action}",
                           "title": f"{name} · Automation {action}", "body": body, "actor": "Codex automation", "url": f"codex://threads/{target}" if target else None,
                           "threadId": target, "tags": ["automation", "schedule", str(saved.get("kind") or "automation")],
                           "metadata": {"automationId": identity, "schedule": automation["schedule"], "status": automation["status"], "targetThreadId": target,
                                        "configurationPath": str(path), "timestampField": field, "rawTimestamp": saved.get(field), "configurationIsCurrentSnapshot": True}})
    if stats["unreadableAutomationFiles"]:
        notes.append("Some saved automation configurations were unreadable and could not be checked for project scope.")
    stats["automations"] = len(automations)
    stats["automationEvents"] = len(events)
    return automations, events


def collect(repo: Path, config: dict) -> dict:
    """Return canonical timestamped messages and source-coverage diagnostics.

    Options under ``codex``: ``home``, ``extra_roots``, ``include_tools`` (false),
    and ``user_actor``. ``codex_home`` is accepted as a flat compatibility option.
    """
    repo = Path(repo).resolve()
    options = config.get("codex", {}) if isinstance(config.get("codex", {}), dict) else {}
    home = Path(options.get("home") or config.get("codex_home") or os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
    notes: list[str] = []
    stats = Counter()
    if not home.is_dir():
        return {"events": [], "threads": [], "automations": [], "status": "unavailable", "notes": ["Codex local storage is not available; configure codex.home or CODEX_HOME."], "stats": {"threads": 0, "messages": 0}}
    files, discovery = _discovery(home, repo, options, notes)
    stats.update(discovery)
    stats["files"] = len(files)
    events, threads, seen_events, thread_index = [], [], {}, {}
    tool_counts = Counter()
    seen_tool_calls: set = set()
    user_actor = str(options.get("user_actor") or Path.home().name or "User")
    for path, meta in files:
        thread_id = str(meta["id"])
        title = str(meta.get("display_name") or meta.get("agent_path") or meta.get("agent_nickname") or "Codex chat " + thread_id[:8])
        title = _redact(re.sub(r"\s+", " ", title).strip()[:160], stats)
        source = meta.get("source", "")
        if isinstance(source, str) and source.startswith("{"):
            try:
                source = json.loads(source)
            except json.JSONDecodeError:
                pass
        spawn = source.get("subagent", {}).get("thread_spawn", {}) if isinstance(source, dict) else {}
        parent_id = meta.get("parent_thread_id") or spawn.get("parent_thread_id")
        subagent = bool(parent_id or meta.get("agent_path") or spawn)
        archived = bool(meta.get("archived"))
        messages, tools = _messages(path, meta, stats, tool_counts, seen_tool_calls)
        thread = {"id": thread_id, "title": title, "createdAt": _utc(meta.get("timestamp")) or _utc(meta.get("created_at_ms") or meta.get("created_at")),
                  "url": f"codex://threads/{thread_id}", "archived": archived, "subagent": subagent,
                  "parentThreadId": parent_id, "forkedFromId": meta.get("forked_from_id"), "agentPath": meta.get("agent_path") or spawn.get("agent_path"),
                  "agentNickname": meta.get("agent_nickname") or spawn.get("agent_nickname"), "agentRole": meta.get("agent_role") or spawn.get("agent_role"), "messageCount": 0, "toolCount": 0}
        if thread_id not in thread_index:
            thread_index[thread_id] = thread
            threads.append(thread)
        thread = thread_index[thread_id]
        thread["toolCount"] += len(tools)
        for message in messages:
            identity = message["itemId"] or hashlib.sha256(f"{thread_id}\0{message['ordinal']}\0{message['timestamp']}\0{message['role']}\0{message['body']}".encode()).hexdigest()[:32]
            event_id = "codex:message:" + str(identity)
            if event_id in seen_events:
                stats["duplicates"] += 1
                observed = seen_events[event_id]["metadata"].setdefault("alsoSeenInThreads", [])
                if thread_id not in observed:
                    observed.append(thread_id)
                continue
            body = _redact(message["body"], stats)
            role, phase = message["role"], message["phase"]
            label = "User message" if role == "user" else ("Final response" if phase == "final" else "Development update")
            kind = "user_message" if role == "user" else ("assistant_final" if phase == "final" else "assistant_message")
            tags = ["conversation", role]
            if phase:
                tags.append(phase)
            if subagent:
                tags.append("subagent")
            if archived:
                tags.append("archived")
            event = {"id": event_id, "timestamp": message["timestamp"], "source": "codex", "kind": kind,
                     "title": f"{title} · {label}", "body": body, "actor": user_actor if role == "user" else "Codex",
                     "url": thread["url"], "threadId": thread_id, "tags": tags,
                     "metadata": {"threadTitle": title, "role": role, "phase": phase or None, "itemId": message["itemId"], "turnId": message["turnId"],
                                  "rolloutPath": str(path), "line": message["line"], "ordinal": message["ordinal"], "rawTimestamp": message["rawTimestamp"],
                                  "representation": message["representation"], "parentThreadId": parent_id, "forkedFromId": meta.get("forked_from_id"),
                                  "agentPath": thread["agentPath"], "agentNickname": thread["agentNickname"], "agentRole": thread["agentRole"]}}
            events.append(event)
            seen_events[event_id] = event
            stats["messages"] += 1
            stats["userMessages" if role == "user" else "assistantMessages"] += 1
            thread["messageCount"] += 1
        if options.get("include_tools", False):
            for tool in tools:
                event_id = "codex:tool:" + str(tool["key"])
                if event_id in seen_events:
                    stats["duplicates"] += 1
                    continue
                name = _redact(tool["name"], stats)
                event = {"id": event_id, "timestamp": tool["timestamp"], "source": "codex", "kind": "tool_action", "title": f"{title} · {name}",
                         "body": f"Codex called {name}. Tool arguments and outputs are omitted from the timeline.", "actor": "Codex", "url": thread["url"], "threadId": thread_id,
                         "tags": ["tool", name], "metadata": {"threadTitle": title, "tool": name, "rolloutPath": str(path), "line": tool["line"], "ordinal": tool["ordinal"], "rawTimestamp": tool["rawTimestamp"]}}
                events.append(event)
                seen_events[event_id] = event
    automations, automation_events = _automations(home, repo, set(thread_index), stats, notes)
    events.extend(automation_events)
    stats["threads"] = len(threads)
    stats["subagentThreads"] = sum(thread["subagent"] for thread in threads)
    stats["archivedThreads"] = sum(thread["archived"] for thread in threads)
    stats["events"] = len(events)
    for key in ("messages", "userMessages", "assistantMessages", "toolActions", "duplicates", "malformedLines", "missingTimestamps", "unreadableFiles", "attachmentsSkipped", "redactedValues", "inheritedRecordsSkipped"):
        stats.setdefault(key, 0)
    if stats["malformedLines"]:
        notes.append(f"Skipped {stats['malformedLines']} malformed JSONL records (an actively written final line may be incomplete); rerun to refresh.")
    if stats["missingTimestamps"]:
        notes.append(f"Skipped {stats['missingTimestamps']} messages without an explicit zoned timestamp; no dates were fabricated.")
    if stats["unreadableFiles"]:
        notes.append(f"{stats['unreadableFiles']} selected rollouts could not be read completely.")
    if stats["encryptedPartsSkipped"]:
        notes.append(f"{stats['encryptedPartsSkipped']} encrypted message blocks could not be exported; readable message text is retained.")
    notes.append("Coverage is this machine's active and archived project rollouts, including forks and subagents. Other teammates' local, cloud-only, ephemeral, and deleted chats require their own export.")
    notes.append("Message bodies are full text with credentials redacted. Hidden reasoning, system/developer instructions, automatic ambient context, and tool payloads are excluded.")
    status = "partial" if any(stats[key] for key in ("missingIndexedSessions", "malformedLines", "missingTimestamps", "unreadableFiles", "encryptedPartsSkipped", "unreadableAutomationFiles")) else ("ok" if files or automations else "unavailable")
    if not files:
        notes.append("No local Codex chats matched this repository's working directory.")
    return {"events": sorted(events, key=lambda event: (_time_key(event["timestamp"]), event["id"])), "threads": threads,
            "automations": automations, "status": status, "notes": notes, "stats": dict(stats), "toolCounts": dict(sorted(tool_counts.items()))}
