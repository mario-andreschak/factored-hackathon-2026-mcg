"""Read-only infrastructure evidence, including retained historical tool output.

Lifecycle dates come from provider fields. Tool-call dates establish when a
command/output was observed, not when an undocumented machine was created.
No env, credential/config/key files, container command lines or provider secrets
are exported. Docker logs and Fly's log buffer are retention-limited sources.
"""
from __future__ import annotations

import ast
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import warnings
from .common import sanitize as _common_sanitize, stable_id, timestamp


_RELATED = re.compile(r"flujo|factored|hackathon|savia|gloria|private-ci", re.I)
_EXCLUDED_DIRS = {".git", "node_modules", ".venv", "venv", "npm-cache", "source", "snapshot", "secrets", "__pycache__", "inputs"}
_LOG_TIME = re.compile(r"^(\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d))\s+(.*)$")
_COMMAND_LITERAL = re.compile(r"exec_command\s*\(\s*\{[\s\S]{0,1800}?\b[\"']?cmd[\"']?\s*:\s*(\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')")
# Projection deliberately does not request Config.Env, Args, Cmd, or labels as
# a whole. Even innocuous-looking labels can contain credentials.
_DOCKER_FORMAT = ('{"Id":{{json .Id}},"Name":{{json .Name}},"Created":{{json .Created}},'
    '"Image":{{json .Config.Image}},"ImageId":{{json .Image}},'
    '"State":{"Status":{{json .State.Status}},"StartedAt":{{json .State.StartedAt}},'
    '"FinishedAt":{{json .State.FinishedAt}},"ExitCode":{{json .State.ExitCode}},"OOMKilled":{{json .State.OOMKilled}}},'
    '"Ports":{{json .NetworkSettings.Ports}},'
    '"Project":{{json (index .Config.Labels "com.docker.compose.project")}},'
    '"Service":{{json (index .Config.Labels "com.docker.compose.service")}}}')


def sanitize(value):
    """Shell logs add generic env/CLI token forms to shared source redaction."""
    value = _common_sanitize(value)
    if isinstance(value, str):
        value = re.sub(r"(?im)((?:[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|CREDENTIAL|PRIVATE_KEY))\s*[=:]\s*[\"']?)([^\s\"'`,;}{]{5,})", r"\1[REDACTED]", value)
        value = re.sub(r"(?i)((?:--access-token|--token|--password|--secret)\s+)[^\s;]+", r"\1[REDACTED]", value)
        value = re.sub(r"\bFlyV1\s+[A-Za-z0-9_,+/=.-]+", "[REDACTED FLY TOKEN]", value)
        return value
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, dict):
        return {key: "[REDACTED]" if re.search(r"(?:token|secret|password|credential|private_key)$", str(key), re.I) and isinstance(item, str) else sanitize(item) for key, item in value.items()}
    return value


def _utc(value):
    if not value or str(value).startswith("0001-") or str(value).startswith("1970-01-01T00:00:00"):
        return None
    try:
        return timestamp(value)
    except (ValueError, TypeError, OverflowError):
        return None


def _run(args, repo, timeout=40):
    result = subprocess.run(args, cwd=repo, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout)
    if result.returncode:
        # Stderr may contain credentials; sanitize before entering a report.
        raise RuntimeError(f"{Path(args[0]).name} {args[1] if len(args)>1 else ''}: " + sanitize(result.stderr.strip())[:240])
    return result.stdout, result.stderr


def _json_values(raw):
    """JSON arrays, NDJSON, and Fly's pretty-printed concatenated JSON objects."""
    decoder, position = json.JSONDecoder(), 0
    while position < len(raw):
        while position < len(raw) and raw[position].isspace():
            position += 1
        if position >= len(raw):
            break
        try:
            value, end = decoder.raw_decode(raw, position)
            position = end
            yield from value if isinstance(value, list) else [value]
        except json.JSONDecodeError:
            next_line = raw.find("\n", position)
            if next_line < 0:
                break
            position = next_line + 1


def _event(identifier, time, kind, title, body, provider, location, **metadata):
    return {"id": "infrastructure:" + identifier, "timestamp": _utc(time), "source": "infrastructure", "kind": kind,
        "title": title, "body": sanitize(body), "actor": metadata.pop("actor", provider.title()),
        "url": metadata.pop("url", ""), "threadId": metadata.pop("threadId", ""),
        "tags": [provider, "infrastructure", "ci" if kind.startswith("ci") else "deployment"],
        "metadata": {"provider": provider, "location": location, **sanitize(metadata)}}


def _link_machine(machine, event):
    if not event["timestamp"]:
        return
    machine.setdefault("evidenceEventIds", []).append(event["id"])
    if not machine.get("firstTimestamp") or event["timestamp"] < machine["firstTimestamp"]:
        machine["firstTimestamp"] = event["timestamp"]


