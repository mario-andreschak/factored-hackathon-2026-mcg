"""Measure an existing approved Process flow through normal chat; never create flows.

The manifest is private: it contains execution credentials, a frontend signing-key
path, and a per-subject transaction-reference oracle. Do not commit it. Example
shape (all values are placeholders):
  {"base_url":"http://127.0.0.1:43420", "model":"flow-approved-inquiry",
   "execution_token":"...", "frontend_signing_key_file":"/private/front.pem",
   "frontend_kid":"front", "frontend_issuer":"test-frontend",
   "frontend_audience":"flujo-banking-ingress", "approved_flow_file":"...",
   "provider_scope":"configured-codex-restricted", "oracle_scope":"response",
   "cases":[{"subject":"approved-subject",
   "prompt":"List one transaction and its transaction reference.",
   "allowed_references":["txn_0123456789ab"]}]}

Requires PyJWT/cryptography from requirements-mcp.txt. Run from the repo root:
  python scripts/banking_acceptance_load.py --manifest PRIVATE.json --phases 1,10,50,500

Output contains aggregates only. Provider provenance is operator supplied, not
runtime-attested. This runner does not measure server admission, provider retries,
S3 time or RSS; it reports those as unmeasured rather than inferring them. A live
model response alone is insufficient to prove tool execution. By default, each
response must include a matching structured tool result. Bound normal chat omits
private tool history: set oracle_scope="response" explicitly to check final masked
transaction references and audit private tool history separately. Restricted Codex
uses provider_scope="configured-codex-restricted" only after native profile gates.
Run deterministic Process tests separately.

An explicitly declared workload="static-prefetch-model-summary" instead measures
a real protected Static lookup followed by a terminal, tool-free model summary.
It requires separate persisted tool/owner/model-attempt evidence; it is not proof
of autonomous model tool calling. The default continues to reject Static calls.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import json
from pathlib import Path
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import uuid


REFERENCE = re.compile(r"^txn_[a-f0-9]{12}$")
MAX_RESPONSE = 4 * 1024 * 1024
VISIBLE_REFERENCE = re.compile(r"\btxn_[a-f0-9]{12}\b")


class AcceptanceError(Exception):
    """Only fixed error codes may be emitted, never response bodies or subjects."""


@dataclass(frozen=True)
class Sample:
    ok: bool
    code: str
    seconds: float
    first_body_byte_seconds: float | None = None
    conversation: str | None = None


def validate_manifest(config: dict, maximum: int) -> None:
    url = urlsplit(config["base_url"])
    if (url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost", "::1"}
            or url.path not in {"", "/"} or url.query or url.fragment or url.username):
        raise AcceptanceError("existing_local_worker_required")
    if not config["model"].startswith("flow-"):
        raise AcceptanceError("graphical_flow_required")
    if config.get("provider_scope") not in {"configured-api", "configured-codex-restricted"}:
        raise AcceptanceError("configured_provider_scope_required")
    graph = json.loads(Path(config["approved_flow_file"]).read_text(encoding="utf-8"))
    if config["model"] != "flow-" + graph["name"]:
        raise AcceptanceError("approved_flow_model_mismatch")
    kinds = [node.get("data", {}).get("type", node.get("type")) for node in graph["nodes"]]
    if "process" not in kinds:
        raise AcceptanceError("process_flow_required")
    workload = config.get("workload", "model-tools")
    if workload not in {"model-tools", "static-prefetch-model-summary"}:
        raise AcceptanceError("invalid_workload")
    static_calls = []
    for node in graph["nodes"]:
        props = node.get("data", {}).get("properties", {})
        static_calls.extend(entry for entry in props.get("entries", []) if entry.get("kind") == "toolCall")
    if workload == "model-tools" and static_calls:
        raise AcceptanceError("static_tool_workload_not_model_proof")
    if workload == "static-prefetch-model-summary":
        validate_snapshot_graph(config, graph, static_calls)
    cases = config["cases"][:maximum]
    if len(cases) != maximum or len({case["subject"] for case in cases}) != maximum:
        raise AcceptanceError("distinct_subjects_required")
    references: set[str] = set()
    for case in cases:
        allowed = set(case["allowed_references"])
        if not allowed or any(not REFERENCE.fullmatch(ref) for ref in allowed):
            raise AcceptanceError("private_reference_oracle_required")
        if references.intersection(allowed):
            raise AcceptanceError("oracle_owner_overlap")
        references.update(allowed)
        if not isinstance(case["prompt"], str) or not case["prompt"].strip():
            raise AcceptanceError("prompt_required")


def validate_snapshot_graph(config: dict, graph: dict, calls: list[dict]) -> None:
    """Reject fixtures, authored answers, or native tool bridges in this scope."""
    nodes = graph["nodes"]
    kind = lambda node: node.get("data", {}).get("type", node.get("type"))
    props = lambda node: node.get("data", {}).get("properties", {})
    process = [node for node in nodes if kind(node) == "process"]
    start = [node for node in nodes if kind(node) == "start"]
    static = [node for node in nodes if kind(node) == "static"]
    mcp = [node for node in nodes if kind(node) == "mcp"]
    server = config.get("protected_server_name")
    if (config.get("oracle_scope") != "response" or not isinstance(server, str) or not server
            or not config.get("summary_model_ref") or len(process) != 1 or len(static) != 1
            or len(mcp) != 1 or len(start) != 1 or len(nodes) != 4 or len(calls) != 1
            or props(process[0]).get("boundModel") != config["summary_model_ref"]
            or props(process[0]).get("inputMode", "full-history") != "full-history"
            or props(static[0]).get("entries") != calls
            or props(mcp[0]).get("boundServer") != server
            or props(mcp[0]).get("enabledTools") != ["list_my_transactions"]):
        raise AcceptanceError("bounded_real_snapshot_summary_required")
    if props(process[0]).get("mcpNodes") or props(process[0]).get("availableTools"):
        raise AcceptanceError("terminal_tool_free_process_required")
    call = calls[0]
    if (call.get("executionMode") != "real" or call.get("serverName") != server
            or call.get("toolName") != "list_my_transactions"):
        raise AcceptanceError("real_snapshot_tool_required")
    try:
        args = json.loads(call.get("argumentsJson", "{}"))
        if (not isinstance(args, dict) or set(args) - {"limit", "start_date", "end_date"}
                or not isinstance(args.get("limit"), int) or isinstance(args["limit"], bool)
                or not 1 <= args["limit"] <= 5):
            raise ValueError()
    except (TypeError, ValueError):
        raise AcceptanceError("bounded_snapshot_arguments_required") from None
    edges = graph.get("edges", [])
    if any(edge.get("source") == process[0]["id"] for edge in edges):
        raise AcceptanceError("terminal_tool_free_process_required")
    attachment = [edge for edge in edges if edge.get("data", {}).get("edgeType") == "mcp"]
    if (len(attachment) != 1 or attachment[0].get("source") != static[0]["id"]
            or attachment[0].get("target") != mcp[0]["id"]
            or attachment[0].get("sourceHandle") != "static-right-mcp"
            or attachment[0].get("targetHandle") != "mcp-left"):
        raise AcceptanceError("connected_real_snapshot_tool_required")
    expected = {(start[0]["id"], static[0]["id"], "standard"),
                (static[0]["id"], process[0]["id"], "standard"),
                (static[0]["id"], mcp[0]["id"], "mcp")}
    actual = {(edge.get("source"), edge.get("target"), edge.get("data", {}).get("edgeType"))
              for edge in edges}
    if len(edges) != 3 or len({node["id"] for node in nodes}) != 4 or actual != expected:
        raise AcceptanceError("linear_snapshot_then_summary_required")


def tool_references(value: object) -> set[str]:
    """Traverse only structured tool evidence, including FLUJO's JSON wrappers."""
    if isinstance(value, str):
        try:
            return tool_references(json.loads(value))
        except (ValueError, RecursionError):
            return set()
    if isinstance(value, list):
        return set().union(*(tool_references(child) for child in value))
    if isinstance(value, dict):
        ref = value.get("transaction_reference")
        found = {ref} if isinstance(ref, str) and REFERENCE.fullmatch(ref) else set()
        for child in value.values():
            if isinstance(child, (dict, list, str)):
                found.update(tool_references(child))
        return found
    return set()


