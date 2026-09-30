"""Real browser HTTP probes; no application is imported or started on import."""
from __future__ import annotations

import http.cookiejar
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid

from contract import CheckpointError, require, require_runtime_release, strict_json


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Browser:
    def __init__(self, origin: str):
        parsed = urllib.parse.urlsplit(origin)
        require(parsed.scheme == "http" and parsed.hostname == "127.0.0.1"
                and parsed.port and parsed.path == "" and not parsed.query
                and not parsed.fragment and not parsed.username, "loopback_frontend_required")
        self.origin = origin
        self.cookies = http.cookiejar.CookieJar()
        self.opener = None

    def request(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        require_runtime_release(dict(os.environ))
        if self.opener is None:
            self.opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(self.cookies), NoRedirect())
        require(path.startswith("/api/") and not path.startswith("/api/chat"),
                "model_ingress_forbidden")
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        request = urllib.request.Request(self.origin + path, data=data, method=method,
                                         headers={"Content-Type": "application/json",
                                                  "Origin": self.origin})
        try:
            response = self.opener.open(request, timeout=60)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read(1024 * 1024 + 1)
            require(len(raw) <= 1024 * 1024, "browser_response_limit")
            try:
                value = strict_json(raw) if raw else {}
            except (ValueError, UnicodeError):
                raise CheckpointError("non_json_browser_response") from None
            require(isinstance(value, dict), "browser_response_object_required")
            return response.status, value

    def cookie_header(self) -> str:
        request = urllib.request.Request(self.origin + "/api/auth/me")
        self.cookies.add_cookie_header(request)
        return request.get_header("Cookie", "")


def snapshot(provider) -> dict:
    result = provider.observe()
    require(set(result) == {"cases", "receipts", "handoffs", "pending", "tool_calls",
                            "external_model_requests_attempted", "fixture_provider_calls",
                            "forwarded_faults", "forbidden_writes"}, "observer_contract")
    require(all(type(result[k]) is int and result[k] >= 0
                for k in ("cases", "receipts", "handoffs", "pending",
                          "external_model_requests_attempted", "fixture_provider_calls",
                          "forwarded_faults", "forbidden_writes")), "observer_count_type")
    require(result["external_model_requests_attempted"] == 0 and result["forbidden_writes"] == 0,
            "forbidden_execution_observed")
    require(isinstance(result["tool_calls"], dict)
            and set(result["tool_calls"]) <= {"banking_status", "list_my_transactions",
                "get_my_transaction", "prepare_unrecognized_charge", "confirm_simulated_intake",
                "read_intake_receipt", "create_verified_handoff", "read_verified_handoff"}
            and all(type(n) is int and n >= 0 for n in result["tool_calls"].values()),
            "stdio_observer_required")
    return result


def unchanged(before: dict, after: dict) -> None:
    require(all(before[k] == after[k] for k in ("cases", "receipts", "handoffs")),
            "unexpected_action_write")


def denied_unchanged(before: dict, after: dict) -> None:
    unchanged(before, after)
    require(before["pending"] == after["pending"] and before["tool_calls"] == after["tool_calls"],
            "denial_created_pending_or_dispatched_mcp")


def coverage(provider, *, complete: bool) -> dict:
    observed = provider.read_coverage()
    require(set(observed) == {"rows", "configured_start_matches", "generation_matches", "complete"}
            and type(observed["rows"]) is int
            and all(type(observed[k]) is bool for k in
                    ("configured_start_matches", "generation_matches", "complete"))
            and observed["rows"] == (1 if complete else 0)
            and all(observed[k] is complete for k in
                    ("configured_start_matches", "generation_matches", "complete")),
            "independent_coverage_observation")
    return observed


def consumed_fault(provider, actor: str, operation: str, target: str, *, receipt=None, handoff_id=None) -> None:
    marker = provider.read_consumed_fault(actor, operation, target)
    expected = {"operation": operation, "target_matches": True, "completed_upstream": True,
                "consumed": True, "consent": operation == "confirm", "receipt": receipt,
                "handoff_id": handoff_id}
    from consume_package import typed_equal
    require(typed_equal(marker, expected), "correlated_completed_response_drop_required")


