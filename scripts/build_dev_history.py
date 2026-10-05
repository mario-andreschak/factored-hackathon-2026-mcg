#!/usr/bin/env python3
"""Rebuild the offline development archive from read-only source adapters."""
from __future__ import annotations

import argparse
import base64
from bisect import bisect_right
import gzip
import hashlib
import importlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from history_sources.common import sanitize, timestamp
from history_sources.slack import allowed_channel, allowed_event
from history_sources.privacy import scrub_embedded_slack
from history_sources.scope import apply_history_start, history_start

REPO = Path(__file__).resolve().parents[1]
SOURCES = {"github": "GitHub", "slack": "Slack", "codex": "Codex", "flujo": "FLUJO", "docs": "Project docs", "infrastructure": "Machines & builds"}
WORKSTREAMS = {
    "backend": ("Backend", r"\b(backend|fastapi|endpoint|auth(?:entication|orization)?|ownership|server|session|revocation|principal|sqlite)\b"),
    "mcp": ("MCP", r"\b(mcp|tools/call|tool.?transport|streamable|banking_mcp|sdk)\b"),
    "dataset": ("Dataset", r"\b(dataset|duckdb|parquet|silver|bronze|gold|data.?pipeline|data.?contract|s3|classifier|tf.idf|training|labeling)\b"),
    "frontend": ("Frontend", r"\b(frontend|savia|portal|avatar|react|vite|lip.sync|ui|interface|portuguese|language.?switch)\b"),
    "deployment": ("Deployment", r"\b(deploy\w*|fly.io|flyctl|docker|gateway|hosting|production|migration|cloud|oom|ram)\b"),
    "review": ("Review", r"\b(review\w*|audit\w*|verif\w*|test\w*|pytest|vitest|quality|supervis\w*|merge\w*|readiness)\b"),
    "steering": ("Steering", r"\b(orchestrat\w*|supervisor|agent\w*|task\w*|priorit\w*|steer\w*|team|plan\w*|handoff|slack|subflow|deadline|scope)\b"),
    "ci": ("CI & automations", r"\b(ci|continuous.?integration|modal|cron|automat\w*|scheduler|hourly|daily|workflow.run|github.?actions)\b"),
    "research": ("Research", r"\b(research\w*|kick.?off|hackathon|challenge|rules|explor\w*|competitor|requirement\w*|feasibility)\b"),
}


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(path)


def private_result(source, result, config):
    """Privacy exclusions override retention, including old/offline captures."""
    result = apply_history_start(result, config)
    if source == "slack":
        result = dict(result)
        before = result.get("events", [])
        result["events"] = [event for event in before if allowed_event(event, config)]
        if isinstance(result.get("channels"), list):
            result["channels"] = [channel for channel in result["channels"] if allowed_channel(channel, config)]
        stats = dict(result.get("stats", {}))
        stats["messages"] = len(result["events"])
        if "channels" in result:
            stats["channels"] = len(result["channels"])
        stats["privacyExcludedEvents"] = stats.get("privacyExcludedEvents", 0) + len(before) - len(result["events"])
        result["stats"] = stats
        result["privacyPolicy"] = "No direct/group direct messages; no find-a-team, challenge-help or technical-help; contact details redacted."
    return sanitize(scrub_embedded_slack(result, config))


def read_private_cache(file, source, config):
    saved = json.loads(file.read_text(encoding="utf-8"))
    clean = {**saved, "result": private_result(source, saved["result"], config)}
    # Purge old private records even when the source is offline or unavailable.
    # Redaction must not masquerade as a newer source observation.
    if clean != saved:
        atomic_json(file, clean)
    return clean