def _docker(repo, config, observed, events, machines, builds, notes, stats):
    if config.get("docker_enabled", True) is False:
        notes.append("Docker live inspection disabled by configuration.")
        return
    if not shutil.which("docker"):
        notes.append("Docker CLI unavailable; persisted command evidence is still collected.")
        return
    try:
        raw, _ = _run(["docker", "ps", "-aq"], repo)
        ids = raw.split()
        if not ids:
            return
        raw, _ = _run(["docker", "inspect", "--format", _DOCKER_FORMAT, *ids], repo)
        context, _ = _run(["docker", "context", "show"], repo)
        location = "Local · Docker Desktop (" + context.strip() + ")"
        allowed = set(config.get("docker_containers", [])) | {config.get("flujo_container", "flujo-slack-flujo-1")}
        log_tail = max(0, int(config.get("docker_log_tail", 6000)))
        image_ids = {}
        for row in _json_values(raw):
            if not isinstance(row, dict):
                continue
            name = str(row.get("Name", "")).lstrip("/")
            if name not in allowed and not _RELATED.search(name + " " + str(row.get("Image", ""))):
                continue
            identifier = "docker:" + row["Id"]
            state = row.get("State", {})
            machine = {"id": identifier, "label": name, "provider": "docker", "location": location,
                "createdAt": _utc(row.get("Created")), "firstTimestamp": None, "state": state.get("Status", "unknown"),
                "currentSnapshot": True, "lastObservedAt": observed, "image": row.get("Image"), "imageId": row.get("ImageId"),
                "service": row.get("Service") or name, "project": row.get("Project") or None,
                "ports": row.get("Ports") or {}, "exitCode": state.get("ExitCode"), "oomKilled": bool(state.get("OOMKilled")),
                "evidenceEventIds": [], "timestampBasis": "docker inspect lifecycle fields; current state observed at collection"}
            machines[identifier] = machine
            stats["dockerContainers"] += 1
            lifecycle = [("create", row.get("Created"), "docker.Created"), ("start", state.get("StartedAt"), "docker.State.StartedAt")]
            if state.get("Status") in {"exited", "dead"}:
                lifecycle.append(("stop", state.get("FinishedAt"), "docker.State.FinishedAt"))
            for action, time, basis in lifecycle:
                if not _utc(time):
                    continue
                detail = {"container": name, "containerId": row["Id"], "image": row.get("Image"), "location": location,
                    "lifecycle": action, "exitCode": state.get("ExitCode") if action == "stop" else None}
                event = _event(f"{identifier}:{action}:{_utc(time)}", time, "machine_" + action,
                    f"{name} · {action}", json.dumps(detail, ensure_ascii=False, indent=2), "docker", location,
                    machineId=identifier, lifecycle=action, timestampBasis=basis, observedAt=observed)
                events.append(event)
                _link_machine(machine, event)
            # State is explicitly a present-day observation, not backdated onto
            # the creation event or an inferred uninterrupted lifetime.
            snapshot = _event(f"{identifier}:snapshot:{observed}", observed, "machine_snapshot", f"{name} · observed {machine['state']}",
                json.dumps({key: machine[key] for key in ("label", "state", "image", "ports", "exitCode", "oomKilled")}, ensure_ascii=False, indent=2),
                "docker", location, machineId=identifier, lifecycle="snapshot", timestampBasis="collection observation", currentSnapshot=True)
            events.append(snapshot)
            _link_machine(machine, snapshot)
            image_ids[row.get("ImageId")] = row.get("Image")
            if not log_tail:
                continue
            try:
                stdout, stderr = _run(["docker", "logs", "--timestamps", "--tail", str(log_tail), row["Id"]], repo, timeout=60)
                lines = stdout.splitlines() + stderr.splitlines()
                stats["dockerLogLinesReturned"] += len(lines)
                if len(lines) >= log_tail:
                    stats["dockerLogTailLimitHit"] += 1
                occurrences = Counter()
                for line in lines:
                    match = _LOG_TIME.match(line)
                    if not match or not _utc(match[1]):
                        stats["logsWithoutTimestamp"] += 1
                        continue
                    key = stable_id(line)
                    ordinal = occurrences[key]
                    occurrences[key] += 1
                    event = _event(f"{identifier}:log:{key}:{ordinal}", match[1], "container_log", f"{name} · runtime log", match[2],
                        "docker", location, machineId=identifier, lifecycle="log", timestampBasis="docker logs --timestamps", observedAt=observed)
                    events.append(event)
                    _link_machine(machine, event)
            except (RuntimeError, subprocess.TimeoutExpired) as error:
                notes.append(f"Docker logs for {name}: {sanitize(str(error))[:180]}")
        for image_id, tag in image_ids.items():
            if not image_id:
                continue
            try:
                raw, _ = _run(["docker", "image", "inspect", "--format", '{"Id":{{json .Id}},"Created":{{json .Created}},"Tags":{{json .RepoTags}},"Size":{{json .Size}}}', image_id], repo)
                for image in _json_values(raw):
                    time = _utc(image.get("Created"))
                    if not time:
                        continue
                    build_id = "docker-image:" + image["Id"]
                    event = _event(build_id, time, "image_created", f"Docker image · {tag}", json.dumps(image, ensure_ascii=False, indent=2),
                        "docker", location, buildId=build_id, timestampBasis="docker image.Created; image creation, not independently proven build start", observedAt=observed)
                    events.append(event)
                    builds.append({"id": build_id, "provider": "docker", "location": location, "timestamp": time, "image": tag,
                        "imageId": image["Id"], "state": "image_exists", "evidenceEventIds": [event["id"]], "timestampBasis": event["metadata"]["timestampBasis"]})
            except (RuntimeError, subprocess.TimeoutExpired):
                stats["unavailableImages"] += 1
        notes.append(f"Docker allowlisted inspect fields plus retained timestamped logs, up to {log_tail:,} lines per project container. Earlier restarts and deleted containers cannot be inferred from the current inspect snapshot; historical tool evidence supplements it.")
    except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError) as error:
        notes.append("Docker live evidence unavailable: " + sanitize(str(error))[:200])
        stats["sourceFailures"] += 1