def saved_receipt(provider, result: dict) -> dict:
    receipt = result.get("receipt")
    require(isinstance(receipt, dict) and receipt.get("status") == "received"
            and receipt.get("kind") == "simulated_intake" and receipt.get("simulated") is True,
            "verified_receipt_required")
    require(provider.read_saved_receipt(receipt["id"]) == receipt, "independent_receipt_mismatch")
    return receipt


def saved_handoff(provider, result: dict, *, questions: list[str], general: bool) -> dict:
    handoff = result.get("handoff")
    require(isinstance(handoff, dict) and handoff.get("human_responded") is False,
            "verified_handoff_required")
    raw = provider.read_saved_handoff(handoff["id"])
    packet = raw.get("packet", {})
    require(packet.get("schema") == "banking-sandbox-handoff/v1"
            and packet.get("unanswered_questions") == questions
            and packet.get("human_responded") is False
            and raw["id"] == handoff["id"] and raw["reason"] == handoff["reason"],
            "independent_handoff_mismatch")
    require(handoff.get("unanswered_questions") == questions
            and handoff.get("transaction_provenance") == packet.get("transaction_provenance")
            and handoff.get("facts") == raw.get("facts"), "handoff_projection_mismatch")
    if general:
        require(packet.get("transaction") is None and packet.get("transaction_provenance") is None
                and raw.get("snapshot") is None and raw.get("facts") == {}
                and raw.get("transaction_currentness") == "not_applicable", "general_handoff_facts")
    else:
        require(packet.get("transaction") == raw.get("facts")
                and isinstance(packet.get("transaction_provenance"), dict)
                and packet["transaction_provenance"]["snapshot"] == raw["snapshot"],
                "selected_handoff_facts")
    return raw