def source_result(source, config, cache, offline):
    file = cache / (source + ".json")
    if offline:
        if not file.exists():
            return {"events": [], "status": "unavailable", "notes": ["No cached snapshot. Run a live rebuild first."]}
        saved = read_private_cache(file, source, config)
        result = saved["result"]
        result["cachedAt"] = saved["collectedAt"]
        result["notes"] = [*result.get("notes", []), "Using the saved source snapshot from " + saved["collectedAt"]]
        return result
    try:
        adapter = importlib.import_module("history_sources." + source)
        result = adapter.collect(REPO, config)
    except Exception as error:
        result = {"events": [], "status": "unavailable", "notes": [f"Collector failed: {type(error).__name__}: {str(error)[:180]}"]}
    result = private_result(source, result, config)
    if source == "slack":
        observed = datetime.now(timezone.utc).isoformat()
        for event in result.get("events", []):
            if event.get("metadata", {}).get("reactions"):
                event["metadata"]["reactionObservedAt"] = observed
    # On source failure, keep the last good source snapshot in view, explicitly
    # marked stale/partial. A temporary outage must not erase prior history.
    if result.get("status") == "unavailable" and file.exists():
        saved = read_private_cache(file, source, config)
        previous = saved["result"]
        previous.update(status="partial", cachedAt=saved["collectedAt"], notes=[*result.get("notes", []), "Live source failed; retaining snapshot from " + saved["collectedAt"]])
        return previous
    if file.exists():
        previous = read_private_cache(file, source, config)
        result["scopeExcludedEventIds"] = sorted(set(result.get("scopeExcludedEventIds", [])) | set(previous["result"].get("scopeExcludedEventIds", [])))
        old_events = {e["id"]: e for e in previous["result"].get("events", [])}
        fresh_events = {e["id"]: e for e in result.get("events", [])}
        retained = 0
        for identifier, event in old_events.items():
            if identifier not in fresh_events:
                event.setdefault("metadata", {})["retainedFromPriorCapture"] = True
                event["metadata"].setdefault("lastCapturedAt", previous["collectedAt"])
                fresh_events[identifier] = event
                retained += 1
        result["events"] = list(fresh_events.values())
        if retained:
            result.setdefault("notes", []).append(f"Retained {retained} previously captured events not returned by this refresh; this may reflect deletion, changed scope or source availability. Their last capture time is recorded, not an inferred deletion date.")
        result.setdefault("stats", {})["retainedEvents"] = retained
    result = private_result(source, result, config)
    atomic_json(file, {"collectedAt": datetime.now(timezone.utc).isoformat(), "result": result})
    return result


def enrich(event):
    if event["source"] == "slack":
        event["body"] = re.sub(r"\n--- Reply \d+ of \d+ ---\s*$", "", event.get("body", ""))
    if event["source"] == "flujo" and "/?conversationId=" in event.get("url", ""):
        base = event["url"].split("/?conversationId=")[0]
        event["url"] = base + "/chat?conversation=" + quote(event.get("threadId", ""))
    text = " ".join([event.get("title", ""), event.get("body", ""), " ".join(str(t) for t in event.get("tags", []))])
    scores = [(name, len(re.findall(pattern, text, re.I))) for name, (_, pattern) in WORKSTREAMS.items()]
    scores.sort(key=lambda item: (-item[1], item[0]))
    event["workstreams"] = [name for name, score in scores[:3] if score] or ["steering"]
    event.setdefault("metadata", {})["classification"] = "Keyword inference from title, message and source tags; multi-label."
    source = event["source"]
    relevant = True
    if source == "slack":
        channel = event["metadata"].get("channel", "")
        relevant = any(word in channel.lower() for word in ("equipo-", "flujo-bot", "gloria", "kp", "flujo", "mario.andreschak", "announcements", "challenge-help")) or bool(re.search(r"factored-hackathon-2026-mcg|savia|mario.andreschak|U0C2TLARRFD|U0C466M7JA3|U0BV8HGPJ5S", text, re.I))
        if re.search(r"se ha unido al canal|has joined the channel|defini[oó] (?:el tema|la descripci[oó]n)|ha cambiado el nombre del canal|This message was deleted", event.get("body", ""), re.I):
            relevant = False
    elif source == "flujo":
        relevant = "agent-topology" in event.get("tags", []) or str(event["metadata"].get("flowName") or "").startswith("Hackathon_Release_") or bool(re.search(r"\b(github|repo(?:sitory)?|commit|pull request|PR #?\d+|deploy|frontend|backend|supervisor|codex|dataset|pipeline|docker|modal|review|pytest|hackathon|multi.agent)\b", text, re.I))
    event["metadata"]["developmentRelevant"] = relevant
    event["metadata"]["relevanceBasis"] = "Project scope" if source not in ("slack", "flujo") else "Development keyword / team-channel inference"
    refs = re.findall(r"https://github\.com/([^\s/<>]+/[^\s/<>]+)/(pull|issues)/(\d+)", text + " " + event.get("url", ""), re.I)
    event["references"] = sorted({f"https://github.com/{repository}/{kind}/{number}" for repository, kind, number in refs})
    return event