def _fly_apps(repo, options):
    names = set(options.get("fly_apps", []))
    for path in (repo / "deploy").rglob("fly*.toml"):
        if any(part in _EXCLUDED_DIRS for part in path.parts):
            continue
        try:
            # Read only app/region declarations, not [env] entries or secrets.
            with path.open(encoding="utf-8") as stream:
                for line in stream:
                    match = re.match(r"\s*app\s*=\s*[\"']([a-zA-Z0-9-]+)[\"']", line)
                    if match:
                        names.add(match[1])
                        break
        except OSError:
            continue
    return sorted(names)


def _fly_machine(row, app, observed, events, machines):
    identifier = "fly:" + app + ":" + str(row.get("id"))
    region = row.get("region") or "Fly region unspecified"
    config = row.get("config") or {}
    machine = {"id": identifier, "label": row.get("name") or str(row.get("id")), "app": app, "provider": "fly", "location": region,
        "createdAt": _utc(row.get("created_at")), "firstTimestamp": None, "state": row.get("state", "unknown"),
        "currentSnapshot": True, "lastObservedAt": observed, "image": config.get("image"),
        "resources": {key: (config.get("guest") or {}).get(key) for key in ("cpu_kind", "cpus", "memory_mb")},
        "evidenceEventIds": [], "timestampBasis": "Fly machine created_at / retained lifecycle events; current state observed at collection"}
    machines[identifier] = machine
    if machine["createdAt"]:
        event = _event(identifier + ":create:" + machine["createdAt"], machine["createdAt"], "machine_create", f"{app} · machine created in {region}",
            json.dumps({key: machine[key] for key in ("id", "label", "app", "location", "createdAt", "resources")}, indent=2), "fly", region,
            machineId=identifier, app=app, lifecycle="create", timestampBasis="fly.machine.created_at", observedAt=observed)
        events.append(event)
        _link_machine(machine, event)
    for row_event in row.get("events") or []:
        time = _utc(row_event.get("timestamp"))
        if not time:
            continue
        action = row_event.get("type") or "lifecycle"
        status = row_event.get("status") or ""
        safe = {key: row_event.get(key) for key in ("type", "status", "source", "timestamp")}
        event = _event(identifier + ":event:" + stable_id(safe), time, "machine_" + action,
            f"{app} · {action} {status} · {region}", json.dumps(safe, indent=2), "fly", region,
            machineId=identifier, app=app, lifecycle=action, state=status, timestampBasis="fly.machine.events.timestamp", observedAt=observed)
        events.append(event)
        _link_machine(machine, event)
    event = _event(identifier + ":snapshot:" + observed, observed, "machine_snapshot", f"{app} · observed {machine['state']} in {region}",
        json.dumps({key: machine[key] for key in ("id", "label", "app", "state", "location", "resources", "image")}, indent=2), "fly", region,
        machineId=identifier, app=app, lifecycle="snapshot", timestampBasis="collection observation", currentSnapshot=True)
    events.append(event)
    _link_machine(machine, event)
    return machine


def _fly(repo, options, observed, events, machines, deployments, notes, stats):
    executable = shutil.which("flyctl") or shutil.which("fly")
    apps = _fly_apps(repo, options)
    stats["discoveredFlyApps"] = len(apps)
    if options.get("fly_enabled", True) is False or not executable:
        notes.append("Fly live CLI collection disabled/unavailable; persisted deployments remain available.")
        return
    for app in apps:
        try:
            raw, _ = _run([executable, "machine", "list", "--app", app, "--json"], repo)
            for row in _json_values(raw):
                if isinstance(row, dict) and row.get("id"):
                    _fly_machine(row, app, observed, events, machines)
                    stats["flyMachines"] += 1
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            notes.append(f"Fly machines {app}: {sanitize(str(error))[:180]}")
            stats["sourceFailures"] += 1
        try:
            raw, _ = _run([executable, "releases", "--app", app, "--json"], repo)
            for row in _json_values(raw):
                if not isinstance(row, dict):
                    continue
                time = _utc(row.get("CreatedAt") or row.get("created_at"))
                if not time:
                    continue
                identifier = "fly-release:" + app + ":" + str(row.get("ID") or row.get("id") or row.get("Version"))
                safe = {key: row.get(key) for key in ("ID", "Version", "Status", "Description", "CreatedAt", "ImageRef", "DeploymentStrategy")}
                event = _event(identifier, time, "deployment_release", f"{app} · release v{row.get('Version', '?')} · {row.get('Status', 'observed')}",
                    json.dumps(safe, ensure_ascii=False, indent=2), "fly", "Fly app · region in associated machine evidence", app=app,
                    deploymentId=identifier, state=row.get("Status"), timestampBasis="fly.release.CreatedAt", observedAt=observed,
                    url="https://fly.io/apps/" + app)
                events.append(event)
                deployments.append({"id": identifier, "app": app, "provider": "fly", "location": event["metadata"]["location"], "timestamp": time,
                    "version": row.get("Version"), "state": row.get("Status"), "image": row.get("ImageRef"), "evidenceEventIds": [event["id"]],
                    "timestampBasis": "fly.release.CreatedAt"})
                stats["flyReleases"] += 1
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            notes.append(f"Fly releases {app}: {sanitize(str(error))[:180]}")
        if options.get("fly_logs", True):
            try:
                raw, _ = _run([executable, "logs", "--app", app, "--json", "--no-tail"], repo)
                for row in _json_values(raw):
                    if not isinstance(row, dict) or not _utc(row.get("timestamp")):
                        continue
                    machine_id = "fly:" + app + ":" + str(row.get("instance")) if row.get("instance") else None
                    event = _event("fly-log:" + app + ":" + stable_id([row.get("timestamp"), row.get("instance"), row.get("message")]),
                        row["timestamp"], "machine_log", f"{app} · {row.get('instance', 'app')} · runtime log", str(row.get("message") or ""),
                        "fly", row.get("region") or "unspecified", machineId=machine_id, app=app, lifecycle="log", level=row.get("level"),
                        timestampBasis="fly.logs.timestamp", observedAt=observed)
                    events.append(event)
                    if machine_id in machines:
                        _link_machine(machines[machine_id], event)
                    stats["flyLogLines"] += 1
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                notes.append(f"Fly retained log buffer {app}: {sanitize(str(error))[:180]}")
    if apps:
        notes.append("Fly machine/release dates are provider timestamps. --no-tail reads only the retained log buffer; deployment CLI output in Codex fills some earlier history. Machine config env, secrets and full provider metadata are excluded.")