def audit_response(case: dict, body: dict, oracle_scope: str = "structured-tool") -> str:
    if body.get("status") not in {"completed", "waiting_for_input"}:
        raise AcceptanceError("turn_not_completed")
    conversation = body.get("conversation_id")
    if not isinstance(conversation, str) or not conversation:
        raise AcceptanceError("conversation_evidence_missing")
    messages = body.get("messages", [])
    references: set[str] = set()
    tool_calls = 0
    for message in messages:
        if message.get("role") == "assistant":
            tool_calls += len(message.get("tool_calls", []))
        if message.get("role") == "tool":
            references.update(tool_references(message.get("content")))
    if oracle_scope == "response":
        # Normal bound chat intentionally omits private tool history. This mode
        # audits final answer references, not proof that a tool was executed.
        choices = body.get("choices", [])
        answer = choices[0].get("message", {}).get("content", "") if choices else ""
        references.update(VISIBLE_REFERENCE.findall(answer) if isinstance(answer, str) else [])
        if not references:
            raise AcceptanceError("response_reference_evidence_missing")
    elif not references or not tool_calls:
        raise AcceptanceError("process_tool_evidence_missing")
    if not references.issubset(set(case["allowed_references"])):
        raise AcceptanceError("foreign_transaction_result")
    return conversation