def topology_result(results, config, cache, offline):
    """Cache graph provenance separately; offline rebuilds never query live apps."""
    config = {**config,
              "_history_event_timestamps": {event["id"]: event["timestamp"] for result in results.values() for event in result.get("events", []) if event.get("id") and event.get("timestamp")},
              "_history_excluded_event_ids": {identity for result in results.values() for identity in result.get("scopeExcludedEventIds", [])}}
    file = cache / "topology.json"
    if offline and file.exists():
        saved = read_private_cache(file, "topology", config)
        topology = saved["result"]
        topology["cachedAt"] = saved["collectedAt"]
    else:
        adapter = importlib.import_module("history_sources.topology")
        topology = private_result("topology", adapter.derive(REPO, results, {**config, "offline": offline}), config)
        if not offline:
            if file.exists():
                previous = read_private_cache(file, "topology", config)
                retained = 0
                for key in ("sessions", "agentEdges", "flows", "events"):
                    fresh = {item["id"]: item for item in topology.get(key, [])}
                    for old in previous["result"].get(key, []):
                        identifier = old["id"]
                        if identifier not in fresh:
                            old["retainedFromPriorCapture"] = True
                            old.setdefault("lastCapturedAt", previous["collectedAt"])
                            fresh[identifier] = old
                            retained += 1
                        elif key == "sessions":
                            # A source outage can yield a message-only fallback;
                            # retain observed ancestry/graph fields without turning
                            # an absent field into evidence of deletion.
                            current = fresh[identifier]
                            missing = {k: v for k, v in old.items() if k not in {"retainedFromPriorCapture", "lastCapturedAt"} and current.get(k) is None and v is not None}
                            prior_ids = set(old.get("eventIds", [])) - set(current.get("eventIds", []))
                            current.update(missing)
                            current["eventIds"] = list(dict.fromkeys([*old.get("eventIds", []), *current.get("eventIds", [])]))
                            current["eventCount"] = len(current["eventIds"])
                            if missing or prior_ids:
                                current.update(retainedFromPriorCapture=True, lastCapturedAt=old.get("lastCapturedAt") or previous["collectedAt"])
                            if not current.get("nodeActivity") and old.get("nodeActivity"):
                                current["nodeActivity"] = old["nodeActivity"]
                                current.update(retainedFromPriorCapture=True, lastCapturedAt=old.get("lastCapturedAt") or previous["collectedAt"])
                    topology[key] = list(fresh.values())
                if retained:
                    topology.setdefault("notes", []).append(f"Retained {retained} prior topology records absent from this refresh, with their last capture time. Absence does not establish deletion or completion.")
                topology.setdefault("stats", {})["retainedRecords"] = retained
            topology = private_result("topology", topology, config)
            atomic_json(file, {"collectedAt": datetime.now(timezone.utc).isoformat(), "result": topology})
    # Restore the same exact session/node attribution when using saved topology.
    event_index = {e["id"]: e for r in results.values() for e in r.get("events", [])}
    for session in topology.get("sessions", []):
        activity = sorted(session.get("nodeActivity", []), key=lambda a: datetime.fromisoformat(a["timestamp"].replace("Z", "+00:00")).timestamp())
        times = [datetime.fromisoformat(a["timestamp"].replace("Z", "+00:00")).timestamp() for a in activity]
        for identifier in session.get("eventIds", []):
            event = event_index.get(identifier)
            if not event:
                continue
            metadata = event.setdefault("metadata", {})
            metadata.update(sessionId=session["id"], flowId=session.get("flowId"), flowDefinitionId=session.get("flowDefinitionId"))
            if times:
                at = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00")).timestamp()
                index = bisect_right(times, at) - 1
                if index >= 0:
                    metadata.update(nodeId=activity[index]["nodeId"], nodeAttributionBasis="Most recent depth-zero node:enter execution log in the same conversation")
    for event in topology.get("events", []):
        results[event["source"]].setdefault("events", []).append(event)
    return topology