def _commands(value, name=""):
    """Extract executed shell tool arguments, never prose or apply_patch text."""
    if isinstance(value, dict):
        tool_name = str(value.get("name") or value.get("tool") or name)
        if isinstance(value.get("function"), dict):
            yield from _commands(value["function"], tool_name)
        if "arguments" in value:
            yield from _commands(value["arguments"], tool_name)
        if any(word in tool_name.lower() for word in ("exec_command", "run_command", "execute_command", "shell", "bash", "powershell", "exec")):
            for field in ("cmd", "command", "shell_command"):
                if isinstance(value.get(field), str):
                    yield value[field]
        for field in ("tool_calls", "toolCalls"):
            for tool in value.get(field) or []:
                yield from _commands(tool)
    elif isinstance(value, list):
        for item in value:
            yield from _commands(item, name)
    elif isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, (dict, list)):
            yield from _commands(parsed, name)
        # functions.exec wraps nested shell tools in JavaScript. Only extract
        # the cmd literal attached to exec_command; patch/script literals are
        # deliberately not interpreted as an executed command.
        for match in _COMMAND_LITERAL.finditer(value):
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", SyntaxWarning)
                    command = json.loads(match[1]) if match[1].startswith('"') else ast.literal_eval(match[1])
                yield command
            except (ValueError, SyntaxError):
                continue


def _classify(command):
    categories = []
    # A quoted command in a Python string, README write, or heredoc is not proof
    # it ran. Direct shell invocations must start a line or follow a separator.
    invocation = re.compile(r"(?:^|[;&|\n])\s*(?:&\s*)?[\"']?(?:[^\s\"']*[/\\])?(docker(?:\.exe)?|flyctl(?:\.exe)?|fly(?:\.cmd)?|modal(?:\.exe)?)\b([^\n;]*)", re.I)
    for match in invocation.finditer(command):
        provider = "docker" if match[1].lower().startswith("docker") else "modal" if match[1].lower().startswith("modal") else "fly"
        arguments = match[2].strip(' "\'')
        if re.search(r"\b(?:build|buildx)\b", arguments) and provider == "docker":
            kind = "build"
        elif provider == "fly" and re.match(r"deploy\b", arguments) or provider == "modal" and re.match(r"(?:deploy|run)\b", arguments):
            kind = "deployment" if provider == "fly" or arguments.startswith("deploy") else "ci_execution"
        elif re.search(r"\b(?:create|run|up|start|stop|restart|destroy|rm)\b", arguments):
            kind = "machine_command"
        else:
            kind = "inspection_command"
        categories.append((provider, kind, match[0].strip(";&|\n ")))
    if re.search(r"(?:^|[;&|\n])\s*(?:python(?:\.exe)?|py)\s+[^\n;]*(?:run_modal|local[_-]ci|ci_controller|run_ci|run_local)[^\n;]*(?:--execute|--resume)", command, re.I):
        categories.append(("modal" if "run_modal" in command else "local", "ci_execution", command))
    return list(dict.fromkeys(categories))