def request_headers(config: dict, case: dict, signing_key: str) -> dict[str, str]:
    import jwt  # Live-only dependency: unit tests never mint customer assertions.

    now = int(time.time())
    token = jwt.encode({"iss": config["frontend_issuer"], "aud": config["frontend_audience"],
        "sub": case["subject"], "session_id": case["session_id"], "session_exp": case["session_exp"],
        "iat": now, "nbf": now, "exp": min(now + 120, case["session_exp"]),
        "jti": str(uuid.uuid4()), "scope": ["bank:read"]}, signing_key, algorithm="EdDSA",
        headers={"kid": config["frontend_kid"], "typ": "flujo-ingress+jwt"})
    return {"Content-Type": "application/json", "Authorization": "Bearer " + config["execution_token"],
            "X-Flujo-User-Assertion": token}


def one(config: dict, case: dict, signing_key: str, barrier: threading.Barrier,
        timeout: float) -> Sample:
    barrier.wait(timeout=30)
    started = time.perf_counter()
    first_byte = None
    try:
        payload = {"model": config["model"], "messages": [{"role": "user", "content": case["prompt"]}],
                   "stream": False, "metadata": {"flujo": "true"}}
        request = Request(config["base_url"].rstrip("/") + "/v1/chat/completions", method="POST",
            headers=request_headers(config, case, signing_key), data=json.dumps(payload).encode())
        with urlopen(request, timeout=timeout) as response:
            prefix = response.read(1)
            first_byte = time.perf_counter() - started
            raw = prefix + response.read(MAX_RESPONSE)
            if len(raw) > MAX_RESPONSE:
                raise AcceptanceError("response_limit_exceeded")
            body = json.loads(raw)
        conversation = audit_response(case, body, config.get("oracle_scope", "structured-tool"))
        return Sample(True, "ok", time.perf_counter() - started, first_byte, conversation)
    except AcceptanceError as error:
        code = str(error)
    except HTTPError as error:
        code = f"http_{error.code}"
        error.close()
    except (TimeoutError, URLError):
        code = "transport_failure"
    except Exception:
        code = "invalid_response_or_configuration"
    return Sample(False, code, time.perf_counter() - started, first_byte)


