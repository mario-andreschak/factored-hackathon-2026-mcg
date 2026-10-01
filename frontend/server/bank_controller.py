"""Banking authority lives in this host; language output is never an input here."""
from __future__ import annotations

import re
from typing import Any, Callable

from .action import handoff_questions, public_facts, verified_handoff, verified_receipt
from .bank_rpc import BankContext, BankRPC, BankRPCError
from .bank_protocol import validate_action_result


_HANDLE = re.compile(r"^[A-Za-z0-9_-]{32,64}$")
_REASONS = frozenset({"high_risk", "missing_evidence", "out_of_policy", "emergency",
    "action_unverified", "customer_request", "clarification_exhausted", "duplicate_review",
    "no_match_exhausted", "tool_failure"})


class BankController:
    def __init__(self, rpc: BankRPC, before_call: Callable[[], None] | None = None):
        self.rpc = rpc
        self.before_call = before_call
        self._workflow_admitted = False

    async def _call(self, tool, args, context, *, timeout_seconds):
        may_write = tool in {"prepare_unrecognized_charge", "confirm_simulated_intake", "create_verified_handoff"}
        try:
            if self.before_call:
                self.before_call()
            result = await self.rpc.call(tool, args, context, timeout_seconds=timeout_seconds)
            if may_write:
                self._workflow_admitted = True
            if self.before_call:
                self.before_call()
            return validate_action_result(tool, result)
        except BankRPCError as exc:
            if self._workflow_admitted and not exc.possibly_sent:
                raise BankRPCError(exc.code, possibly_sent=True) from None
            if may_write and exc.possibly_sent:
                self._workflow_admitted = True
            raise

    async def _receipt(self, handle: str, context: BankContext, timeout: float) -> dict:
        read = await self._call("read_intake_receipt", {"pending_handle": handle},
                                   context, timeout_seconds=timeout)
        receipt = verified_receipt(read.get("receipt"))
        if read.get("state") == "created" and receipt:
            return {"state": "intake_verified", "receipt": receipt}
        return {"state": "action_unverified"}

    async def _handoff(self, payload: dict, context: BankContext, timeout: float,
                       *, expected_facts: dict | None = None,
                       expected_snapshot: str | None = None) -> dict:
        reason = payload.get("reason")
        questions = payload.get("unanswered_questions", [])
        if reason not in _REASONS or handoff_questions(questions) is None:
            raise BankRPCError("invalid_arguments", possibly_sent=False)
        args = {"reason": reason, "unanswered_questions": list(questions)}
        handle = payload.get("pendingHandle")
        if handle:
            args["pending_handle"] = handle
        if payload.get("requestId"):
            args["request_id"] = payload["requestId"]
        try:
            created = await self._call("create_verified_handoff", args, context,
                                          timeout_seconds=timeout)
            # A persisted packet is mandatory at both boundaries. A flattened
            # browser projection alone cannot prove this independent readback.
            original = created.get("handoff")
            first = verified_handoff(original) if isinstance(original, dict) and "packet" in original else None
            if created.get("state") != "created" or first is None:
                return {"state": "handoff_unverified", "reason": reason}
            read = await self._call("read_verified_handoff", {"handoff_id": first["id"]},
                                      context, timeout_seconds=timeout)
            raw = read.get("handoff")
            packet = verified_handoff(raw) if isinstance(raw, dict) and "packet" in raw else None
            if (read.get("state") != "created" or packet is None
                    or {**first, "transaction_currentness": packet["transaction_currentness"]} != packet
                    or original["packet"] != raw["packet"]
                    or packet["reason"] != reason or packet["unanswered_questions"] != questions
                    or bool(handle) != (packet["snapshot"] is not None)
                    or (expected_facts is not None and packet["facts"] != expected_facts)
                    or (expected_snapshot is not None and packet["snapshot"] != expected_snapshot)):
                return {"state": "handoff_unverified", "reason": reason}
            return {"state": "handoff_verified", "handoff": packet}
        except BankRPCError as exc:
            if exc.code in {"authorization_denied", "authorization_required", "reference_unavailable", "action_unverified"} or (
                    exc.code == "server_busy" and not exc.possibly_sent):
                raise
            return {"state": "handoff_unverified", "reason": reason}

    async def execute(self, payload: dict[str, Any], context: BankContext,
                      *, timeout_seconds: float = 45) -> dict:
        self._workflow_admitted = False
        operation = payload.get("operation")
        if operation == "prepare":
            args = {"transaction_id": payload["transactionId"], "snapshot": payload["snapshot"],
                    "request_id": payload["requestId"]}
            prepared = await self._call("prepare_unrecognized_charge", args, context,
                                           timeout_seconds=timeout_seconds)
            facts = public_facts(prepared.get("transaction"))
            handle = prepared.get("pending_handle")
            decision, reason = prepared.get("decision"), prepared.get("reason")
            if (prepared.get("action") != "simulated_intake" or facts is None
                    or prepared.get("snapshot") != payload["snapshot"]
                    or not isinstance(handle, str) or not _HANDLE.fullmatch(handle)
                    or decision not in {"intake", "existing_case", "handoff"}):
                return {"state": "prepare_unverified"}
            # Correlate the owner-resolved portal fields BEFORE any follow-up
            # write. Recovery uses the same saved expected facts, never model facts.
            from .action import matches_selected_transaction
            if not matches_selected_transaction(facts, payload.get("expected_transaction")):
                return {"state": "prepare_unverified"}
            public = {"pending_handle": handle, "snapshot": prepared["snapshot"], "transaction": facts}
            if decision == "existing_case":
                existing = prepared.get("existing_case")
                expected = verified_receipt(existing.get("receipt")) if isinstance(existing, dict) else None
                try:
                    read = await self._receipt(handle, context, timeout_seconds)
                except BankRPCError as exc:
                    if exc.code in {"authorization_denied", "action_unverified"}:
                        raise
                    return {**public, "state": "prepare_unverified"}
                if (not isinstance(existing, dict) or existing.get("state") != "verified"
                        or expected is None or read.get("receipt") != expected
                        or expected["transaction"] != facts):
                    return {**public, "state": "prepare_unverified"}
                return {**public, "state": "existing_case_verified", "receipt": expected}
            if decision == "handoff":
                if reason not in _REASONS:
                    return {"state": "prepare_unverified"}
                outcome = await self._handoff({"reason": reason, "pendingHandle": handle,
                    "requestId": payload["requestId"], "unanswered_questions": []}, context,
                    timeout_seconds, expected_facts=facts, expected_snapshot=prepared["snapshot"])
                return {**public, "reason": reason, **outcome}
            return {**public, "state": "pending_confirmation"}
        if operation == "confirm":
            if payload.get("confirmed") is not True:
                raise BankRPCError("confirmation_required", possibly_sent=False)
            policy_reason = None
            try:
                await self._call("confirm_simulated_intake", {
                    "pending_handle": payload["pendingHandle"], "confirmed": True}, context,
                    timeout_seconds=timeout_seconds)
            except BankRPCError as exc:
                if exc.code in {"authorization_denied", "authorization_required", "reference_unavailable", "server_busy", "action_unverified"}:
                    raise
                if exc.code in {"risk_data_unavailable", "handoff_required", "snapshot_changed"}:
                    policy_reason = "high_risk" if exc.code == "handoff_required" else "missing_evidence"
                # A definitive policy denial can be presented for an explicit
                # host handoff control. Uncertain writes never manufacture HOF.
            try:
                result = await self._receipt(payload["pendingHandle"], context, min(timeout_seconds, 20))
                if result["state"] != "intake_verified" and policy_reason:
                    return {"state": "handoff_unverified", "reason": policy_reason}
                return result
            except BankRPCError as exc:
                if exc.code in {"authorization_denied", "authorization_required", "reference_unavailable", "action_unverified"}:
                    raise
                return {"state": "action_unverified"}
        if operation == "receipt":
            return await self._receipt(payload["pendingHandle"], context, timeout_seconds)
        if operation == "handoff":
            return await self._handoff(payload, context, timeout_seconds,
                expected_facts=payload.get("expected_transaction"),
                expected_snapshot=payload.get("expected_snapshot"))
        raise BankRPCError("invalid_arguments", possibly_sent=False)