def run_stock(provider) -> dict:
    """Existing bank71 behavior with freshly generated data and no coverage backdating."""
    before = snapshot(provider)
    require(before["cases"] == before["receipts"] == before["handoffs"] == before["pending"] == 0,
            "preloaded_action_evidence_forbidden")
    require(before["fixture_provider_calls"] > 0, "ordinary_runflow_bootstrap_required")
    coverage(provider, complete=False)
    observations = []

    def record(name):
        observations.append({"scenario": name, "status": "passed", "counts": snapshot(provider)})

    def login(actor):
        browser = Browser(provider.frontend_origin)
        code, result = browser.request("POST", "/api/auth/login", provider.credentials(actor))
        require(code == 200 and result.get("authenticated") is True, "fixture_login_failed")
        return browser

    anonymous = Browser(provider.frontend_origin)
    code, _ = anonymous.request("POST", "/api/action/prepare",
                                 {"transaction_reference": "txn_" + "a" * 24})
    require(code in {401, 403}, "anonymous_action_accepted")
    denied_unchanged(before, snapshot(provider))
    record("stock_anonymous_denied")
    es, pt = login("es"), login("pt")
    references = {actor: provider.bind_selection(actor, browser.cookie_header(), "normal")
                  for actor, browser in (("es", es), ("pt", pt))}
    before = snapshot(provider)
    code, _ = es.request("POST", "/api/action/prepare",
                         {"transaction_reference": references["pt"], "language": "es"})
    require(code in {403, 404}, "foreign_selection_accepted")
    denied_unchanged(before, snapshot(provider))
    record("stock_foreign_selection_denied")
    for actor, browser in (("es", es), ("pt", pt)):
        body = {"transaction_reference": references[actor],
                "request_id": str(uuid.uuid4()), "language": actor}
        before = snapshot(provider)
        code, result = browser.request("POST", "/api/action/prepare", body)
        require(code == 200 and result.get("state") == "handoff_verified"
                and result.get("reason") == "missing_evidence", "fresh_ledger_must_not_claim_coverage")
        coverage(provider, complete=False)
        require(isinstance(result.get("request_id"), str), "host_prepare_request_id_required")
        risk = provider.read_risk_by_request(actor, result["request_id"])
        require(risk.get("risk_data_complete") is False
                and "unrecognized_count_24h" in risk and risk["unrecognized_count_24h"] is None,
                "stock_incomplete_risk_must_have_null_count")
        original = saved_handoff(provider, result, questions=[], general=False)
        after = snapshot(provider)
        require(after["cases"] == after["receipts"] == 0
                and after["handoffs"] == before["handoffs"] + 1, "stock_intake_without_coverage")
        code, retry = browser.request("GET", "/api/action/status?language=" + actor)
        require(code == 200 and saved_handoff(provider, retry, questions=[], general=False) == original,
                "stock_handoff_status_changed")
        unchanged(after, snapshot(provider))
        before_denial = snapshot(provider)
        code, _ = browser.request("POST", "/api/action/confirm",
            {"transaction_reference": references[actor], "pending_handle": result["pending_handle"],
             "confirmed": False, "language": actor})
        require(code == 422, "false_confirmation_accepted")
        denied_unchanged(before_denial, snapshot(provider))
        record(actor + "_stock_missing_coverage_handoff_status")
    browser = login("pt")
    provider.bind_general("pt", browser.cookie_header())
    questions = ["Qual informação falta?"]
    body = {"reason": "customer_request", "request_id": str(uuid.uuid4()),
            "language": "pt", "unanswered_questions": questions}
    before = snapshot(provider)
    code, result = browser.request("POST", "/api/action/handoff", body)
    require(code == 200 and result.get("state") == "handoff_verified", "stock_general_handoff_failed")
    original = saved_handoff(provider, result, questions=questions, general=True)
    after = snapshot(provider)
    require(after["handoffs"] == before["handoffs"] + 1, "stock_general_handoff_count")
    code, retry = browser.request("POST", "/api/action/handoff",
                                  {k: v for k, v in body.items() if k != "unanswered_questions"})
    require(code == 200 and saved_handoff(provider, retry, questions=questions, general=True) == original,
            "stock_general_handoff_retry_changed")
    unchanged(after, snapshot(provider))
    code, _ = browser.request("POST", "/api/action/handoff",
                              {**body, "unanswered_questions": ["Pergunta diferente?"]})
    require(code == 409, "changed_handoff_questions_accepted")
    unchanged(after, snapshot(provider))
    provider.restart_preserving_state()
    code, recovered = browser.request("GET", "/api/action/status?language=pt")
    require(code == 200 and saved_handoff(provider, recovered, questions=questions, general=True) == original,
            "stock_handoff_restart_readback")
    unchanged(after, snapshot(provider))
    record("stock_general_handoff_questions_retry_restart")
    return {"schema": "banking-synthetic-assembly-observations/v1",
            "proof_kind": "deterministic_fixture_provider_stock_boundaries",
            "scenarios": observations, "final_counts": snapshot(provider),
            "unproven": ["positive_intake_receipt", "business_clock_r16", "deep_mcp_write_fault",
                         "real_model_es_pt", "customer_acceptance", "human_adjudication",
                         "capacity", "held_out_baseline_comparison", "shared_deployment"]}


