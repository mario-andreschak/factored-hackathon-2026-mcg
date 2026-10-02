"""Apply the development-history time window without inventing lifecycle dates.

Collectors and offline caches share this policy. Cross-source evidence can be
provided through ``_history_event_timestamps`` and ``_history_excluded_event_ids``
in config: an unknown reference is kept until dated evidence excludes it.
"""
from __future__ import annotations

from datetime import datetime

from .common import timestamp


DEFAULT_HISTORY_START = "2026-09-25T00:00:00-05:00"
_REF_LISTS = {"eventIds", "evidenceEventIds", "evidenceSourceEventIds", "evidenceIds"}
_REF_SINGLES = {"eventId", "evidenceEventId", "fromEventId", "toEventId"}
_SESSION_FIELDS = {"sessionId", "executingSessionId", "observedInSessionId", "targetSessionId"}


def _epoch(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return datetime.fromisoformat(timestamp(value).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def _trim_refs(row, excluded):
    """Copy only records being changed; never edit a cached source dictionary."""
    clean = dict(row)
    for key in _REF_LISTS:
        if isinstance(row.get(key), list):
            clean[key] = [identity for identity in row[key] if identity not in excluded]
    for key in _REF_SINGLES:
        if row.get(key) in excluded:
            clean.pop(key, None)
    return clean


def _recent(row, cutoff, fields):
    dates = [_epoch(row.get(field)) for field in fields]
    return any(value is not None and value >= cutoff for value in dates)


def _unknown_dates(row, fields):
    return not any(_epoch(row.get(field)) is not None for field in fields)


def _has_evidence(row):
    return any(row.get(key) for key in _REF_LISTS | _REF_SINGLES)


def _prune_topology(result, excluded, cutoff):
    originally_referenced_flows = {row.get("flowId") for row in result.get("sessions", [])}
    originally_referenced_flows.update(row.get("flowId") for row in result.get("agentEdges", []))
    sessions = [_trim_refs(row, excluded) for row in result.get("sessions", [])]
    by_id = {row["id"]: row for row in sessions if row.get("id")}
    active = set()
    for event in result.get("events", []):
        metadata = event.get("metadata") or {}
        active.update(metadata[field] for field in _SESSION_FIELDS if metadata.get(field) in by_id)

    edges = []
    for row in result.get("agentEdges", []):
        time = _epoch(row.get("timestamp"))
        if time is not None and time < cutoff:
            continue
        edge = _trim_refs(row, excluded)
        # An undated edge with only excluded evidence cannot assert an action.
        if time is None and _has_evidence(row) and not _has_evidence(edge):
            continue
        edges.append(edge)
        active.update(edge[field] for field in ("from", "to", "sessionId") if edge.get(field) in by_id)

    session_dates = ("startedAt", "lastActivityAt", "endedAt")
    for session in sessions:
        activity = []
        for item in session.get("nodeActivity", []):
            time = _epoch(item.get("timestamp"))
            if item.get("eventId") in excluded or (time is not None and time < cutoff):
                continue
            activity.append(dict(item))
        if "nodeActivity" in session:
            session["nodeActivity"] = activity
        if "eventCount" in session:
            session["eventCount"] = len(session.get("eventIds", []))
        if _has_evidence(session) or activity or _recent(session, cutoff, session_dates) or _unknown_dates(session, session_dates):
            if session.get("id"):
                active.add(session["id"])

    keep = set(active)
    # A surviving child needs its actual parent even when the parent last spoke
    # before the window. This is lifecycle context, with old messages removed.
    pending = list(keep)
    while pending:
        parent = by_id.get(pending.pop(), {}).get("parentId")
        if parent in by_id and parent not in keep:
            keep.add(parent)
            pending.append(parent)
    kept_sessions = []
    for session in sessions:
        if session.get("id") not in keep:
            continue
        if session["id"] not in active:
            session["historyContextOnly"] = True
        else:
            session.pop("historyContextOnly", None)
        kept_sessions.append(session)
    result["sessions"] = kept_sessions
    result["agentEdges"] = edges

    required_flows = {row.get("flowId") for row in kept_sessions if row.get("flowId")}
    required_flows.update(row.get("flowId") for row in edges if row.get("flowId"))
    required_flows.update((row.get("metadata") or {}).get("flowId") for row in result.get("events", []))
    flows = []
    for row in result.get("flows", []):
        flow = _trim_refs(row, excluded)
        if row.get("id") in originally_referenced_flows and row.get("id") not in required_flows and not _has_evidence(flow):
            continue
        if row.get("id") in required_flows or _has_evidence(flow) or _recent(row, cutoff, ("availableFrom",)) or _unknown_dates(row, ("availableFrom",)):
            flows.append(flow)
    result["flows"] = flows
    if isinstance(result.get("stats"), dict):
        stats = dict(result["stats"])
        stats.update(sessions=len(kept_sessions), agentEdges=len(edges), flowGraphs=len(flows), executionEvents=len(result.get("events", [])))
        for source in ("codex", "flujo"):
            if source + "Sessions" in stats:
                stats[source + "Sessions"] = sum(row.get("source") == source for row in kept_sessions)
        result["stats"] = stats


def _prune_infrastructure(result, excluded, cutoff):
    for key in ("builds", "deployments", "machines"):
        if key not in result:
            continue
        records = []
        fields = ("timestamp", "startedAt", "finishedAt") if key != "machines" else ("createdAt", "firstTimestamp", "lastObservedAt")
        for row in result.get(key, []):
            clean = _trim_refs(row, excluded)
            if _has_evidence(clean) or _recent(row, cutoff, fields) or _unknown_dates(row, fields):
                records.append(clean)
        result[key] = records
    if isinstance(result.get("stats"), dict):
        stats = dict(result["stats"])
        for key in ("builds", "deployments", "machines"):
            if key in result and key in stats:
                stats[key] = len(result[key])
        result["stats"] = stats


def _prune_documents(result, excluded, cutoff):
    documents = []
    for row in result.get("documents", []):
        if not isinstance(row.get("revisions"), list):
            documents.append(row)
            continue
        revisions = []
        for revision in row["revisions"]:
            time = _epoch(revision.get("timestamp"))
            if revision.get("eventId") in excluded or (time is not None and time < cutoff):
                continue
            revisions.append(dict(revision))
        if revisions or _recent(row, cutoff, ("firstObservedAt",)):
            documents.append({**row, "revisions": revisions})
    result["documents"] = documents


def _prune_threads(result, cutoff):
    rows = result.get("threads", [])
    by_id = {row["id"]: row for row in rows if row.get("id")}
    keep = {row.get("threadId") for row in result.get("events", [])}
    keep.update(row["id"] for row in rows if row.get("id") and (_recent(row, cutoff, ("createdAt", "updatedAt")) or _unknown_dates(row, ("createdAt", "updatedAt"))))
    pending = list(keep)
    while pending:
        row = by_id.get(pending.pop(), {})
        for field in ("parentThreadId", "forkedFromId"):
            parent = row.get(field)
            if parent in by_id and parent not in keep:
                keep.add(parent)
                pending.append(parent)
    result["threads"] = [row for row in rows if row.get("id") in keep]
    if isinstance(result.get("stats"), dict) and "threads" in result["stats"]:
        result["stats"] = {**result["stats"], "threads": len(result["threads"])}


def history_start(config=None):
    """Return the configured start in UTC with six fractional digits."""
    start = (config or {}).get("history_start", DEFAULT_HISTORY_START)
    if _epoch(start) is None:
        raise ValueError("history_start must be a valid timezone-aware timestamp")
    return timestamp(start)


def apply_history_start(result, config=None):
    """Return history at/after the configured inclusive, timezone-aware start.

    Undated records and unknown evidence references remain as unknown context;
    dated messages before the cutoff never survive. Real creation times on
    active sessions and machines stay unchanged. ``scopeExcludedEventIds`` holds
    only excluded IDs, so separate topology caches can use the same exclusions.
    """
    config = config or {}
    start = history_start(config)
    cutoff = _epoch(start)
    if cutoff is None:
        raise ValueError("history_start must be a valid timezone-aware timestamp")
    scoped = dict(result)
    previous_start = result.get("historyStart")
    # Exclusions describe one window. An earlier live refresh may return rows
    # that are now eligible, so IDs excluded by a different window cannot veto
    # that fresh evidence. Legacy IDs without a policy date belong only to the
    # default window; keep them for repeat/offline default rebuilds.
    same_window = _epoch(previous_start) == cutoff or (previous_start is None and cutoff == _epoch(DEFAULT_HISTORY_START))
    excluded = set(result.get("scopeExcludedEventIds") or []) if same_window else set()
    excluded.update(config.get("_history_excluded_event_ids") or [])
    for identity, value in (config.get("_history_event_timestamps") or {}).items():
        time = _epoch(value)
        if time is not None and time < cutoff:
            excluded.add(identity)

    events = []
    for event in result.get("events", []):
        time = _epoch(event.get("timestamp"))
        if (time is not None and time < cutoff) or event.get("id") in excluded:
            if event.get("id"):
                excluded.add(event["id"])
            continue
        # Metadata can include references to observations excluded elsewhere.
        if isinstance(event.get("metadata"), dict):
            clean = _trim_refs(event["metadata"], excluded)
            events.append({**event, "metadata": clean})
        else:
            events.append(event)
    # Exclusions discovered late in source order still trim earlier evidence.
    scoped["events"] = [{**event, "metadata": _trim_refs(event["metadata"], excluded)} if isinstance(event.get("metadata"), dict) else event for event in events]
    scoped["historyStart"] = start
    scoped["scopeExcludedEventIds"] = sorted(identity for identity in excluded if isinstance(identity, str))
    if "sessions" in scoped or "agentEdges" in scoped or "flows" in scoped:
        _prune_topology(scoped, excluded, cutoff)
    if any(key in scoped for key in ("machines", "builds", "deployments")):
        _prune_infrastructure(scoped, excluded, cutoff)
    if "documents" in scoped:
        _prune_documents(scoped, excluded, cutoff)
    if "threads" in scoped:
        _prune_threads(scoped, cutoff)
    if isinstance(scoped.get("stats"), dict):
        stats = dict(scoped["stats"])
        stats["historyExcludedEvents"] = len(scoped["scopeExcludedEventIds"])
        if "messages" in stats:
            stats["messages"] = len(scoped["events"])
        if "events" in stats:
            stats["events"] = len(scoped["events"])
        scoped["stats"] = stats
    return scoped
