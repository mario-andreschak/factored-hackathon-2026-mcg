"""Executable v3 stage graph over typed LLM outputs and host-owned bank reads.

This runner intentionally has no write port. Portal controls perform writes through
the existing banking host; this graph can only consume independently read receipts.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import time
import uuid

import yaml

from .policy import decide
from .state import TrustedBinding, new_state, begin_turn, apply_decision, parse_timestamp, empty_pending
from .prompts import StageError, safe_structured_data, safe_workflow_state
from .response import validate_response, fallback_response
from .retrieval import retrieve_policy


_ROOT = Path(__file__).resolve().parents[1]
_HUMAN = re.compile(r"\b(?:asesor(?:a)?|agente humano|persona real|humano|humana|atendente|assessor|falar com (?:alguém|uma pessoa)|hablar con (?:alguien|una persona))\b", re.I)
_FOREIGN = re.compile(r"\b(?:otro cliente|otra persona|cuenta de (?:mi|su|un|una)|conta (?:do|da|de) (?:meu|minha|outro|outra)|meu irmão|minha irmã|minha esposa|meu esposo|meu marido|soy (?:el esposo|la esposa) de la titular|otro cliente)\b", re.I)
_PRIVATE = re.compile(r"\b(?:CUST|CLI|CUS|CUSTOMER)-[\w-]+\b|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", re.I)
_PRIVATE_CONTEXT = re.compile(r"\b((?:tel[eé]fono|celular|m[oó]vil|telefone|documento|c[eé]dula|cpf|dni|identificaci[oó]n|tarjeta|cart[aã]o|card)\s*(?:(?:n[uú]mero|n[º°.]?|number)\s*)?[:#]?\s*)\+?\d[\d ()-]{6,}\d", re.I)
_SAFE_FIELDS = {"transaction_id", "transaction_date", "occurred_at", "process_date", "amount", "currency", "merchant_name", "merchant", "transaction_type", "type", "channel", "transaction_city", "city", "transaction_country", "country", "transaction_status", "status", "product_type", "product_last4", "ref", "complaint_id", "id", "created_at", "transaction_reference"}


def sanitize(value):
    """Bound untrusted free text without promoting it into instructions."""
    if isinstance(value, str):
        return _PRIVATE_CONTEXT.sub(lambda match: match[1] + "[DATO_REDACTADO]", _PRIVATE.sub("[DATO_REDACTADO]", value))[:4000]
    if isinstance(value, list):
        return [sanitize(x) for x in value[:20]]
    if isinstance(value, dict):
        return {k: sanitize(v) for k, v in value.items() if k in _SAFE_FIELDS}
    return value


def safe_workflow(state):
    return safe_workflow_state(state["workflow_state"])


class Workflow:
    def __init__(self, adapters, bank, store, *, config=None, tool_timeout=20, clock=None):
        self.adapters, self.bank, self.store = adapters, bank, store
        self.config = config or yaml.safe_load((_ROOT / "config/policy_rules.yaml").read_text(encoding="utf-8"))
        self.tool_timeout = tool_timeout
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    async def _stage(self, state, name, inputs, *, correction=None):
        started = time.monotonic()
        try:
            if correction is None:
                return await self.adapters.run(name, inputs)
            return await self.adapters.run(name, inputs, correction=correction)
        except asyncio.CancelledError:
            raise
        except StageError as exc:
            state["runtime"]["node_errors"].append({"node": name, "code": exc.code})
        except Exception:
            state["runtime"]["node_errors"].append({"node": name, "code": "model_error"})
        finally:
            state["trace"].append({"node": name, "turn_id": state["turn"]["turn_id"], "latency_ms": round((time.monotonic()-started)*1000), "model": getattr(self.adapters, "model_id", None)})
        return None

    async def _read(self, state, name, args, *, optional=False):
        started = time.monotonic()
        result = None
        retries = min(2, max(0, int(self.config.get("tool_retries", 2))))
        for attempt in range(retries + 1):
            try:
                result = await asyncio.wait_for(self.bank.read(name, args), self.tool_timeout)
                if not isinstance(result, dict) or result.get("status") not in {"ok", "error"}:
                    raise ValueError("invalid tool result")
                if result.get("status") != "error":
                    break
                if result.get("code") in {"unsupported_history", "reference_unavailable", "snapshot_changed", "authorization_denied", "target_mismatch", "binding_mismatch", "action_unavailable"}:
                    break
            except asyncio.CancelledError:
                raise
            except Exception:
                result = {"status": "error", "code": "tool_unavailable"}
        if optional and result.get("status") == "error" and result.get("code") == "action_unavailable":
            # Read-only application instances deliberately disable portal
            # actions; absence of that capability is not a failed bank fact.
            result = {"status": "ok", "state": "unavailable", "available": False}
        state["tool_results"][name] = deepcopy(result)
        if result.get("status") == "error":
            state["runtime"]["node_errors"].append({"node": name, "code": result.get("code", "tool_error"), "exhausted": True})
        state["trace"].append({"node": name, "turn_id": state["turn"]["turn_id"], "latency_ms": round((time.monotonic()-started)*1000), "attempts": attempt + 1})
        return result

    def _generator_input(self, state, history):
        t, w, tools = state["turn"], state["workflow_state"], state["tool_results"]
        search = tools.get("search_transactions", {})
        facts = {"status": search.get("status", "not_queried"), "match_count": search.get("match_count", 0), "candidates": search.get("candidates", []) if search.get("status") == "ok" else [], "data_sources": [], "search_context": search.get("search_context", {})}
        target_read = tools.get("get_transaction", {})
        target = target_read.get("transaction") if target_read.get("status") == "ok" and w.get("transaction_identified") else None
        if target is not None:
            facts["transaction"] = target
            facts["data_sources"].append("transactions")
        elif facts["candidates"]:
            facts["data_sources"].append("transactions")
        complaint_read = tools.get("list_customer_complaints", {})
        complaints = complaint_read.get("complaints", []) if complaint_read.get("status") == "ok" else []
        if t.get("intent") == "COMPLAINT_STATUS":
            facts.update(status=complaint_read.get("status", "not_queried"), match_count=complaint_read.get("match_count", 0))
        if complaints:
            facts["complaints"] = complaints
            facts["data_sources"].append("complaints")
        if w.get("action", {}).get("verified"):
            facts["data_sources"].append("sandbox_case_receipt")
        if w.get("handoff", {}).get("created"):
            facts["data_sources"].append("sandbox_handoff_receipt")
        mode = w["policy_decision"]["response_mode"]
        projection = safe_workflow(state)
        if mode in {"AUTH_REQUIRED", "BLOCKED", "SMALL_TALK", "OUT_OF_SCOPE"}:
            # A prior conversation can never supply facts to a restricted mode.
            facts = {"status": "not_queried", "match_count": 0, "data_sources": []}
            projection = safe_workflow_state({})
            projection["policy_decision"] = {"response_mode": mode}
            history = ""
        return {"response_mode": mode, "language": t["language"], "emotional_context": t["emotional_context"], "clean_query": t["clean_query"], "structured_data": safe_structured_data(facts), "policy_context": state.get("policy_context", []), "workflow_state": projection, "historic_conversation": history, "customer_first_name": "", "current_date": t["current_date"]}

    @staticmethod
    def _invalidate_target(state, code):
        w = state["workflow_state"]
        w.update(transaction_identified=False, transaction_unique=False, transaction_id=None, candidate_snapshot_hash=None)
        w["pending"] = empty_pending()
        state["runtime"]["pending_created_at"] = None
        state["runtime"]["pending_expires_at"] = None
        state["runtime"]["node_errors"].append({"node": "get_transaction", "code": code})

    @staticmethod
    def _selection_matches(selection, row):
        try:
            return (Decimal(str(selection["amount"])) == Decimal(str(row["amount"]))
                    and selection["currency"] == row["currency"]
                    and selection["status"] == row.get("transaction_status", row.get("status"))
                    and selection["type"] == row.get("transaction_type", row.get("type"))
                    and datetime.fromisoformat(selection["occurred_at"].replace("Z", "+00:00")) == datetime.fromisoformat(row["transaction_date"].replace("Z", "+00:00")))
        except (KeyError, TypeError, ValueError, InvalidOperation, AttributeError):
            return False

    async def _facts(self, state, selection):
        t, w = state["turn"], state["workflow_state"]
        if t["intent"] == "COMPLAINT_STATUS":
            cid = t["slots"].get("complaint_id")
            if cid:
                pending = w.get("pending", {})
                result = await self._read(state, "get_complaint", {"complaint_id": cid,
                    "snapshot_id": pending.get("snapshot_id"), "snapshot_hash": pending.get("snapshot_hash")})
                if result.get("status") == "ok":
                    if result.get("complaint") is not None and not isinstance(result["complaint"], dict):
                        state["runtime"]["node_errors"].append({"node": "get_complaint", "code": "invalid_complaint_result"})
                        return
                    if result.get("complaint") and result["complaint"].get("complaint_id") != cid:
                        state["runtime"]["node_errors"].append({"node": "get_complaint", "code": "target_mismatch"})
                        return
                    state["tool_results"]["list_customer_complaints"] = {"status": "ok", "complaints": [result["complaint"]] if result.get("complaint") else [], "match_count": 1 if result.get("complaint") else 0, "coverage_complete": result.get("coverage_complete", False)}
            else:
                result = await self._read(state, "list_customer_complaints", {})
                if result.get("status") == "ok":
                    w["candidate_snapshot_hash"] = result.get("snapshot_hash") or result.get("snapshot_id")
            return
        if t["intent"] not in {"TRANSACTION_DISPUTE", "TRANSACTION_INQUIRY"}:
            return
        slots = t["slots"]
        w["search_criteria_present"] = bool(selection or w.get("transaction_id") or any(slots.get(k) is not None for k in ("amount", "date_from", "date_to", "transaction_id", "merchant")))
        if slots.get("currency_raw") and not slots.get("currency"):
            w["search_criteria_present"] = False
            w["missing_fields"] = ["currency"]
            return
        if not w["search_criteria_present"]:
            return
        pending = w.get("pending", {})
        selected_pending = t.get("clarification", {}).get("resolution_type") == "SELECTED"
        if selected_pending and pending.get("type") == "awaiting_selection":
            # Preserve the displayed count; selection rereads its target rather
            # than replacing the original candidate evidence with a new search.
            search = {"status": "ok", "match_count": len(pending.get("candidates", [])),
                      "candidates": deepcopy(pending.get("candidates", [])),
                      "snapshot_hash": pending.get("snapshot_hash"),
                      "search_context": {"coverage_complete": True, "snapshot_id": pending.get("snapshot_id")}}
            state["tool_results"]["search_transactions"] = deepcopy(search)
        else:
            search = await self._read(state, "search_transactions", {"slots": deepcopy(slots)})
        if search.get("status") != "ok":
            return
        candidates = search.get("candidates", [])
        if not isinstance(candidates, list) or any(not isinstance(c, dict) for c in candidates) or type(search.get("match_count")) is not int or search["match_count"] < len(candidates):
            state["runtime"]["node_errors"].append({"node": "search_transactions", "code": "invalid_search_result"})
            return
        if pending.get("type") != "awaiting_confirmation" and not selected_pending:
            w["candidate_snapshot_hash"] = search.get("snapshot_hash") or search.get("search_context", {}).get("snapshot_id")
        chosen = selection.get("reference") if selection else slots.get("transaction_id") or w.get("transaction_id")
        if selection and pending.get("type") == "awaiting_selection" and chosen not in {c.get("transaction_id") for c in pending.get("candidates", [])}:
            self._invalidate_target(state, "selection_not_displayed")
            return
        if chosen == w.get("transaction_id") and not selected_pending and not selection and not slots.get("transaction_id") and chosen not in {c.get("transaction_id") for c in candidates}:
            chosen = None
        if not chosen and len(candidates) == 1 and search.get("search_context", {}).get("coverage_complete"):
            chosen = candidates[0].get("transaction_id")
        if chosen:
            expected_snapshot = pending.get("snapshot_id") if selected_pending or pending.get("type") == "awaiting_confirmation" else search.get("search_context", {}).get("snapshot_id")
            target = await self._read(state, "get_transaction", {"transaction_id": chosen, "snapshot_hash": w.get("candidate_snapshot_hash"), "snapshot_id": expected_snapshot})
            if target.get("status") == "error" and target.get("code") in {"snapshot_changed", "target_mismatch", "reference_unavailable", "authorization_denied"}:
                self._invalidate_target(state, target["code"])
                return
            if target.get("status") == "ok" and not isinstance(target.get("transaction"), dict):
                self._invalidate_target(state, "invalid_target_result")
                return
            if target.get("status") == "ok" and target.get("transaction"):
                row = target["transaction"]
                current_snapshot = target.get("snapshot_id") or target.get("snapshot") or target.get("snapshot_hash")
                if row.get("transaction_id") != chosen or not current_snapshot or row.get("customer_id") not in (None, state["session"]["customer_id"]):
                    self._invalidate_target(state, "target_mismatch")
                    return
                if expected_snapshot and current_snapshot != expected_snapshot or selection and not self._selection_matches(selection, row):
                    self._invalidate_target(state, "snapshot_changed")
                    return
                w.update(transaction_identified=True, transaction_unique=True, transaction_id=chosen)
                w["candidate_snapshot_hash"] = w.get("candidate_snapshot_hash") or search.get("snapshot_hash") or current_snapshot
                target["snapshot_id"] = current_snapshot
                if "status" not in row and "transaction_status" in row:
                    row["status"] = row["transaction_status"]
                # _read retains a copy; publish only the checked canonical aliases.
                state["tool_results"]["get_transaction"] = deepcopy(target)
                if t["intent"] == "TRANSACTION_DISPUTE":
                    related = await self._read(state, "get_related_complaints", {"transaction_id": chosen})
                    report = related.get("report_window", {})
                    if not isinstance(report, dict):
                        state["runtime"]["node_errors"].append({"node": "get_related_complaints", "code": "invalid_report_result"})
                        return
                    count = report.get("prior_distinct_verified_count")
                    timestamp = parse_timestamp(t["current_timestamp"])
                    complete = (report.get("coverage_complete") is True and report.get("scope") == "prototype_sandbox_cases"
                        and parse_timestamp(report.get("window_end")) == timestamp
                        and parse_timestamp(report.get("window_start")) == timestamp - timedelta(hours=24))
                    w["unrecognized_count_24h"] = count + 1 if type(count) is int and count >= 0 and complete else None
                    w["risk_data_complete"] = target.get("risk_data_complete") is True and complete

    @staticmethod
    def _receipt_matches_target(receipt, row):
        facts = receipt["transaction"]
        try:
            if (Decimal(str(facts["amount"])) != Decimal(str(row["amount"]))
                    or facts["currency"] != row["currency"]
                    or datetime.fromisoformat(facts["transaction_date"].replace("Z", "+00:00")) != datetime.fromisoformat(row["transaction_date"].replace("Z", "+00:00"))
                    or facts["status"] != row.get("transaction_status", row.get("status"))):
                return False
            for fact, aliases in (("process_date", ("process_date",)), ("merchant", ("merchant_name", "merchant")),
                                  ("transaction_type", ("transaction_type", "type")), ("channel", ("channel",)), ("product", ("product",))):
                key = next((key for key in aliases if key in row), None)
                if key and facts[fact] != row[key]:
                    return False
            return True
        except (TypeError, KeyError, ValueError, InvalidOperation, AttributeError):
            return False

    def _host_evidence(self, state, status, binding):
        """Consume readback only after the exact host binding is independently proved."""
        w = state["workflow_state"]
        from frontend.server.action import verified_receipt, verified_handoff
        proof = status.get("binding", {})
        if (status.get("binding_verified") is not True or not isinstance(proof, dict)
                or any(proof.get(key) != getattr(binding, key) for key in ("owner", "customer_id", "session_id", "conversation_id"))
                or parse_timestamp(proof.get("expires_at")) != parse_timestamp(binding.expires_at)):
            state["runtime"]["unaccepted_host_status"] = "binding_mismatch"
            return
        pending = w.get("pending", {})
        target = w.get("transaction_id")
        snapshot = state["tool_results"].get("get_transaction", {}).get("snapshot_id")
        native_receipt = verified_receipt(status.get("receipt"))
        raw_handoff = status.get("handoff", {})
        if isinstance(raw_handoff, dict) and raw_handoff.get("state") == "handoff_verified":
            raw_handoff = raw_handoff.get("handoff", {})
        native_handoff = verified_handoff(raw_handoff)
        status_snapshot = status.get("snapshot") or (native_receipt or {}).get("snapshot") or (native_handoff or {}).get("snapshot")
        matches_target = bool(w.get("transaction_identified") and target and snapshot and status.get("target_reference") == target and status_snapshot == snapshot)
        matches_request = all(not pending.get(key) or status.get(status_key) == pending[key]
                              for key, status_key in (("request_id", "request_id"), ("host_pending_handle", "pending_handle")))
        if status.get("state") == "pending_confirmation" and matches_target and matches_request:
            for key, status_key in (("request_id", "request_id"), ("host_pending_handle", "pending_handle")):
                if status.get(status_key):
                    pending[key] = status[status_key]
            pending["snapshot_id"] = snapshot
            return
        if status.get("state") == "intake_verified":
            canonical = status.get("action", {})
            canonical_receipt = canonical.get("receipt", {}) if isinstance(canonical, dict) else {}
            canonical_valid = (isinstance(canonical_receipt, dict) and canonical.get("name") == "CREATE_COMPLAINT"
                and canonical.get("authorized") is True and canonical.get("executed") is True and canonical.get("verified") is True
                and isinstance(canonical.get("result_id"), str) and re.fullmatch(r"CMP-SBX-[A-Za-z0-9_-]{8}", canonical["result_id"])
                and canonical_receipt.get("verified") is True and canonical_receipt.get("result_id") == canonical["result_id"])
            row = state["tool_results"].get("get_transaction", {}).get("transaction", {})
            native_valid = bool(native_receipt and native_receipt["snapshot"] == snapshot and self._receipt_matches_target(native_receipt, row))
            if matches_target and matches_request and (native_valid or canonical_valid):
                rid = native_receipt["id"] if native_receipt else canonical["result_id"]
                w["action"] = {"name": "CREATE_COMPLAINT", "authorized": True, "executed": True, "verified": True, "result_id": rid, "receipt": {"verified": True, "result_id": rid}}
                w["action_attempted"], w["action_outcome"] = True, "verified"
        elif status.get("state") == "action_unverified":
            if matches_request:
                # A trusted conversation-bound uncertain outcome must be
                # recovered even if its target is unavailable. It supplies no
                # success facts and never authorizes a different action.
                w["action"].update(executed=False, verified=False)
                w["action_attempted"], w["action_outcome"] = True, "unknown"
        handoff = native_handoff
        general = handoff and handoff.get("facts") == {} and handoff.get("snapshot") is None
        if status.get("state") in {"handoff_verified", "action_unverified"} and handoff and matches_request and (general and not target or matches_target and handoff["snapshot"] == snapshot):
            w["handoff"].update(created=True, handoff_id=handoff["id"], receipt={"verified": True, "handoff_id": handoff["id"]})
        elif status.get("state") in {"handoff_verified", "action_unverified"} and matches_target and matches_request:
            handoff = status.get("handoff", {})
            receipt = handoff.get("receipt", {}) if isinstance(handoff, dict) else {}
            if (isinstance(receipt, dict) and handoff.get("created") is True and isinstance(handoff.get("handoff_id"), str)
                    and re.fullmatch(r"HOF-[A-Za-z0-9_-]{8}", handoff["handoff_id"])
                    and receipt.get("verified") is True and receipt.get("handoff_id") == handoff["handoff_id"]):
                w["handoff"].update(created=True, handoff_id=handoff["handoff_id"], receipt={"verified": True, "handoff_id": handoff["handoff_id"]})

    def _retrieve(self, state, *, human_required=False):
        started = time.monotonic()
        try:
            chunks = retrieve_policy(state["turn"].get("intent"), human_required=human_required, max_chars=7000)
            state["tool_results"]["retrieve_policy"] = {"status": "ok", "chunks": chunks}
            state["policy_context"] = chunks
        except (OSError, ValueError, TypeError):
            state["tool_results"]["retrieve_policy"] = {"status": "error", "chunks": [], "code": "policy_unavailable"}
            state["policy_context"] = []
            state["runtime"]["node_errors"].append({"node": "retrieve_policy", "code": "policy_unavailable"})
        state["trace"].append({"node": "retrieve_policy", "turn_id": state["turn"]["turn_id"],
            "latency_ms": round((time.monotonic() - started) * 1000), "source": "reviewed_local_chunks"})

    @staticmethod
    def _resume_fields(state, slots, context):
        """Resume only from typed current fields that answer the prior question."""
        if not isinstance(context, dict) or context.get("intent") not in {"TRANSACTION_DISPUTE", "TRANSACTION_INQUIRY", "COMPLAINT_STATUS"}:
            return slots
        missing = context.get("missing_fields", [])
        fields = {"date_from", "date_to"} if "date" in missing else set()
        fields.update(field for field in missing if field in slots)
        answered = any(slots.get(field) is not None for field in fields)
        if state["turn"]["intent"] == "OOD":
            # An out-of-scope sentence can mention the requested value while
            # asking something else. Only a standalone extracted value or an
            # explicit field statement may override that current intent. This
            # gate never determines the value; the canonical slot model does.
            expressions = {str(slots[field]).strip() for field in fields if slots.get(field) is not None}
            labels = []
            if "currency" in fields:
                if slots.get("currency_raw"):
                    expressions.add(slots["currency_raw"].strip())
                labels.extend((r"(?:la\s+)?moneda", r"(?:a\s+)?moeda"))
            if fields & {"date_from", "date_to"}:
                if slots.get("date_expression"):
                    expressions.add(slots["date_expression"].strip())
                labels.extend((r"(?:la\s+)?fecha", r"(?:a\s+)?data"))
            if "amount" in fields:
                labels.extend((r"(?:el\s+)?(?:monto|importe|valor)", r"(?:o\s+)?valor"))
            prefix = r"(?:(?:es|[ée]|son|são)\s+)?"
            if labels:
                prefix = r"(?:(?:" + "|".join(labels) + r")\s*(?:(?:es|[ée])\s+|:\s*)?|(?:es|[ée]|son|são)\s+)?"
            original = state["turn"]["user_question"].strip()
            field_only = any(expression and re.fullmatch(prefix + re.escape(expression) + r"\s*[.]?", original, re.I) for expression in expressions)
            answered = answered and field_only
        prior = context.get("slots", {})
        changed_criteria = any(slots.get(field) is not None and prior.get(field) is not None and slots[field] != prior[field]
                               for field in ("amount", "date_from", "date_to", "merchant", "transaction_id", "complaint_id") if field not in fields)
        compatible = state["turn"]["intent"] in {"OOD", context["intent"]}
        if answered and compatible and not changed_criteria and not context.get("new_request"):
            merged = deepcopy(prior)
            for field, value in slots.items():
                if value is not None and field not in {"amount_is_approximate", "foreign_customer_reference"}:
                    merged[field] = value
            if slots.get("amount") is not None:
                merged["amount_is_approximate"] = slots.get("amount_is_approximate", False)
            merged["foreign_customer_reference"] = slots.get("foreign_customer_reference", False)
            state["turn"]["intent"] = context["intent"]
            state["runtime"]["field_clarification_resumed"] = True
            state["runtime"].pop("field_clarification", None)
            return merged
        # A distinct classified request gets no criteria or business domain from
        # the earlier question, including an unrelated out-of-scope request.
        state["runtime"].pop("field_clarification", None)
        state["runtime"].pop("workflow_intent", None)
        state["workflow_state"].update(missing_fields=[], transaction_id=None,
            transaction_identified=False, transaction_unique=False, search_criteria_present=False)
        return slots

    async def _refresh_replay(self, state, binding):
        """Cached success needs current readback; never replay a model or write."""
        w = state["workflow_state"]
        mode = w.get("policy_decision", {}).get("response_mode")
        success = mode == "ACTION_DONE"
        handoff_success = w.get("handoff", {}).get("created") is True
        if not success and not handoff_success:
            return state
        original_id = w.get("action", {}).get("result_id")
        original_handoff = w.get("handoff", {}).get("handoff_id")
        old_status = state["tool_results"].get("host_action_status", {})
        old_target = state["tool_results"].get("get_transaction", {})
        expected_snapshot = old_target.get("snapshot_id") or old_target.get("snapshot") or old_target.get("snapshot_hash")
        w["action"].update(authorized=False, verified=False)
        w["handoff"].update(created=False)
        target_ok = not w.get("transaction_id")
        if w.get("transaction_id") and expected_snapshot:
            target = await self._read(state, "get_transaction", {"transaction_id": w["transaction_id"],
                "snapshot_id": expected_snapshot, "snapshot_hash": w.get("candidate_snapshot_hash")})
            current_snapshot = target.get("snapshot_id") or target.get("snapshot") or target.get("snapshot_hash")
            row = target.get("transaction", {})
            target_ok = (target.get("status") == "ok" and isinstance(row, dict)
                         and row.get("transaction_id") == w["transaction_id"] and current_snapshot == expected_snapshot
                         and row.get("customer_id") in (None, state["session"]["customer_id"]))
            w.update(transaction_identified=target_ok, transaction_unique=target_ok)
            if target_ok:
                target["snapshot_id"] = current_snapshot
                state["tool_results"]["get_transaction"] = deepcopy(target)
        if target_ok:
            status = await self._read(state, "host_action_status", {"expected_request_id": old_status.get("request_id"),
                "pending_handle": old_status.get("pending_handle")}, optional=True)
            self._host_evidence(state, status, binding)
        action_ok = w.get("action", {}).get("verified") is True and w["action"].get("result_id") == original_id
        handoff_ok = w.get("handoff", {}).get("created") is True and w["handoff"].get("handoff_id") == original_handoff
        finished = self.clock()
        if binding.expired(finished):
            refreshed = begin_turn(new_state(binding, now=finished), binding,
                turn_id=state["turn"]["turn_id"], user_question=state["turn"]["user_question"], now=finished)
            refreshed = apply_decision(refreshed, decide(refreshed, self.config))
            refreshed["response"] = fallback_response(self._generator_input(refreshed, ""))
            refreshed["runtime"]["safe_fallback_used"] = True
            return refreshed
        if success and action_ok and (not handoff_success or handoff_ok) or not success and handoff_success and handoff_ok:
            state["runtime"]["replay_receipt_reverified"] = True
            return state
        w["action"]["authorized"] = False
        w["action"]["verified"] = False
        w["handoff"].update(required=True, created=False, reason_code="action_unverified" if success else "missing_evidence")
        w["policy_decision"].update(response_mode="ACTION_UNVERIFIED" if success else mode,
            requires_confirmation=False, requires_human=True, reason_code="action_unverified" if success else "missing_evidence")
        w["action_attempted"], w["action_outcome"] = success or w.get("action_attempted", False), "unknown" if success else w.get("action_outcome", "none")
        state["response"] = fallback_response(self._generator_input(state, ""))
        state["runtime"].update(safe_fallback_used=True, replay_receipt_reverified=False)
        return state

    async def run(self, binding, message, *, turn_id=None, selection=None):
        binding = TrustedBinding(**binding) if isinstance(binding, dict) else binding
        turn_id = turn_id or str(uuid.uuid4())
        if not isinstance(message, str) or not message.strip() or len(message) > 4096:
            raise ValueError("invalid message")
        now = self.clock()
        if hasattr(self.bank, "bind_context"):
            # This call is server-only. Its identity never comes from message or LLM JSON.
            self.bank.bind_context({key: getattr(binding, key) for key in ("owner", "customer_id", "session_id", "conversation_id", "expires_at")})
        digest = hashlib.sha256(json.dumps({"message": message, "selection": selection}, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        if hasattr(self.store, "load_turn"):
            replay = self.store.load_turn(binding, turn_id, now=now)
            if replay:
                if replay["runtime"].get("input_sha256") != digest:
                    raise ValueError("turn replay mismatch")
                return await self._refresh_replay(replay, binding)
        live = binding.authenticated and not binding.expired(now)
        previous = (self.store.load(binding, now=now) if live else None) or new_state(binding, now=now)
        revision = previous.get("runtime", {}).get("store_revision", 0)
        history_items = previous.get("runtime", {}).get("history", [])[-6:]
        history = "\n".join(history_items)
        state = begin_turn(previous, binding, turn_id=turn_id, user_question=sanitize(message), now=now)
        state["runtime"]["input_sha256"] = digest
        t, w = state["turn"], state["workflow_state"]
        t["human_requested"] = bool(_HUMAN.search(message))
        t["unauthorized_reference"] = bool(_FOREIGN.search(message))
        if state["session"]["authenticated"] and not state["session"]["expired"]:
            inputs = {"user_question": t["user_question"], "historic_conversation": history}
            rewrite, attack, context = await asyncio.gather(self._stage(state, "rewrite_decompose", inputs), self._stage(state, "detect_attack", {"user_question": t["user_question"]}), self._stage(state, "detect_context", inputs))
            # asyncio.gather is the real same-turn barrier before any dependent stage.
            state["trace"].append({"node": "merge_parallel", "turn_id": turn_id, "branches": ["rewrite_decompose", "detect_attack", "detect_context"]})
            if rewrite:
                t.update(rewrite)
            if attack:
                t["attack"] = attack
            if context:
                t.update(context)
                t["effective_language"] = "pt" if context["language"] == "pt" else "es"
            guarded = t["attack"].get("deceptive") or t["attack"].get("inappropriate") or t["unauthorized_reference"] or state["runtime"]["node_errors"]
            if not guarded:
                pending = w.get("pending", {})
                if pending.get("type") != "none":
                    clarification = await self._stage(state, "resolve_clarification", {"clean_query": t["clean_query"], "pending": safe_workflow(state)["pending"], "historic_conversation": history})
                    if clarification:
                        t["clarification"] = clarification
                        resolution = clarification["resolution_type"]
                        if resolution == "NEW_REQUEST":
                            if w.get("action_outcome") in {"unknown", "executed"}:
                                state["runtime"]["node_errors"].append({"node": "resolve_clarification", "code": "action_recovery_required"})
                            else:
                                state["workflow_state"] = w = new_state(binding, now=now)["workflow_state"]
                        elif resolution == "SELECTED":
                            candidate = next((c for c in pending.get("candidates", []) if c.get("ref") == clarification["selected_ref"]), None)
                            if candidate:
                                field = "complaint_id" if pending.get("candidate_type") == "complaint" else "transaction_id"
                                w[field] = candidate.get(field)
                                t["intent"] = pending.get("intent") or ("COMPLAINT_STATUS" if field == "complaint_id" else "TRANSACTION_DISPUTE")
                                t["slots"][field] = candidate.get(field)
                            else:
                                t["clarification"] = {"resolution_type": "UNCLEAR", "selected_ref": None}
                        else:
                            t["intent"] = pending.get("intent") or "TRANSACTION_DISPUTE"
                if w.get("pending", {}).get("type") == "none":
                    queries = [query["query_text"] for query in t.get("sub_queries", [])] or [t["clean_query"]]
                    intents = await self._stage(state, "detect_intent", {"queries": queries})
                    if intents:
                        t["intents"] = intents["intents"]
                        # Multiple business queries need independent target scopes. This
                        # slice asks for one rather than accidentally reusing a target.
                        if len(t["intents"]) == 1:
                            t["intent"] = t["intents"][0]["domain"]
                        elif len(t["intents"]) > 1:
                            state["runtime"]["node_errors"].append({"node": "detect_intent", "code": "multiple_queries_need_separate_turns"})
                business = t["intent"] in {"TRANSACTION_DISPUTE", "TRANSACTION_INQUIRY", "COMPLAINT_STATUS"}
                field_context = state["runtime"].get("field_clarification") if w.get("pending", {}).get("type") == "none" else None
                if (business or field_context or t["human_requested"] or t["emotional_context"] == "Emergencia") and not state["runtime"]["node_errors"]:
                    # R2 must be known before even a currency/profile read. The
                    # first extraction has no customer data; ambiguity stays null.
                    slots = await self._stage(state, "extract_slots", {"clean_query": t["user_question"] if field_context else t["clean_query"], "current_date": t["current_date"], "customer_currencies": []})
                    if slots:
                        if field_context:
                            # A currency in an unrelated question is not a field
                            # answer. Reuse the canonical clarification model to
                            # distinguish the current answer from a topic change.
                            if not t["human_requested"] and t["emotional_context"] != "Emergencia" and not slots.get("foreign_customer_reference"):
                                resolution = await self._stage(state, "resolve_clarification", {
                                    "clean_query": t["user_question"], "pending": {"type": "none", "candidates": []},
                                    "historic_conversation": history}, correction=(
                                    "Hay una pregunta de campos pendiente del host: " + ", ".join(field_context.get("missing_fields", [])) +
                                    ". Usa UNCLEAR para una respuesta a esos campos y NEW_REQUEST para una pregunta independiente o un cambio de tema. No uses SELECTED ni CONFIRMED; no hay selección ni consentimiento pendientes."))
                                if resolution and resolution["resolution_type"] in {"NEW_REQUEST", "DENIED"}:
                                    field_context = {**field_context, "new_request": True}
                            slots = self._resume_fields(state, slots, field_context)
                            business = t["intent"] in {"TRANSACTION_DISPUTE", "TRANSACTION_INQUIRY", "COMPLAINT_STATUS"}
                        retained = deepcopy(t.get("slots", {}))
                        t["slots"].update(slots)
                        if t.get("clarification", {}).get("resolution_type") == "SELECTED":
                            # A validated displayed reference outranks extraction.
                            for field in ("transaction_id", "complaint_id"):
                                if retained.get(field):
                                    t["slots"][field] = retained[field]
                    assisted = t["human_requested"] or t["intent"] == "HUMAN_REQUEST" or t["emotional_context"] == "Emergencia"
                    stopped = t.get("clarification", {}).get("resolution_type") in {"DENIED", "UNCLEAR"} and w.get("pending", {}).get("type") != "none"
                    if business and not assisted and not stopped and not t["slots"].get("foreign_customer_reference") and not state["runtime"]["node_errors"]:
                        if t["slots"].get("currency_raw") and not t["slots"].get("currency"):
                            profile = await self._read(state, "get_customer_profile", {})
                            currencies = profile.get("currencies", [])
                            if not currencies:
                                currencies = sorted({p.get("currency") for p in profile.get("products", []) if p.get("currency")})
                            if not state["runtime"]["node_errors"]:
                                slots = await self._stage(state, "extract_slots", {"clean_query": t["clean_query"], "current_date": t["current_date"], "customer_currencies": currencies})
                                if slots:
                                    for field, value in slots.items():
                                        if field not in {"transaction_id", "complaint_id"} or t.get("clarification", {}).get("resolution_type") != "SELECTED":
                                            t["slots"][field] = value
                        if not t["slots"].get("foreign_customer_reference") and not state["runtime"]["node_errors"]:
                            await self._facts(state, selection)
                assisted = t["human_requested"] or t["intent"] == "HUMAN_REQUEST" or t["emotional_context"] == "Emergencia"
                stopped = t.get("clarification", {}).get("resolution_type") in {"DENIED", "UNCLEAR"} and w.get("pending", {}).get("type") != "none"
                needs_status = business or w.get("pending", {}).get("type") == "awaiting_confirmation" or w.get("action_attempted")
                if needs_status and not assisted and not stopped and not state["runtime"]["node_errors"] and not t["slots"].get("foreign_customer_reference"):
                    status = await self._read(state, "host_action_status", {"expected_request_id": w.get("pending", {}).get("request_id"), "pending_handle": w.get("pending", {}).get("host_pending_handle")}, optional=True)
                    self._host_evidence(state, status, binding)
        state["policy_context"] = []
        if (state["session"]["authenticated"] and not state["session"]["expired"]
                and not t["attack"].get("deceptive") and not t["attack"].get("inappropriate")
                and not t["unauthorized_reference"] and not t["slots"].get("foreign_customer_reference")
                and not state["runtime"]["node_errors"]):
            self._retrieve(state, human_required=t["human_requested"] or t["emotional_context"] == "Emergencia")
        linked_pending = deepcopy(state["workflow_state"].get("pending", {}))
        # Classification may take tens of seconds. Eligibility, session expiry
        # and bounded risk freshness use the current trusted server clock at
        # the policy boundary, never the time captured before those calls.
        decision_now = self.clock()
        clock_turn = new_state(binding, now=decision_now)["turn"]
        t["current_date"], t["current_timestamp"] = clock_turn["current_date"], clock_turn["current_timestamp"]
        state["session"] = binding.session(decision_now)
        decision = decide(state, self.config)
        state = apply_decision(state, decision)
        t, w = state["turn"], state["workflow_state"]
        if w.get("pending", {}).get("candidate_type") == "complaint" and w["pending"].get("type") == "awaiting_selection":
            w["pending"]["snapshot_id"] = state["tool_results"].get("list_customer_complaints", {}).get("snapshot_id")
        if (w.get("pending", {}).get("type") == "awaiting_confirmation"
                and linked_pending.get("target_transaction_id") == w.get("transaction_id")
                and linked_pending.get("snapshot_id") == state["tool_results"].get("get_transaction", {}).get("snapshot_id")):
            # Policy may renew the conversational pending projection; preserve
            # only an already-bound host request, never model confirmation.
            for field in ("request_id", "host_pending_handle", "snapshot_id"):
                if linked_pending.get(field):
                    w["pending"][field] = linked_pending[field]
        if w.get("handoff", {}).get("required"):
            if not any(chunk.get("chunk_id", "").startswith("handoff") for chunk in state["policy_context"]):
                self._retrieve(state, human_required=True)
            packet_input = self._generator_input(state, history)
            narrative_input = {k: packet_input[k] for k in ("clean_query", "historic_conversation", "structured_data", "workflow_state", "language")}
            narrative_input["language"] = t["effective_language"]
            narrative = await self._stage(state, "generate_handoff_summary", narrative_input)
            state["runtime"]["handoff_narrative"] = narrative
            # Narrative is auxiliary: it never replaces the host's factual packet
            # and does not establish handoff.created.
        generator_input = self._generator_input(state, history)
        response = None
        correction = None
        for attempt in range(min(1, max(0, int(self.config.get("max_response_retries", 1)))) + 1):
            before = len(state["runtime"]["node_errors"])
            candidate = await self._stage(state, "generate", generator_input, correction=correction)
            errors = validate_response(candidate, generator_input) if candidate else ["generation_failed"]
            t["validation_errors"] = errors
            t["validation_attempts"] = attempt
            if not errors:
                response = candidate
                break
            stage_errors = state["runtime"]["node_errors"][before:]
            if candidate is None and any(error.get("code") not in {"invalid_json", "schema"} for error in stage_errors):
                break
            # A bounded system correction contains diagnostic codes, never the
            # invalid candidate, raw state, capabilities, or customer records.
            correction = "Corrige la respuesta anterior. Devuelve solo el JSON del contrato y hechos autorizados; errores del host: " + ", ".join(error.get("code", "schema") for error in stage_errors) + ("; " if stage_errors else "") + ", ".join(errors)
        if response is None:
            response = fallback_response(generator_input)
            state["runtime"]["safe_fallback_used"] = True
        state["response"] = response
        state["runtime"]["history"] = (history_items + [f"user: {t['user_question']}", f"assistant: {sanitize(response['message'])}", f"language: {t['effective_language']}"])[-9:]
        finished = self.clock()
        if not live or binding.expired(finished):
            # The store rejects expired sessions. Return an ungrounded auth
            # message and retain neither private replay nor historical state.
            state = begin_turn(new_state(binding, now=finished), binding, turn_id=turn_id, user_question=sanitize(message), now=finished)
            state = apply_decision(state, decide(state, self.config))
            state["response"] = fallback_response(self._generator_input(state, ""))
            state["runtime"]["safe_fallback_used"] = True
            return state
        if hasattr(self.store, "save_turn"):
            new_revision = self.store.save_turn(binding, turn_id, state, expected_revision=revision, now=finished)
        else:
            new_revision = self.store.save(binding, state, expected_revision=revision, now=finished)
        state["runtime"]["store_revision"] = new_revision
        return state