def run(provider) -> dict:
    """Provider supplies reviewed generation/IPC, never HTTP or MCP responses."""
    observations = []
    initial = snapshot(provider)
    require(initial["cases"] == initial["receipts"] == initial["handoffs"] == initial["pending"] == 0,
            "preloaded_action_evidence_forbidden")
    require(initial["fixture_provider_calls"] > 0, "ordinary_runflow_bootstrap_required")
    coverage(provider, complete=True)

    def record(name):
        observations.append({"scenario": name, "status": "passed", "counts": snapshot(provider)})

    def login(actor):
        browser = Browser(provider.frontend_origin)
        status, value = browser.request("POST", "/api/auth/login", provider.credentials(actor))
        require(status == 200 and value.get("authenticated") is True, "fixture_login_failed")
        return browser

    def bind(browser, actor, charge):
        # Private IPC gate derives owned facts from the generated snapshot.
        ref = provider.bind_selection(actor, browser.cookie_header(), charge)
        require(isinstance(ref, str), "selection_gate_contract")
        return ref

    anonymous = Browser(provider.frontend_origin)
    code, _ = anonymous.request("POST", "/api/action/prepare",
                                 {"transaction_reference": "txn_" + "a" * 24})
    require(code in {401, 403}, "anonymous_action_accepted")
    denied_unchanged(initial, snapshot(provider))
    record("anonymous_action_denied")
    es, pt = login("es"), login("pt")
    es_ref, pt_ref = bind(es, "es", "normal"), bind(pt, "pt", "normal")
    before = snapshot(provider)
    code, _ = es.request("POST", "/api/action/prepare",
                         {"transaction_reference": pt_ref, "language": "es"})
    require(code in {403, 404}, "foreign_selection_accepted")
    denied_unchanged(before, snapshot(provider))
    record("foreign_selection_denied")

    for actor, browser, reference in (("es", es, es_ref), ("pt", pt, pt_ref)):
        body = {"transaction_reference": reference, "request_id": str(uuid.uuid4()), "language": actor}
        before = snapshot(provider)
        status, prepared = browser.request("POST", "/api/action/prepare", body)
        require(status == 200 and prepared.get("state") == "pending_confirmation"
                and prepared.get("language") == actor, "pending_confirmation_required")
        unchanged(before, snapshot(provider))
        status, retry = browser.request("GET", "/api/action/status?language=" + actor)
        require(status == 200 and retry.get("pending_handle") == prepared.get("pending_handle"),
                "status_changed_pending_identity")
        unchanged(before, snapshot(provider))
        pending = snapshot(provider)
        status, _ = browser.request("POST", "/api/action/prepare", body)
        require(status == 409, "unresolved_second_prepare_accepted")
        denied_unchanged(pending, snapshot(provider))
        confirmation = {"transaction_reference": reference, "pending_handle": prepared["pending_handle"],
                        "confirmed": False, "language": actor}
        before_denial = snapshot(provider)
        status, _ = browser.request("POST", "/api/action/confirm", confirmation)
        require(status == 422, "false_confirmation_accepted")
        denied_unchanged(before_denial, snapshot(provider))
        confirmation["confirmed"] = True
        status, confirmed = browser.request("POST", "/api/action/confirm", confirmation)
        require(status == 200 and confirmed.get("state") == "intake_verified"
                and confirmed.get("language") == actor, "intake_readback_required")
        receipt = saved_receipt(provider, confirmed)
        after = snapshot(provider)
        require(after["cases"] == before["cases"] + 1
                and after["receipts"] == before["receipts"] + 1, "intake_row_count")
        status, repeated = browser.request("POST", "/api/action/confirm", confirmation)
        require(status == 200 and saved_receipt(provider, repeated) == receipt, "confirm_retry_changed_receipt")
        unchanged(after, snapshot(provider))
        body["request_id"] = str(uuid.uuid4())
        status, existing = browser.request("POST", "/api/action/prepare", body)
        require(status == 200 and existing.get("state") == "existing_case_verified"
                and saved_receipt(provider, existing) == receipt, "existing_case_readback_required")
        unchanged(after, snapshot(provider))
        record(actor + "_consent_receipt_retry_existing_case")

    general = login("pt")
    provider.bind_general("pt", general.cookie_header())
    questions = ["Qual informação falta?"]
    request = {"reason": "customer_request", "request_id": str(uuid.uuid4()),
               "language": "pt", "unanswered_questions": questions}
    before = snapshot(provider)
    status, handed = general.request("POST", "/api/action/handoff", request)
    require(status == 200 and handed.get("state") == "handoff_verified"
            and handed.get("language") == "pt", "general_handoff_readback_required")
    original = saved_handoff(provider, handed, questions=questions, general=True)
    after = snapshot(provider)
    require(after["handoffs"] == before["handoffs"] + 1, "handoff_row_count")
    omitted = {k: v for k, v in request.items() if k != "unanswered_questions"}
    status, retry = general.request("POST", "/api/action/handoff", omitted)
    require(status == 200 and saved_handoff(provider, retry, questions=questions, general=True) == original,
            "handoff_retry_changed_packet")
    unchanged(after, snapshot(provider))
    status, _ = general.request("POST", "/api/action/handoff",
                                 {**request, "unanswered_questions": ["Pergunta diferente?"]})
    require(status == 409, "changed_handoff_questions_accepted")
    unchanged(after, snapshot(provider))
    record("general_handoff_frozen_retry_questions")

    return {"schema": "banking-synthetic-assembly-observations/v1",
            "proof_kind": "deterministic_fixture_provider_api_assembly_safety",
            "scenarios": observations, "final_counts": snapshot(provider)}