def story(events):
    development = [e for e in events if e["metadata"].get("developmentRelevant")]
    project_start = next((e["timestamp"] for e in development if e["source"] == "codex"), "2026-09-25T05:00:00Z")
    specifications = [
        ("kickoff", "The hackathon begins", r"official launch.*Hackathon|Today marks the official launch", "The organizer launches the challenge and the development record begins."),
        ("formation", "A team takes shape", r"created this channel for our team|github invitation|sent both.*invitation.*github", "Team formation and the first shared project decisions."),
        ("audit", "Understand the challenge", r"data audit|profile_s3|data review|unrecognized.charge|data dictionary", "Inspect the banking data, challenge rules and feasible workflow."),
        ("slack-bot", "FLUJO joins the conversation", r"<@U0C4X0JDL8H|FLUJO.*(?:slack|bot)|slack.*FLUJO", "Slack becomes an entry point for the FLUJO development agent."),
        ("parallel", "Development splits into workstreams", r"multiple parallel sessions|one doing FRONTEND", "Frontend, backend, data and MCP work proceed with supervision."),
        ("governance", "The review loop connects systems", r"supervis.*(?:PR|FLUJO)|(?:Codex|threads).*(?:supervis|FLUJO)|(?:PR|pull request).*#\d+", "Messages, agent work and pull requests form a traceable review loop."),
        ("ci", "Verification becomes recurring", r"external worker|CI.*(?:docker|automat)|(?:hourly|every hour).*CI|modal.*(?:CI|worker)|CI.*modal", "Local and cloud workers add recurring verification to development."),
        ("release", "Deployment becomes a workstream", r"flyctl|fly.io|bring.*online|production.*deploy|deploy.*(?:gateway|fly|savia)", "Deployment work and readiness checks extend the development loop."),
    ]
    chapters = []
    for identifier, title, pattern, description in specifications:
        matches = []
        for e in development:
            source, channel = e["source"], e["metadata"].get("channel", "").lower()
            text = e.get("title", "") + " " + e.get("body", "")
            if identifier != "kickoff" and e["timestamp"] < project_start:
                continue
            if identifier == "kickoff" and not (source == "slack" and channel == "announcements"):
                continue
            if identifier == "formation" and not (source == "slack" and channel.startswith("equipo-")):
                continue
            if identifier == "audit" and source not in ("docs", "github", "codex"):
                continue
            if identifier in ("slack-bot", "parallel") and not (source == "slack" and channel.startswith(("equipo-", "flujo-bot"))):
                continue
            if identifier == "governance" and not (source in ("codex", "flujo") or source == "slack" and channel.startswith("equipo-")):
                continue
            if identifier == "governance" and source == "codex" and not re.search(r"supervis|orchestrat|manage|control.*FLUJO", e["title"], re.I):
                continue
            if identifier == "ci" and source not in ("codex", "slack"):
                continue
            if identifier == "release" and source == "slack" and not channel.startswith("equipo-"):
                continue
            if identifier == "release" and source not in ("github", "codex", "slack"):
                continue
            if identifier == "release" and source in ("github", "codex") and not re.search(r"deploy|fly.io|flyctl|gateway|online", e["title"], re.I):
                continue
            if re.search(pattern, text, re.I):
                matches.append(e)
        if matches:
            evidence = matches[0]
            chapters.append({"id": identifier, "title": title, "timestamp": evidence["timestamp"], "description": description, "evidenceIds": [e["id"] for e in matches[:5]], "basis": "Editorial chapter derived from source evidence; opening time is the first matching captured event."})
    chapters.sort(key=lambda c: c["timestamp"])
    if not chapters and development:
        chapters.append({"id": "start", "title": "Development begins", "timestamp": development[0]["timestamp"], "description": "The first captured project activity.", "evidenceIds": [development[0]["id"]]})
    by_reference = defaultdict(list)
    for event in development:
        for reference in event["references"]:
            if "/mario-andreschak/factored-hackathon-2026-mcg/" in reference:
                by_reference[reference].append(event)
    connections = []
    for reference, related in by_reference.items():
        first = {}
        for e in related:
            first.setdefault(e["source"], e)
        ordered = sorted(first.values(), key=lambda e: e["timestamp"])
        for a, b in zip(ordered, ordered[1:]):
            connections.append({"fromEventId": a["id"], "toEventId": b["id"], "from": a["source"], "to": b["source"], "timestamp": b["timestamp"], "reference": reference, "basis": "Shared explicit GitHub URL; relation is evidence, not proof of causation."})
    nodes = []
    for source, label in SOURCES.items():
        first = next((e for e in development if e["source"] == source), None)
        if first:
            nodes.append({"id": source, "label": label, "source": source, "firstTimestamp": first["timestamp"]})
    ci_events = [e for e in development if "ci" in e["workstreams"]]
    for identifier, label, pattern in [("local-ci", "Local Docker CI", r"external worker.*docker|docker.*(?:hourly|every hour)|CI.*docker"), ("modal-ci", "Modal CI", r"\bmodal\b.*(?:CI|worker|daily|24|automat)|(?:CI|worker).*\bmodal\b")]:
        matches = [e for e in ci_events if e["source"] in ("codex", "slack", "github") and e["timestamp"] >= project_start and re.search(pattern, e["body"] + " " + e["title"], re.I | re.S)]
        if matches:
            nodes.append({"id": identifier, "label": label, "source": "ci", "firstTimestamp": matches[0]["timestamp"], "evidenceIds": [e["id"] for e in matches[:5]]})
    edges = []
    grouped = defaultdict(list)
    for link in connections:
        grouped[(link["from"], link["to"])].append(link)
    for (a, b), links in grouped.items():
        edges.append({"id": a + "-" + b, "from": a, "to": b, "label": "Shared PR / issue", "firstTimestamp": min(x["timestamp"] for x in links), "evidenceIds": list(dict.fromkeys(e for x in links for e in (x["fromEventId"], x["toEventId"])))[:20], "basis": "Explicit cross-source references"})
    for node in nodes:
        if node["id"].endswith("-ci"):
            edges.append({"id": "github-" + node["id"], "from": "github", "to": node["id"], "label": "Recurring verification", "firstTimestamp": node["firstTimestamp"], "evidenceIds": node["evidenceIds"], "basis": "Inferred from cited development messages / automation configuration"})
    # Specific historical milestones are reviewable source pointers, not dates
    # or events invented to improve the story. Refreshes preserve these anchors.
    index = {e["id"]: e for e in events}
    curated_path = REPO / "scripts/history_story.json"
    curated = json.loads(curated_path.read_text(encoding="utf-8")) if curated_path.exists() else {}
    for chapter in curated.get("chapters", []):
        evidence = [identifier for identifier in chapter["evidenceIds"] if identifier in index]
        if evidence:
            chapters = [c for c in chapters if c["id"] != chapter["id"]]
            chapters.append({**chapter, "timestamp": index[evidence[0]]["timestamp"], "evidenceIds": evidence, "basis": "Editorial milestone pinned to its cited original source event."})
    for node in curated.get("nodes", []):
        evidence = [identifier for identifier in node["evidenceIds"] if identifier in index]
        if evidence:
            nodes = [n for n in nodes if n["id"] != node["id"]]
            nodes.append({**node, "firstTimestamp": index[evidence[0]]["timestamp"], "evidenceIds": evidence})
    node_times = {n["id"]: n["firstTimestamp"] for n in nodes}
    for edge in edges:
        if edge["to"].endswith("-ci") and edge["to"] in node_times:
            edge["firstTimestamp"] = node_times[edge["to"]]
    for edge in curated.get("edges", []):
        evidence = [identifier for identifier in edge["evidenceIds"] if identifier in index]
        if evidence and edge["from"] in node_times and edge["to"] in node_times:
            edges.append({**edge, "firstTimestamp": max(node_times[edge["from"]], node_times[edge["to"]], max(index[x]["timestamp"] for x in evidence)), "evidenceIds": evidence, "basis": "Editorial relationship supported by the cited request, configuration, or persisted response; inspect evidence for its scope."})
    team_time = node_times.get("flujo-team")
    team_links = [x for x in connections if x["timestamp"] >= team_time and "flujo" in (x["from"], x["to"]) and "github" in (x["from"], x["to"])] if team_time else []
    if team_links:
        link = team_links[0]
        edges.append({"id": "flujo-team-github", "from": "flujo-team", "to": "github", "label": "Shared PR evidence", "firstTimestamp": link["timestamp"], "evidenceIds": [link["fromEventId"], link["toEventId"]], "basis": link["basis"]})
    chapters.sort(key=lambda c: (c["timestamp"], c["id"]))
    return chapters, connections, {"nodes": nodes, "edges": edges, "note": "Landscape activation uses first captured evidence. Shared references connect systems; arrows do not claim an independently verified causal chain."}