def percentile(values: list[float], percent: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, (len(ordered) * percent + 99) // 100 - 1)], 6)


def summarize(samples: list[Sample], elapsed: float) -> dict:
    conversations = [sample.conversation for sample in samples if sample.ok]
    codes = Counter(sample.code for sample in samples if not sample.ok)
    if len(set(conversations)) != len(conversations):
        codes["conversation_reused_across_distinct_owners"] += len(conversations) - len(set(conversations))
    success = sum(sample.ok for sample in samples)
    return {"submitted_distinct_customers": len(samples), "successful_oracles": success,
        "passed": success == len(samples) and not codes, "errors": dict(codes),
        "full_response_seconds": {f"p{p}": percentile([s.seconds for s in samples], p) for p in (50, 95, 99)},
        "first_body_byte_seconds": {f"p{p}": percentile([s.first_body_byte_seconds for s in samples
            if s.first_body_byte_seconds is not None], p) for p in (50, 95, 99)},
        "elapsed_seconds": round(elapsed, 6), "completed_requests_per_second": round(len(samples) / elapsed, 3),
        "maximum_server_active_runs": None, "queue_provider_tool_s3_breakdown": None,
        "provider_retry_rate_limit_counts": None, "server_memory_bytes": None}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--phases", default="1,10,50,500")
    parser.add_argument("--timeout-seconds", type=float, default=180)
    args = parser.parse_args()
    try:
        phases = [int(value) for value in args.phases.split(",")]
        if not phases or any(value not in {1, 10, 50, 500} for value in phases) or args.timeout_seconds <= 0:
            raise AcceptanceError("invalid_phase_or_timeout")
        config = json.loads(args.manifest.read_text(encoding="utf-8"))
        validate_manifest(config, max(phases))
        if config.get("oracle_scope", "structured-tool") not in {"structured-tool", "response"}:
            raise AcceptanceError("invalid_oracle_scope")
        signing_key = Path(config["frontend_signing_key_file"]).read_text(encoding="utf-8")
        session_exp = int(time.time()) + 3600
        for case in config["cases"]:
            case.setdefault("session_id", str(uuid.uuid4()))
            case.setdefault("session_exp", session_exp)
        snapshot = config.get("workload") == "static-prefetch-model-summary"
        evidence = {"scope": "normal_completion_snapshot_model_summary" if snapshot else "normal_completion_process",
            "provider_scope": config["provider_scope"],
            "oracle_scope": config.get("oracle_scope", "structured-tool"),
            "private_tool_history_audit": "required separately when oracle_scope=response",
            "provenance": "operator-supplied approved flow; running deployment must be attested separately",
            "static_calls_per_request": 1 if snapshot else 0,
            "model_attempt_and_private_tool_owner_audit": "required separately" if snapshot else "private tool audit required",
            "saved_flow_mutations": 0, "phases": []}
        for count in phases:
            started = time.perf_counter()
            barrier = threading.Barrier(count)
            with ThreadPoolExecutor(max_workers=count) as pool:
                futures = [pool.submit(one, config, case, signing_key, barrier, args.timeout_seconds)
                           for case in config["cases"][:count]]
                samples = [future.result() for future in as_completed(futures)]
            summary = summarize(samples, time.perf_counter() - started)
            evidence["phases"].append(summary)
            if not summary["passed"]:
                break  # Resolve the first failing workload before increasing paid load.
        print(json.dumps(evidence, indent=2))
        return 0 if len(evidence["phases"]) == len(phases) and all(p["passed"] for p in evidence["phases"]) else 1
    except AcceptanceError as error:
        print(json.dumps({"passed": False, "error": str(error)}))
    except Exception:
        print(json.dumps({"passed": False, "error": "invalid_private_manifest_or_runtime"}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