def _output_text(value):
    if isinstance(value, dict):
        return "\n".join(_output_text(value[key]) for key in ("output", "stdout", "stderr", "text", "content") if key in value)
    if isinstance(value, list):
        return "\n".join(_output_text(item) for item in value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (ValueError, TypeError):
            return value
        return _output_text(decoded) or value
    return "" if value is None else str(value)


def _output_state(value):
    raw = json.dumps(value) if not isinstance(value, str) else value
    matches = re.findall(r'(?:exit_code|exitCode)[\"\s:]+(-?\d+)|(?:exit code|exited with code)[\s:]+(-?\d+)', raw, re.I)
    codes = [int(a or b) for a, b in matches]
    if any(code for code in codes):
        return "failed"
    if codes or re.search(r"successfully built|successfully tagged|exporting to image.*done|View your deployment at|deployment is ready", _output_text(value), re.I):
        return "completed"
    return "output_observed"


def _record_command(call, output, events, builds, deployments, stats):
    for ordinal, (provider, kind, command) in enumerate(_classify(call["command"])):
        identifier = "tool:" + str(call["source"]) + ":" + stable_id([call["key"], command, ordinal])
        location = call.get("location") or ("Modal cloud · location not exposed by saved output" if provider == "modal" else "Fly cloud · command origin: " + str(call.get("cwd") or "local host") if provider == "fly" else "Local · " + str(call.get("cwd") or "shell host"))
        state = _output_state(output) if output is not None else "command_observed"
        result_text = _output_text(output) if output is not None else "No matching retained output. This records the tool invocation only."
        time = call["timestamp"]
        build_id = identifier if kind == "build" else None
        deployment_id = identifier if kind in {"deployment", "ci_execution"} else None
        app_match = re.search(r"(?:--app|-a)\s+[\"']?([a-zA-Z0-9-]+)", command)
        event = _event(identifier, time, kind + "_output", f"{provider.title()} · {kind.replace('_', ' ')} · {state.replace('_', ' ')}",
            "$ " + command + "\n\n" + result_text, provider, location,
            actor=call.get("actor") or call["source"].title(), threadId=call.get("threadId", ""), url=call.get("url", ""),
            command=command, commandTimestamp=time, outputTimestamp=call.get("outputTimestamp"), state=state,
            buildId=build_id, deploymentId=deployment_id, app=app_match[1] if app_match else None,
            timestampBasis="tool invocation timestamp; output observation is separate, lifecycle time not inferred",
            evidenceSource=call["source"], evidenceSourceEventIds=call.get("evidenceIds", []), originPath=call.get("originPath"), originLine=call.get("line"),
            stdoutTruncated=bool(re.search(r"truncated|omitted.*characters|output token.*limit", result_text, re.I)))
        if not event["timestamp"]:
            stats["missingCommandTimestamps"] += 1
            continue
        events.append(event)
        stats[call["source"] + "CommandEvidence"] += 1
        record = {"id": identifier, "provider": provider, "location": location, "timestamp": time, "startedAt": time,
            "finishedAt": call.get("outputTimestamp") if state in {"completed", "failed"} else None, "state": state,
            "command": sanitize(command), "app": app_match[1] if app_match else None, "evidenceEventIds": [event["id"]],
            "timestampBasis": event["metadata"]["timestampBasis"]}
        if build_id:
            builds.append(record)
        if deployment_id:
            deployments.append(record)


def _codex_tools(repo, config, events, builds, deployments, notes, stats, report_paths):
    if config.get("codex_tools", True) is False:
        return
    from . import codex
    home = Path(config.get("codex_home") or os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    paths, discovery = codex._discovery(home, repo, config.get("codex", {}), notes)
    stats["codexRollouts"] = len(paths)
    seen = set()
    for path, meta in paths:
        pending = {}
        thread_id = str(meta["id"])
        boundary = meta.get("subagent_history_start_ordinal")
        creation = _utc(meta.get("timestamp"))
        try:
            with path.open(encoding="utf-8-sig") as stream:
                for line_number, line in enumerate(stream, 1):
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        stats["malformedToolRecords"] += 1
                        continue
                    payload = row.get("payload") or {}
                    if not isinstance(payload, dict) or row.get("type") != "response_item":
                        continue
                    ordinal = row.get("ordinal")
                    time = _utc(row.get("timestamp"))
                    if isinstance(boundary, int) and isinstance(ordinal, int) and ordinal < boundary:
                        continue
                    if meta.get("forked_from_id") and creation and time and time < creation:
                        continue
                    key = str(payload.get("call_id") or payload.get("id") or f"{thread_id}:{line_number}")
                    if payload.get("type") in {"function_call", "custom_tool_call"}:
                        if key in seen:
                            continue
                        seen.add(key)
                        commands = list(dict.fromkeys(_commands(payload.get("arguments") or payload.get("input") or "", str(payload.get("name") or ""))))
                        infra = [command for command in commands if _classify(command)]
                        if infra:
                            pending[key] = [{"key": key, "source": "codex", "command": command, "timestamp": time,
                                "threadId": thread_id, "cwd": meta.get("cwd"), "originPath": str(path), "line": line_number,
                                "actor": meta.get("agent_nickname") or "Codex", "url": "codex://threads/" + thread_id} for command in infra]
                        for command in commands:
                            # Discover explicitly referenced execution evidence,
                            # never filesystem mtimes or credential files.
                            for candidate in re.findall(r"[A-Za-z]:[/\\][^\"'\r\n]+?(?:summary|result|report)\.json", command, re.I):
                                evidence_path = Path(candidate)
                                if evidence_path.is_file() and (codex._inside(evidence_path, home / "visualizations") or codex._inside(evidence_path, repo)):
                                    report_paths.add(evidence_path)
                    elif payload.get("type") in {"function_call_output", "custom_tool_call_output"} and key in pending:
                        output = payload.get("output")
                        for call in pending.pop(key):
                            call["outputTimestamp"] = time
                            _record_command(call, output, events, builds, deployments, stats)
            for calls in pending.values():
                for call in calls:
                    _record_command(call, None, events, builds, deployments, stats)
        except (OSError, UnicodeError):
            stats["unreadableToolRollouts"] += 1
    notes.append("Historical Codex evidence is extracted only from executed shell tool arguments and paired retained outputs in project rollouts. Patches, user prose, reasoning and planned instructions are not infrastructure execution evidence. A command timestamp is not an inferred machine creation time.")


def _flujo_tools(repo, config, events, builds, deployments, notes, stats):
    cache = Path(config.get("cache_path") or repo / "private/development-history/cache") / "flujo.json"
    if not cache.exists():
        return
    try:
        source = json.loads(cache.read_text(encoding="utf-8")).get("result", {}).get("events", [])
    except (OSError, ValueError):
        notes.append("FLUJO saved snapshot unreadable for infrastructure evidence.")
        return
    by_thread = {}
    for event in sorted(source, key=lambda value: value.get("timestamp", "")):
        thread_id = event.get("threadId")
        if event.get("kind") == "assistant_message":
            body = event.get("body", "")
            for start in [match.start() for match in re.finditer(r"(?:^|\n)\s*\[\s*\{", body)]:
                try:
                    tools = json.loads(body[start:].strip())
                except ValueError:
                    continue
                for command in _commands(tools):
                    if _classify(command):
                        by_thread.setdefault(thread_id, []).append({"key": event["id"], "source": "flujo", "command": command,
                            "timestamp": event["timestamp"], "threadId": thread_id, "location": "FLUJO worker · Docker local / configured shell", "url": event.get("url"),
                            "evidenceIds": [event["id"]], "actor": "FLUJO"})
        elif event.get("kind") == "tool_message" and by_thread.get(thread_id):
            calls = by_thread.pop(thread_id)
            for call in calls:
                call["outputTimestamp"] = event["timestamp"]
                call["evidenceIds"].append(event["id"])
                _record_command(call, event.get("body"), events, builds, deployments, stats)
    for calls in by_thread.values():
        for call in calls:
            _record_command(call, None, events, builds, deployments, stats)
    notes.append("FLUJO historical shell execution uses the saved conversation snapshot; its source capture time is reported separately. The next rebuild incorporates newly captured FLUJO messages.")


def _safe_report(row):
    fields = {"schema_version", "executed", "status", "repository", "head_sha", "tree_sha", "mode", "gate_id", "gate", "name", "platform", "worker",
        "started_at", "finished_at", "completed_at", "timestamp", "created_at", "generated_at", "exit_code", "exitCode", "all_gates_passed",
        "image_id", "app_id", "appId", "app_url", "function_call_id", "call_id", "run_id", "duration_seconds", "error", "errors", "reason",
        "checks", "reports", "gates", "results", "receipts", "image_probe", "remote_pr", "remote_pr_at_execution", "preserved_gate_ids", "missing_gate_ids"}
    if isinstance(row, dict):
        return {key: _safe_report(value) for key, value in row.items() if key in fields}
    if isinstance(row, list):
        return [_safe_report(item) for item in row]
    return sanitize(row)


def _modal(repo, config, observed, events, machines, notes, stats):
    executable = shutil.which("modal")
    if config.get("modal_enabled", True) is False or not executable:
        notes.append("Modal live CLI collection disabled/unavailable; saved execution evidence is retained.")
        return
    try:
        raw, _ = _run([executable, "app", "list", "--json"], repo, timeout=45)
        rows = list(_json_values(raw))
        stats["modalAppsReturned"] = len(rows)
        allowed = set(config.get("modal_apps", []))
        for row in rows:
            if not isinstance(row, dict):
                continue
            app_id = row.get("App ID") or row.get("app_id") or row.get("id")
            name = row.get("Description") or row.get("description") or row.get("Name") or row.get("name") or str(app_id)
            if not app_id or app_id not in allowed and name not in allowed and not _RELATED.search(str(name)):
                continue
            identifier = "modal:" + str(app_id)
            created = _utc(row.get("Created at") or row.get("created_at") or row.get("CreatedAt"))
            location = "Modal cloud · provider region not returned"
            machine = {"id": identifier, "label": str(name), "app": str(app_id), "provider": "modal", "location": location,
                "createdAt": created, "firstTimestamp": created or observed, "state": row.get("State") or row.get("state") or "observed",
                "currentSnapshot": True, "lastObservedAt": observed, "evidenceEventIds": [],
                "timestampBasis": "Modal app list created_at if timezone-qualified; snapshot observed at collection"}
            machines[identifier] = machine
            event = _event(identifier + ":snapshot:" + observed, observed, "machine_snapshot", f"Modal · {name} · observed {machine['state']}",
                json.dumps({key: machine[key] for key in ("app", "label", "state", "location", "createdAt")}, indent=2), "modal", location,
                machineId=identifier, app=str(app_id), lifecycle="snapshot", timestampBasis="collection observation", currentSnapshot=True)
            events.append(event)
            _link_machine(machine, event)
            if created:
                event = _event(identifier + ":create:" + created, created, "machine_create", f"Modal · {name} · app created",
                    "App creation returned by Modal app list; individual sandbox/container lifecycle is not available in this snapshot.", "modal", location,
                    machineId=identifier, app=str(app_id), lifecycle="create", timestampBasis="modal.app.created_at")
                events.append(event)
                _link_machine(machine, event)
            if config.get("modal_logs", True):
                try:
                    raw, stderr = _run([executable, "app", "logs", str(app_id), "--timestamps", "--show-container-id", "--tail", str(config.get("modal_log_tail", 2000))], repo, timeout=45)
                    for line in (raw + "\n" + stderr).splitlines():
                        # Modal can print colored output; remove terminal escapes.
                        line = re.sub(r"\x1b\[[0-9;]*m", "", line)
                        match = _LOG_TIME.match(line.strip())
                        if not match or not _utc(match[1]):
                            stats["modalLogsWithoutQualifiedTimestamp"] += 1
                            continue
                        event = _event(identifier + ":log:" + stable_id(line), match[1], "machine_log", f"Modal · {name} · app log", match[2], "modal", location,
                            machineId=identifier, app=str(app_id), lifecycle="log", timestampBasis="modal.app.logs --timestamps", observedAt=observed)
                        events.append(event)
                        _link_machine(machine, event)
                        stats["modalLogLines"] += 1
                except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                    notes.append("Modal app logs: " + sanitize(str(error))[:180])
        notes.append(f"Modal read-only app list returned {len(rows)} currently running/deployed/recent apps; only project matches are exported. This does not establish deletion dates for historical apps. Historical tool outputs and execution reports remain part of the archive.")
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        notes.append("Modal live app list unavailable: " + sanitize(str(error))[:200])
        stats["sourceFailures"] += 1


def _ci_reports(repo, config, observed, events, machines, builds, notes, stats, report_paths):
    home = Path(config.get("codex_home") or os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    repository = config.get("github_repository", "mario-andreschak/factored-hackathon-2026-mcg")
    roots = [Path(path) for path in config.get("ci_evidence_roots", [])]
    # Ownership manifests only establish scope and an evidence directory. Their
    # ownership tokens are never retained in the exported report.
    for ownership in (home / "ci").glob("*/owned-run.json"):
        try:
            row = json.loads(ownership.read_text(encoding="utf-8"))
            if row.get("repository") != repository:
                continue
            path = Path(row.get("evidence", ""))
            if path.is_dir() and (path.is_relative_to(home / "visualizations") or path.is_relative_to(repo)):
                roots.append(path)
                # Local and Modal workers share a project evidence root.
                for parent in path.parents:
                    if parent.name == "pr-review-automation":
                        roots.append(parent / "local-ci")
                        break
        except (OSError, ValueError):
            continue
    for root in dict.fromkeys(roots):
        if not root.is_dir():
            continue
        for directory, directories, filenames in os.walk(root):
            directories[:] = [name for name in directories if name not in _EXCLUDED_DIRS and not name.startswith(".")]
            for name in filenames:
                if name.endswith(".json") and re.search(r"(?:summary|result|report|execution|receipt)", name, re.I) and not re.search(r"dry|plan|template|attestation|secret|auth|config|policy", name, re.I):
                    report_paths.add(Path(directory) / name)
    for path in sorted(report_paths, key=str):
        if any(part.lower() in _EXCLUDED_DIRS for part in path.parts) or re.search(r"secret|credential|token|policy|auth|config|template|dry.plan", path.name, re.I):
            continue
        try:
            if path.stat().st_size > 8_000_000:
                stats["oversizeReportsSkipped"] += 1
                continue
            row = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if not isinstance(row, dict) or row.get("executed") is False:
            continue
        if row.get("repository") and row["repository"] != repository:
            continue
        time_field = next((key for key in ("started_at", "finished_at", "completed_at", "timestamp", "created_at", "generated_at") if _utc(row.get(key))), None)
        if not time_field:
            stats["reportsWithoutAuthoritativeTime"] += 1
            continue
        if not any(key in row for key in ("exit_code", "exitCode", "status", "executed", "all_gates_passed", "results", "reports", "receipts")):
            continue
        provider = "modal" if "modal" in str(path).lower() or row.get("app_id") else "local"
        location = "Modal cloud · location not recorded" if provider == "modal" else "Local · Windows/Linux CI worker"
        safe = _safe_report(row)
        time = _utc(row[time_field])
        identifier = "ci-report:" + stable_id(str(path))
        state = str(row.get("status") or ("passed" if row.get("all_gates_passed") else "observed"))
        event = _event(identifier + ":" + stable_id(safe), time, "ci_execution_report", f"{provider.title()} CI · {row.get('gate_id') or row.get('mode') or path.parent.name} · {state}",
            json.dumps(safe, ensure_ascii=False, indent=2), provider, location, buildId=identifier, state=state, reportPath=str(path),
            headSha=row.get("head_sha"), timestampBasis="execution report." + time_field, observedAt=observed)
        events.append(event)
        builds.append({"id": identifier, "provider": provider, "location": location, "timestamp": time, "startedAt": _utc(row.get("started_at")),
            "finishedAt": _utc(row.get("finished_at") or row.get("completed_at")), "state": state, "headSha": row.get("head_sha"),
            "evidenceEventIds": [event["id"]], "timestampBasis": event["metadata"]["timestampBasis"]})
        app_id = row.get("app_id") or row.get("appId")
        if provider == "modal" and app_id:
            machine_id = "modal:" + str(app_id)
            machine = machines.setdefault(machine_id, {"id": machine_id, "label": str(app_id), "provider": "modal", "location": location,
                "createdAt": None, "firstTimestamp": time, "state": state, "currentSnapshot": False, "evidenceEventIds": [],
                "timestampBasis": "saved CI report; sandbox creation time unavailable"})
            event["metadata"]["machineId"] = machine_id
            _link_machine(machine, event)
        stats["ciExecutionReports"] += 1
    notes.append("CI reports use recorded execution dates, never filesystem modification times. Dry plans and setup/authorization/config files are excluded. Report fields are allowlisted; ownership tokens and input datasets are excluded.")


def _associate_machine_evidence(events, machines):
    """Connect executed commands to observed identities without inferred births.

    A reused Docker name is a logical worker until its exact container ID is
    established. Modal app IDs denote apps, not invented persistent sandboxes.
    """
    for event in events:
        metadata = event.get("metadata") or {}
        if metadata.get("machineId"):
            continue
        command = metadata.get("command") or ""
        provider = metadata.get("provider")
        if not command:
            continue
        associated = []
        for machine in list(machines.values()):
            if machine["provider"] != provider:
                continue
            identifiers = [machine.get("label"), machine["id"].split(":")[-1]]
            if any(identifier and re.search(r"(?<![a-zA-Z0-9_.-])" + re.escape(str(identifier)) + r"(?![a-zA-Z0-9_.-])", command) for identifier in identifiers):
                # Names may be reused after a container was removed. Earlier
                # commands cannot silently acquire the current container ID.
                if machine.get("createdAt") and event["timestamp"] < machine["createdAt"]:
                    continue
                associated.append(machine)
        if provider == "docker" and not associated:
            name = re.search(r"--name(?:=|\s+)[\"']?([a-zA-Z0-9_.-]+)", command)
            returned_id = re.search(r"(?:^|\n)([0-9a-f]{64})(?:\s|$)", event.get("body", ""))
            if name and returned_id and metadata.get("state") in {"completed", "output_observed"}:
                identifier = "docker:" + returned_id[1]
                machine = machines.setdefault(identifier, {"id": identifier, "label": name[1], "provider": "docker", "location": metadata["location"],
                    "createdAt": None, "firstTimestamp": event["timestamp"], "state": "historical command output", "currentSnapshot": False,
                    "lastObservedAt": metadata.get("outputTimestamp") or event["timestamp"], "evidenceEventIds": [],
                    "timestampBasis": "container ID returned by executed command; creation time not recorded"})
                associated.append(machine)
        if provider == "fly":
            app = metadata.get("app")
            if app:
                for match in re.finditer(r"\bmachine(?:\s+ID)?[\s:=]+([0-9a-f]{14})\b", event.get("body", ""), re.I):
                    identifier = "fly:" + app + ":" + match[1]
                    machine = machines.setdefault(identifier, {"id": identifier, "label": match[1], "app": app, "provider": "fly",
                        "location": "Fly region unspecified in saved command output", "createdAt": None, "firstTimestamp": event["timestamp"],
                        "state": "historical command output", "currentSnapshot": False, "lastObservedAt": metadata.get("outputTimestamp") or event["timestamp"],
                        "evidenceEventIds": [], "timestampBasis": "machine ID in executed Fly output; lifecycle date not inferred"})
                    associated.append(machine)
        if provider == "modal":
            # --help, web documentation and shell batches may contain example
            # app IDs. Only actual app-list rows, executed app-log targets, or
            # provider run URLs establish a historical app identity.
            app_rows = {}
            if re.search(r"\bmodal(?:\.exe)?\s+app\s+list\b", command, re.I):
                pending = [event.get("body", "")]
                for _ in range(5):
                    following = []
                    for raw in pending:
                        for row in _json_values(raw):
                            if not isinstance(row, dict):
                                continue
                            if row.get("app_id") and ("description" in row or "state" in row):
                                app_rows[str(row["app_id"])] = row
                            for key in ("output", "text", "stdout", "content"):
                                if isinstance(row.get(key), str):
                                    following.append(row[key])
                                elif isinstance(row.get(key), list):
                                    following.extend(str(item.get("text") or "") for item in row[key] if isinstance(item, dict))
                    pending = following
            app_ids = set(app_rows)
            log_target = re.search(r"\bmodal(?:\.exe)?\s+app\s+logs\s+(ap-[a-zA-Z0-9]{10,})\b", command, re.I)
            if log_target and metadata.get("state") != "failed":
                app_ids.add(log_target[1])
            if metadata.get("state") != "failed" and metadata.get("state") != "command_observed" and re.search(r"\bmodal(?:\.exe)?\s+(?:run|deploy)\b|run_modal.*--execute", command, re.I):
                app_ids.update(re.findall(r"View run at\s+https://modal\.com/apps/[^\s]+/(ap-[a-zA-Z0-9]{10,})", event.get("body", "")))
            for app_id in app_ids:
                identifier = "modal:" + app_id
                row = app_rows.get(app_id, {})
                created = _utc(row.get("created_at") or row.get("Created at"))
                machine = machines.setdefault(identifier, {"id": identifier, "label": row.get("description") or app_id, "app": app_id, "provider": "modal",
                    "location": "Modal cloud · region not recorded", "createdAt": created, "firstTimestamp": created or event["timestamp"],
                    "state": row.get("state") or "historical app execution", "currentSnapshot": False, "lastObservedAt": metadata.get("outputTimestamp") or event["timestamp"],
                    "evidenceEventIds": [], "timestampBasis": "provider app-list created_at when recorded; otherwise app observation, sandbox lifecycle not inferred"})
                associated.append(machine)
        unique = {machine["id"]: machine for machine in associated}
        if unique:
            metadata["machineIds"] = list(unique)
            if len(unique) == 1:
                metadata["machineId"] = next(iter(unique))
            metadata["machineAssociationBasis"] = "Explicit identity in executed command/output; reused names before current container creation are not matched."
            for machine in unique.values():
                _link_machine(machine, event)


def collect(repo: Path, config: dict):
    options = {**config, **config.get("infrastructure", {})}
    observed = timestamp(datetime.now(timezone.utc).isoformat())
    events, machines, deployments, builds, notes, stats = [], {}, [], [], [], Counter()
    _docker(repo, options, observed, events, machines, builds, notes, stats)
    _fly(repo, options, observed, events, machines, deployments, notes, stats)
    _modal(repo, options, observed, events, machines, notes, stats)
    report_paths = set()
    _codex_tools(repo, options, events, builds, deployments, notes, stats, report_paths)
    _flujo_tools(repo, options, events, builds, deployments, notes, stats)
    _ci_reports(repo, options, observed, events, machines, builds, notes, stats, report_paths)
    _associate_machine_evidence(events, machines)
    unique = {event["id"]: event for event in events if event.get("timestamp")}
    builds = list({record["id"]: record for record in builds}.values())
    deployments = list({record["id"]: record for record in deployments}.values())
    stats.update(events=len(unique), machines=len(machines), deployments=len(deployments), builds=len(builds))
    return sanitize({"events": sorted(unique.values(), key=lambda value: (value["timestamp"], value["id"])),
        "status": "partial" if stats["sourceFailures"] else "ok" if unique else "unavailable", "notes": notes,
        "stats": dict(stats), "machines": list(machines.values()), "deployments": deployments, "builds": builds, "observedAt": observed})
