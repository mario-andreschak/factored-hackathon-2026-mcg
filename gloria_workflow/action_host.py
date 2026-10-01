"""Trusted application action bridge to the existing banking sandbox ledger.

Only the frontend's explicit controls invoke this object. It is never exposed
as a language tool. Identity comes from verified frontend admission; Actions
still owns eligibility, atomic intake, idempotency and durable receipt readback.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
import secrets
import time

import anyio
import jwt

from banking_mcp.security import BankError, Principal
from frontend.server.action import project_action_result, verified_handoff
from frontend.server.chat import ChatError
from .state import TrustedBinding, new_state
from .bank_read import pin_bank_generation


class BankingActionHost:
    def __init__(self, bank_service, workflow_store, *, source_root=None):
        self.bank = bank_service
        self.workflow_store = workflow_store
        self.source_root, self.repository = source_root, None
        if bank_service.config.mode != "delegated":
            raise ValueError("delegated banking sandbox required")
        self.ledger_generation = pin_bank_generation(bank_service, retained_state_paths=(workflow_store.path,))
        with self.bank.store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS gloria_host_actions(
                    binding TEXT NOT NULL, request_id TEXT NOT NULL, query_id TEXT,
                    pending_hash TEXT, target TEXT, snapshot TEXT, handoff_id TEXT,
                    PRIMARY KEY(binding,request_id));
                CREATE UNIQUE INDEX IF NOT EXISTS gloria_host_pending
                    ON gloria_host_actions(binding,pending_hash) WHERE pending_hash IS NOT NULL;
                CREATE TABLE IF NOT EXISTS gloria_host_cancelled(
                    binding TEXT NOT NULL, pending_hash TEXT NOT NULL, query_id TEXT,
                    cancelled_at INTEGER NOT NULL, PRIMARY KEY(binding,pending_hash));
                CREATE TABLE IF NOT EXISTS gloria_handoff_packets(
                    binding TEXT NOT NULL, handoff_id TEXT NOT NULL, query_id TEXT,
                    request_id TEXT NOT NULL, packet_json TEXT NOT NULL,
                    PRIMARY KEY(binding,handoff_id));
            """)

    def bind_repository(self, repository):
        if repository.settings.data_dir.resolve() != self.bank.config.data_dir.resolve():
            raise ValueError("inquiry and action repositories must share a dataset")
        self.repository = repository
        self.bank.actions.trusted_evidence_reader = self._evidence

    def _evidence(self, principal, snapshot, target):
        if self.repository is None:
            raise BankError("risk_data_unavailable")
        from .bank_read import OwnedBankReads
        reader = OwnedBankReads(self.bank, self.repository, principal,
            source_root=self.source_root, clock=self.bank.actions.clock)
        return reader.action_evidence(target, snapshot.id)

    def _admission(self, chat, headers, payload, *, revoke=False):
        try:
            expected = "Bearer " + chat._execution_token
            if not secrets.compare_digest(headers.get("Authorization", ""), expected):
                raise ValueError()
            token = headers.get("X-Flujo-User-Assertion")
            claims = jwt.decode(token, chat._key.public_key(), algorithms=["EdDSA"],
                audience="flujo-banking-ingress", issuer=chat._issuer,
                options={"require": ["sub", "session_id", "session_exp", "iat", "nbf", "exp", "jti", "scope"]})
            if claims.get("scope") != ["bank:read"] or claims["exp"] > claims["session_exp"]:
                raise ValueError()
            subject, sid, expiry = claims["sub"], claims["session_id"], claims["session_exp"]
            customer = chat._approved_subject_customers[subject]
            if self.bank.config.principal_customers.get(subject) != customer:
                raise ValueError()
            with chat._connection() as db:
                row = db.execute("SELECT * FROM chat_sessions WHERE session_id=?", (sid,)).fetchone()
            if (not row or row["owner"] != chat._owner_for_subject(subject) or row["expires"] != expiry
                    or row["subject"] != subject or row["customer_id"] != customer
                    or (row["revoked"] and not revoke) or expiry <= time.time()):
                raise ValueError()
            conversation = row["conversation_id"]
            if not conversation or (not revoke and payload.get("conversationId") != conversation):
                raise ValueError()
            principal = Principal(subject, customer, sid, conversation, expiry, self.ledger_generation)
            if not revoke:
                from .bank_read import assert_bank_principal
                assert_bank_principal(self.bank, principal)
            return principal, row
        except (ValueError, TypeError, KeyError, jwt.PyJWTError, BankError):
            raise ChatError("action_authorization_failed", 401, "La sesión de la solicitud no está disponible.") from None

    def query_scope(self, chat, customer, sid, expiry, target_reference, query_id=None):
        subject, owner = chat._identity(customer, sid, expiry)
        with chat._connection() as db:
            row = db.execute("SELECT * FROM chat_sessions WHERE session_id=?", (sid,)).fetchone()
        if not row or row["revoked"] or not row["conversation_id"]:
            raise ChatError("inquiry_required", 409, "Primero consulta el movimiento con Savia.")
        binding = TrustedBinding(owner=owner, customer_id=customer, session_id=sid,
            conversation_id=row["conversation_id"], expires_at=expiry)
        state = self.workflow_store.load(binding)
        if not state:
            raise ChatError("inquiry_required", 409, "Primero consulta el movimiento con Savia.")
        scopes = state["runtime"].get("query_scopes", {})
        if scopes:
            selected = query_id or state["runtime"].get("active_query_id")
            capsule = scopes.get(selected)
            if not isinstance(capsule, dict):
                raise ChatError("action_scope_required", 409, "Selecciona la consulta que deseas continuar.")
            workflow = capsule.get("workflow_state", {})
        else:
            if query_id is not None:
                raise ChatError("action_mismatch", 409, "La consulta seleccionada ya no está disponible.")
            selected, workflow = None, state["workflow_state"]
        if target_reference and workflow.get("transaction_id") != target_reference:
            raise ChatError("action_mismatch", 409, "Selecciona el movimiento de esta consulta.")
        return {"query_id": selected, "snapshot_hash": workflow.get("candidate_snapshot_hash")}

    def _record(self, principal, request_id, query_id, *, handle=None, target=None, snapshot=None, handoff_id=None):
        hashed = hashlib.sha256(handle.encode()).hexdigest() if handle else None
        with self.bank.store.authority(principal, write=True) as db:
            previous = db.execute("SELECT query_id,pending_hash,target,snapshot FROM gloria_host_actions WHERE binding=? AND request_id=?",
                (principal.binding(), request_id)).fetchone()
            expected = (query_id, hashed, target, snapshot)
            if previous and previous != expected:
                raise BankError("authorization_denied")
            db.execute("INSERT OR IGNORE INTO gloria_host_actions VALUES (?,?,?,?,?,?,?)",
                (principal.binding(), request_id, query_id, hashed, target, snapshot, handoff_id))
            if handoff_id:
                db.execute("UPDATE gloria_host_actions SET handoff_id=? WHERE binding=? AND request_id=?",
                    (handoff_id, principal.binding(), request_id))

    def _pending_lineage(self, principal, handle, query_id=None, *, confirm=False):
        hashed = hashlib.sha256(handle.encode()).hexdigest()
        with self.bank.store.authority(principal) as db:
            row = db.execute("SELECT request_id,query_id,target,snapshot FROM gloria_host_actions WHERE binding=? AND pending_hash=?",
                (principal.binding(), hashed)).fetchone()
            cancelled = db.execute("SELECT 1 FROM gloria_host_cancelled WHERE binding=? AND pending_hash=?",
                (principal.binding(), hashed)).fetchone()
        if not row or (query_id is not None and row[1] != query_id) or (confirm and cancelled):
            raise BankError("authorization_denied")
        return row

    def _verified_handoff(self, principal, payload, binding, result):
        if result.get("state") != "created":
            return {"state": "handoff_unverified"}
        native = result["handoff"]
        with self.bank.store.authority(principal) as db:
            existing = db.execute("SELECT query_id,request_id,packet_json FROM gloria_handoff_packets "
                "WHERE binding=? AND handoff_id=?", (principal.binding(), native["id"])).fetchone()
        if existing:
            if existing[:2] != (payload.get("queryId"), payload["requestId"]):
                raise BankError("authorization_denied")
            try:
                packet = json.loads(existing[2])
            except (TypeError, ValueError):
                raise BankError("action_unverified") from None
            # Currentness describes this read; it may change after a dataset
            # refresh without changing the saved receipt or human packet.
            normalized_native = verified_handoff(native)
            if normalized_native is None:
                raise BankError("action_unverified")
            normalized_native["packet"] = deepcopy(native["packet"])
            immutable_native = {key: value for key, value in normalized_native.items() if key != "transaction_currentness"}
            saved_native = packet.get("native_handoff")
            if (not isinstance(saved_native, dict) or
                    {key: value for key, value in saved_native.items() if key != "transaction_currentness"} != immutable_native or
                    packet.get("schema") != "gloria-human-handoff/v1" or
                    packet.get("binding_digest") != binding.digest() or
                    packet.get("query_id") != payload.get("queryId")):
                raise BankError("action_unverified")
            return {"state": "handoff_verified", "handoff": native}
        state = self.workflow_store.load(binding)
        if state is None:
            raise BankError("action_unverified")
        query_id, handle = payload.get("queryId"), payload.get("pendingHandle")
        if state["runtime"].get("query_scopes"):
            from .state import activate_query_scope
            state = activate_query_scope(state, binding, query_id, fresh=False)
        state = deepcopy(state)
        target = None
        if handle:
            request, recorded_query, raw_target, snapshot = self._pending_lineage(principal, handle, query_id)
            if request != payload["requestId"] or recorded_query != query_id or snapshot != native["snapshot"]:
                raise BankError("authorization_denied")
            target = self.repository.reference("txn", principal.customer, raw_target)
            if state["workflow_state"].get("transaction_id") != target:
                raise BankError("action_unverified")
        else:
            state["workflow_state"]["transaction_id"] = None
        # Reevaluate with current trusted evidence. A user may request review
        # after an inquiry, or source-backed risk may change after the reply.
        from .policy import decide
        now = datetime.fromtimestamp(self.bank.actions.clock(), timezone.utc)
        clock_turn = new_state(binding, now=now)["turn"]
        state["turn"].update(current_timestamp=clock_turn["current_timestamp"], current_date=clock_turn["current_date"])
        if target and native["transaction_currentness"] == "same_snapshot":
            from .bank_read import OwnedBankReads
            reader = OwnedBankReads(self.bank, self.repository, principal, source_root=self.source_root,
                clock=self.bank.actions.clock)
            for name in ("get_transaction", "get_related_complaints"):
                state["tool_results"][name] = reader._read(name, {"transaction_id": target, "snapshot_id": native["snapshot"]})
        if native["reason"] in {"customer_request", "emergency"}:
            state["turn"]["human_requested"] = True
            state["turn"]["emotional_context"] = "Emergencia" if native["reason"] == "emergency" else "Neutro"
            state["turn"]["clarification"] = {"resolution_type": None, "selected_ref": None}
        state["workflow_state"]["policy_decision"] = decide(state)
        snapshot_hash = state["workflow_state"].get("candidate_snapshot_hash") if target else None
        state["runtime"]["handoff_lineage"] = dict(query_id=query_id, binding_digest=binding.digest(),
            handoff_id=native["id"], request_id=payload["requestId"], target_transaction_id=target,
            snapshot_id=native["snapshot"], snapshot_hash=snapshot_hash, host_pending_handle=handle)
        from .handoff import assemble_handoff_packet
        try:
            packet = assemble_handoff_packet(state, native, binding=binding)
            encoded = json.dumps(packet, ensure_ascii=False, allow_nan=False, sort_keys=True)
        except (ValueError, TypeError, KeyError):
            raise BankError("action_unverified") from None
        with self.bank.store.authority(principal, write=True) as db:
            db.execute("INSERT OR IGNORE INTO gloria_handoff_packets VALUES (?,?,?,?,?)",
                (principal.binding(), native["id"], query_id, payload["requestId"], encoded))
            saved = db.execute("SELECT packet_json FROM gloria_handoff_packets WHERE binding=? AND handoff_id=?",
                (principal.binding(), native["id"])).fetchone()
        if not saved or saved[0] != encoded:
            raise BankError("action_unverified")
        self._record(principal, payload["requestId"], query_id, handle=handle,
            target=raw_target if handle else None, snapshot=native["snapshot"], handoff_id=native["id"])
        return {"state": "handoff_verified", "handoff": native}

    def _execute(self, principal, payload, binding):
        operation = payload.get("operation")
        query_id = payload.get("queryId")
        actions = self.bank.actions
        if operation == "prepare":
            result = actions.prepare(principal, payload["transactionId"], payload["snapshot"], payload["requestId"])
            self._record(principal, payload["requestId"], query_id, handle=result["pending_handle"],
                target=payload["transactionId"], snapshot=payload["snapshot"])
            base = {"pending_handle": result["pending_handle"], "snapshot": result["snapshot"], "transaction": result["transaction"]}
            if result["decision"] == "existing_case":
                return {**base, "state": "existing_case_verified", "receipt": result["existing_case"].get("receipt")}
            if result["decision"] == "intake":
                return {**base, "state": "pending_confirmation"}
            handoff = actions.handoff(principal, result["reason"], result["pending_handle"], payload["requestId"], [])
            handoff_payload = {**payload, "pendingHandle": result["pending_handle"]}
            return {**base, **self._verified_handoff(principal, handoff_payload, binding, handoff), "reason": result["reason"]}
        if operation in {"confirm", "receipt"}:
            self._pending_lineage(principal, payload["pendingHandle"], query_id, confirm=operation == "confirm")
            result = (actions.confirm(principal, payload["pendingHandle"], payload.get("confirmed"))
                if operation == "confirm" else actions.receipt(principal, payload["pendingHandle"]))
            # The action method itself rereads the durable receipt. Its raw write
            # response is never promoted; the public projector checks facts too.
            return {"state": "intake_verified" if result.get("state") == "created" else "action_unverified", "receipt": result.get("receipt")}
        if operation == "handoff":
            handle = payload.get("pendingHandle")
            if handle:
                self._pending_lineage(principal, handle, query_id)
            result = actions.handoff(principal, payload["reason"], handle, payload.get("requestId"), payload.get("unanswered_questions", []))
            return self._verified_handoff(principal, payload, binding, result)
        raise BankError("invalid_arguments")

    def _execute_admitted(self, chat, principal, payload, binding):
        # The frontend writer lock orders this action against durable logout and
        # cancellation. A queued remote revocation alone cannot fence a local
        # bank commit. Keep this lock through bank write and receipt readback.
        with chat._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM chat_sessions WHERE session_id=?", (principal.session,)).fetchone()
            if (not row or row["revoked"] or row["expires"] <= time.time() or
                    row["expires"] != principal.expires or row["owner"] != binding.owner or
                    row["subject"] != principal.subject or row["customer_id"] != principal.customer or
                    row["conversation_id"] != principal.conversation or
                    chat._approved_subject_customers.get(principal.subject) != principal.customer or
                    self.bank.config.principal_customers.get(principal.subject) != principal.customer):
                raise BankError("authorization_denied")
            return self._execute(principal, payload, binding)

    async def post(self, path, headers, payload, chat):
        revoke = path == "/v1/banking/session/revoke"
        principal, row = self._admission(chat, headers, payload, revoke=revoke)
        if revoke:
            self.bank.store.revoke(principal.session, principal=principal)
            return {"revoked": True}
        if path != "/v1/banking/action":
            raise ChatError("action_unavailable", 503, "La solicitud no está disponible.")
        try:
            binding = TrustedBinding(owner=row["owner"], customer_id=principal.customer,
                session_id=principal.session, conversation_id=principal.conversation, expires_at=principal.expires)
            result = await anyio.to_thread.run_sync(lambda: self._execute_admitted(chat, principal, payload, binding), abandon_on_cancel=True)
            self._admission(chat, headers, payload)
            return project_action_result(result)
        except BankError as exc:
            if exc.code in {"action_unverified", "write_failed"}:
                return {"state": "action_unverified"}
            raise ChatError("action_rejected", 409, "La solicitud ya no puede continuar. Revisa su estado.") from None

    def cancel(self, chat, customer, sid, expiry, handle, query_id=None):
        subject, _ = chat._identity(customer, sid, expiry)
        with chat._connection() as db:
            row = db.execute("SELECT * FROM chat_sessions WHERE session_id=?", (sid,)).fetchone()
        if not row or row["revoked"]:
            raise ChatError("session_expired", 401, "Tu sesión expiró. Vuelve a ingresar.")
        principal = Principal(subject, customer, sid, row["conversation_id"], expiry, self.ledger_generation)
        from .bank_read import assert_bank_principal
        assert_bank_principal(self.bank, principal)
        self._pending_lineage(principal, handle, query_id)
        hashed = hashlib.sha256(handle.encode()).hexdigest()
        with self.bank.store.authority(principal, write=True) as db:
            pending = db.execute("SELECT confirmation_state FROM action_pending WHERE id=? AND binding=?", (hashed, principal.binding())).fetchone()
            if not pending or pending[0] != "prepared":
                return False  # An attempted write remains uncertain and readable.
            db.execute("INSERT OR IGNORE INTO gloria_host_cancelled VALUES (?,?,?,?)", (principal.binding(), hashed, query_id, int(time.time())))
            db.execute("UPDATE action_pending SET expires=0 WHERE id=? AND binding=? AND confirmation_state='prepared'", (hashed, principal.binding()))
        return True