def run_confirm_loss(provider) -> dict:
    """Separate fresh attested generation, normal ES charge; no invented fixture row."""
    initial = snapshot(provider)
    require(initial["cases"] == initial["receipts"] == initial["handoffs"] == initial["pending"] == 0,
            "preloaded_action_evidence_forbidden")
    require(initial["fixture_provider_calls"] > 0, "ordinary_runflow_bootstrap_required")
    coverage(provider, complete=True)
    browser = Browser(provider.frontend_origin)
    code, logged = browser.request("POST", "/api/auth/login", provider.credentials("es"))
    require(code == 200 and logged.get("authenticated") is True, "fixture_login_failed")
    reference = provider.bind_selection("es", browser.cookie_header(), "normal")
    status, prepared = browser.request("POST", "/api/action/prepare",
        {"transaction_reference": reference, "request_id": str(uuid.uuid4()), "language": "es"})
    require(status == 200 and prepared.get("state") == "pending_confirmation", "fault_prepare_failed")
    before = snapshot(provider)
    handle = prepared["pending_handle"]
    provider.arm_response_loss("es", browser.cookie_header(), "confirm", handle)
    _, first = browser.request("POST", "/api/action/confirm",
        {"pending_handle": handle, "transaction_reference": reference, "confirmed": True, "language": "es"})
    committed = snapshot(provider)
    require(committed["cases"] == before["cases"] + 1
            and committed["receipts"] == before["receipts"] + 1
            and committed["forwarded_faults"] == before["forwarded_faults"] + 1
            and committed["tool_calls"].get("confirm_simulated_intake", 0)
                == before["tool_calls"].get("confirm_simulated_intake", 0) + 1,
            "fault_must_follow_one_real_confirm_and_receipt")
    status, recovered = browser.request("GET", "/api/action/status?language=es")
    require(status == 200 and recovered.get("state") == "intake_verified", "uncertain_confirmation_readback_failed")
    receipt = saved_receipt(provider, recovered)
    consumed_fault(provider, "es", "confirm", handle, receipt=receipt)
    if first.get("state") == "intake_verified":
        require(saved_receipt(provider, first) == receipt, "automatic_confirm_recovery_changed_receipt")
    unchanged(committed, snapshot(provider))
    require(snapshot(provider)["tool_calls"].get("confirm_simulated_intake", 0)
            == committed["tool_calls"].get("confirm_simulated_intake", 0), "recovery_replayed_confirmation")
    provider.restart_preserving_state()
    status, restarted = browser.request("GET", "/api/action/status?language=es")
    require(status == 200 and restarted.get("state") == "intake_verified"
            and saved_receipt(provider, restarted) == receipt, "restart_lost_verified_receipt")
    unchanged(committed, snapshot(provider))
    require(snapshot(provider)["tool_calls"].get("confirm_simulated_intake", 0)
            == committed["tool_calls"].get("confirm_simulated_intake", 0), "restart_replayed_confirmation")
    status, _ = browser.request("POST", "/api/auth/logout", {})
    require(status == 204, "logout_failed")
    after_logout = snapshot(provider)
    status, _ = browser.request("POST", "/api/action/confirm",
        {"pending_handle": handle, "transaction_reference": reference, "confirmed": True, "language": "es"})
    require(status in {401, 403}, "revoked_session_action_accepted")
    denied_unchanged(after_logout, snapshot(provider))
    return {"schema": "banking-synthetic-assembly-observations/v1",
            "proof_kind": "deterministic_fixture_provider_api_assembly_safety",
            "scenarios": [{"scenario": "lost_confirm_response_read_only_recovery_restart_logout", "status": "passed"}],
            "final_counts": snapshot(provider)}


PREPARE_RECOVERY_FIELDS = {"host_request_id", "action_id", "revision", "conversation_sha256",
    "pending_handle_sha256", "pending_identity_count", "handoff_id", "handoff_packet_sha256",
    "ledger_generation", "target_matches", "completed_upstream", "consumed"}