def javascript_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def write_browser_snapshot(output, payload):
    """Keep first load small; full original bodies load on demand, even file://."""
    browser = {**payload, "events": []}
    bodies = output / "bodies"
    bodies.mkdir(parents=True, exist_ok=True)
    batch, event_batch, size, written = {}, [], 0, set()

    def flush():
        nonlocal batch, event_batch, size
        if not batch:
            return
        content = javascript_json(batch)
        name = "body-" + hashlib.sha256(content.encode()).hexdigest()[:20] + ".js"
        data = "window.DEV_HISTORY_BODY_SHARDS=window.DEV_HISTORY_BODY_SHARDS||{};window.DEV_HISTORY_BODY_SHARDS[" + json.dumps(name) + "]=" + content + ";\n"
        target = bodies / name
        if not target.exists():
            temporary = target.with_suffix(".tmp")
            temporary.write_text(data, encoding="utf-8")
            temporary.replace(target)
        for event in event_batch:
            event["bodyRef"] = name
        written.add(name)
        batch, event_batch, size = {}, [], 0

    for event in payload["events"]:
        body = event["body"]
        browser_metadata = {key: value for key, value in event["metadata"].items() if key in {"developmentRelevant", "bodyTruncated", "channel", "channelId", "channelType", "reactions", "reactionObservedAt", "files", "images", "role", "flowName", "origin", "parentThreadId", "forkedFromId", "agentRole", "agentNickname", "timestampBasis", "synthetic", "bankingOwned", "sessionId", "flowId", "flowDefinitionId", "nodeId", "fromNodeId", "toNodeId", "nodeAttributionBasis", "targetSessionId", "relationKind", "basis", "provider", "location", "region", "machineId", "machineIds", "buildId", "deploymentId", "image", "status", "lifecycle", "observedAt", "retainedFromPriorCapture", "lastCapturedAt", "kind", "depth", "threadTitle", "executingSessionId", "observedInSessionId", "eventType", "dispatchId", "nodeType", "app", "evidenceSourceEventIds"}}
        view = {**event, "metadata": browser_metadata}
        # Bodies are retained in canonical history.json and static body shards.
        # All events/IDs/timestamps/metadata remain in the lightweight index.
        if len(body) > 480:
            view["body"] = body[:480]
            view["metadata"]["bodyTruncated"] = True
            batch[event["id"]] = body
            event_batch.append(view)
            size += len(body)
            if size >= 400000 or len(batch) >= 150:
                flush()
        browser["events"].append(view)
    flush()
    browser["collection"] = {**browser["collection"], "bodyLoading": "Full original text loads from local JS shards when an event is opened. Search covers titles and text previews; history.json contains all original text."}
    temp = output / "history-data.js.tmp"
    compressed = base64.b64encode(gzip.compress(javascript_json(browser).encode("utf-8"), compresslevel=6, mtime=0)).decode("ascii")
    loader = "window.DEV_HISTORY_READY=(async()=>{if(!window.DecompressionStream)throw new Error('This browser needs native gzip support; use current Chrome, Edge or Firefox, or the local HTTP preview.');const bytes=Uint8Array.from(atob('" + compressed + "'),c=>c.charCodeAt(0));const stream=new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));const data=JSON.parse(await new Response(stream).text());window.DEV_HISTORY=data;return data;})();\n"
    temp.write_text(loader, encoding="utf-8")
    temp.replace(output / "history-data.js")
    # Only remove known generated files directly inside this output directory.
    for old in bodies.glob("body-*.js"):
        if old.name not in written and old.resolve().parent == bodies.resolve():
            old.unlink()
    print(f"Browser index: {(output / 'history-data.js').stat().st_size / 1024 / 1024:.1f} MB; {len(written)} full-text shards", flush=True)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Optional JSON collector configuration")
    parser.add_argument("--output", type=Path, default=REPO / "web/dev-history/data")
    parser.add_argument("--cache", type=Path, default=REPO / "private/development-history/cache")
    parser.add_argument("--offline", action="store_true", help="Rebuild from saved source snapshots without network/Docker")
    parser.add_argument("--only", nargs="+", choices=[*SOURCES, "topology"], help="Refresh just these sources, reuse cached snapshots for the rest")
    parser.add_argument("--strict", action="store_true", help="Exit nonzero if any source is incomplete")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8")) if args.config else {}
    cutoff = history_start(config)
    results = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        pending = {pool.submit(source_result, source, config, args.cache, args.offline or bool(args.only and source not in args.only)): source for source in SOURCES}
        for future in as_completed(pending):
            source = pending[future]
            results[source] = future.result()
            print(f"{SOURCES[source]}: {len(results[source].get('events', [])):,} events ({results[source].get('status')})", flush=True)
    from history_sources.media import collect_assets
    results["slack"] = collect_assets(results["slack"], args.output, args.cache, config, args.offline or bool(args.only and "slack" not in args.only))
    slack_cache = args.cache / "slack.json"
    if slack_cache.exists():
        saved = json.loads(slack_cache.read_text(encoding="utf-8"))
        # Keep source collection time while storing only screened file metadata.
        cached_result = {key: value for key, value in results["slack"].items() if key != "cachedAt"}
        cached_result["notes"] = [note for note in cached_result.get("notes", []) if not str(note).startswith("Using the saved source snapshot from ")]
        atomic_json(slack_cache, {**saved, "result": private_result("slack", cached_result, config)})
    topology = topology_result(results, config, args.cache, args.offline or bool(args.only and "topology" not in args.only))
    print(f"Topology: {len(topology.get('sessions', [])):,} sessions, {len(topology.get('agentEdges', [])):,} relationships, {len(topology.get('flows', [])):,} saved graphs", flush=True)
    events, skipped = {}, Counter()
    for source, result in results.items():
        for raw in result.get("events", []):
            try:
                e = dict(raw)
                e["timestamp"] = timestamp(e["timestamp"])
                if e["timestamp"] < cutoff:
                    continue
                e.setdefault("source", source)
                for key in ("body", "title", "actor", "url", "threadId"):
                    e.setdefault(key, "")
                e.setdefault("kind", "event")
                e.setdefault("tags", [])
                e.setdefault("metadata", {})
                events[e["id"]] = enrich(e)
            except (ValueError, TypeError, KeyError, OverflowError):
                skipped[source] += 1
    ordered = sorted(events.values(), key=lambda e: (e["timestamp"], e["id"]))
    chapters, connections, landscape = story(ordered)
    narrative_path = REPO / "scripts/history_narrative.json"
    narrative = json.loads(narrative_path.read_text(encoding="utf-8")) if narrative_path.exists() else {}
    for chapter in chapters:
        chapter["narration"] = narrative.get(chapter["id"], {"heading": chapter["title"], "paragraphs": [chapter["description"]], "view": "activity"})
    sources = []
    for source, label in SOURCES.items():
        r = results[source]
        notes = r.get("notes", [])
        if skipped[source]:
            notes = [*notes, f"Skipped {skipped[source]} events with invalid timestamps or IDs."]
        sources.append({"id": source, "label": label, "status": "partial" if skipped[source] else r.get("status", "unavailable"), "eventCount": sum(e["source"] == source for e in ordered), "notes": notes, "stats": r.get("stats", {}), "cachedAt": r.get("cachedAt")})
    payload = sanitize({"schemaVersion": 2, "generatedAt": datetime.now(timezone.utc).isoformat(), "project": {"name": "SAVIA", "title": "Factored Hackathon 2026 · Development history", "repo": "mario-andreschak/factored-hackathon-2026-mcg", "timezone": "America/Bogota"}, "events": ordered, "sources": sources, "chapters": chapters, "connections": connections, "landscape": landscape, "topology": {k: v for k, v in topology.items() if k != "events"}, "infrastructure": {k: v for k, v in results["infrastructure"].items() if k != "events"}, "workstreams": [{"id": k, "label": v[0]} for k, v in WORKSTREAMS.items()], "stats": {"events": len(ordered), "developmentEvents": sum(e["metadata"].get("developmentRelevant", False) for e in ordered), "start": ordered[0]["timestamp"] if ordered else None, "end": ordered[-1]["timestamp"] if ordered else None, "actors": len({e["actor"] for e in ordered}), "workstreams": dict(Counter(w for e in ordered for w in e["workstreams"]))}, "documents": results["docs"].get("documents", []), "automations": results["codex"].get("automations", []), "collection": {"readOnly": True, "redactedCredentials": True, "scope": "Full captured archive; default chronological replay visits every selected record. Development relevance is an optional inferred scope filter; narrated chapters contain authored evidence-linked prose. Workstreams, chapters and relationship arrows are annotations, source bodies and timestamps are primary evidence.", "command": "python scripts/build_dev_history.py"}})
    payload["collection"].update(privacyPolicyVersion=1, redactedContactDetails=True,
                                 historyStart=cutoff, historyStartTimezone="America/Bogota",
                                 slackExcludedConversations="Direct/group direct messages; find-a-team; challenge-help; technical-help",
                                 embeddedSlackPrivacy="Recognized disallowed transcripts/listings in tool outputs are scrubbed with explicit omission markers.",
                                 teamNames="Preserved by user preference", slackImages="Local metadata-free PNG assets after local OCR screening; detected contacts withheld.")
    atomic_json(args.output / "history.json", payload)
    write_browser_snapshot(args.output, payload)
    report = {key: payload[key] for key in ("generatedAt", "project", "sources", "stats", "collection")}
    atomic_json(args.output / "collection-report.json", report)
    print(f"Built {len(ordered):,} timestamped events, {len(chapters)} chapters, {len(connections)} cross-source references → {args.output}", flush=True)
    if args.strict and any(s["status"] != "ok" for s in sources):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