def prepare_recovery_identity(provider, actor: str, cookie: str) -> dict:
    observed = provider.read_prepare_recovery(actor, cookie)
    import re
    require(set(observed) == PREPARE_RECOVERY_FIELDS
            and all(observed[k] is True for k in ("target_matches", "completed_upstream", "consumed"))
            and type(observed["pending_identity_count"]) is int and observed["pending_identity_count"] == 1
            and type(observed["revision"]) is int and observed["revision"] >= 1
            and all(isinstance(observed[k], str) and re.fullmatch(r"[a-f0-9]{64}", observed[k])
                    for k in ("conversation_sha256", "pending_handle_sha256", "handoff_packet_sha256", "ledger_generation"))
            and all(isinstance(observed[k], str) and re.fullmatch(
                    r"[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}", observed[k])
                    for k in ("host_request_id", "action_id"))
            and isinstance(observed["handoff_id"], str)
            and re.fullmatch(r"HOF-[A-Za-z0-9_-]{8}", observed["handoff_id"]),
            "actual_host_prepare_and_consumed_commit_required")
    return observed


def compare_prepare_recovery(before: dict, after: dict) -> None:
    from consume_package import typed_equal
    require(all(typed_equal(before[k], after[k]) for k in PREPARE_RECOVERY_FIELDS - {"revision"})
            and type(after["revision"]) is int and after["revision"] >= before["revision"],
            "prepare_recovery_changed_saved_identity")


def run_prepare_loss(provider) -> dict:
    """Fresh stock phase. Recover the actual host UUID; never POST another prepare."""
    initial = snapshot(provider)
    require(initial["cases"] == initial["receipts"] == initial["handoffs"] == initial["pending"] == 0,
            "preloaded_action_evidence_forbidden")
    require(initial["fixture_provider_calls"] > 0, "ordinary_runflow_bootstrap_required")
    coverage(provider, complete=False)
    browser = Browser(provider.frontend_origin)
    code, logged = browser.request("POST", "/api/auth/login", provider.credentials("es"))
    require(code == 200 and logged.get("authenticated") is True, "fixture_login_failed")
    reference = provider.bind_selection("es", browser.cookie_header(), "normal")
    cookie = browser.cookie_header()
    before = snapshot(provider)
    provider.arm_response_loss("es", cookie, "prepare", None)
    browser_uuid = str(uuid.uuid4())
    _, first = browser.request("POST", "/api/action/prepare",
        {"transaction_reference": reference, "request_id": browser_uuid, "language": "es"})
    committed = snapshot(provider)
    require(committed["cases"] == committed["receipts"] == 0
            and committed["pending"] == before["pending"] + 1
            and committed["handoffs"] == before["handoffs"] + 1
            and committed["forwarded_faults"] == before["forwarded_faults"] + 1,
            "prepare_fault_must_follow_actual_pending_handoff_commit")
    identity = prepare_recovery_identity(provider, "es", cookie)
    if "request_id" in first:
        require(first["request_id"] == identity["host_request_id"], "prepare_response_host_uuid_mismatch")
    original = provider.read_saved_handoff_by_request("es", identity["host_request_id"])
    require(original["id"] == identity["handoff_id"], "prepare_drop_handoff_identity")
    provider.restart_preserving_state()
    compare_prepare_recovery(identity, prepare_recovery_identity(provider, "es", cookie))
    code, recovered = browser.request("GET", "/api/action/status?language=es")
    require(code == 200 and recovered.get("state") == "handoff_verified"
            and recovered.get("request_id") == identity["host_request_id"]
            and saved_handoff(provider, recovered, questions=[], general=False) == original,
            "lost_prepare_status_recovery_failed")
    compare_prepare_recovery(identity, prepare_recovery_identity(provider, "es", cookie))
    after = snapshot(provider)
    unchanged(committed, after)
    require(after["pending"] == committed["pending"]
            and after["forwarded_faults"] == committed["forwarded_faults"]
            and after["tool_calls"].get("confirm_simulated_intake", 0)
                == committed["tool_calls"].get("confirm_simulated_intake", 0),
            "prepare_recovery_added_pending_drop_or_confirmation")
    return {"schema": "banking-synthetic-assembly-observations/v1",
            "proof_kind": "deterministic_fixture_provider_stock_boundaries",
            "scenarios": [{"scenario": "lost_prepare_host_uuid_status_recovery_restart", "status": "passed"}],
            "final_counts": after}
