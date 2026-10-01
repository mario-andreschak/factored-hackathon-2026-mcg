"""Owner-scoped banking application ports.

Serving snapshot reads are not relabelled as pinned-source verification. Missing
historical complaint/risk adapters are explicit rather than interpreted as zero.
"""
from __future__ import annotations

from decimal import Decimal
from datetime import date, timedelta
import hashlib
import json

from .runtime import Workflow
from .prompts import StageAdapters
from .state import ConversationStore, TrustedBinding
from .bank_read import OwnedBankReads
from banking_mcp.security import Principal


def _admitted_session(chat, customer, session_id, session_exp):
    """Resolve persisted admission only; caller selectors confer no authority."""
    subject, owner = chat._identity(customer, session_id, session_exp)
    with chat._connection() as db:
        row = db.execute("SELECT * FROM chat_sessions WHERE session_id=?", (session_id,)).fetchone()
    if (not row or row["revoked"] or row["customer_id"] != customer or
            row["subject"] != subject or row["owner"] != owner or
            row["expires"] != session_exp or not row["conversation_id"]):
        raise ValueError("session unavailable")
    return subject, owner, row["conversation_id"]


class RepositoryBank:
    def __init__(self, repository, chat_service, profile_id, session_id, session_exp, *, source_reader=None,
                 bank_service=None, source_root=None):
        self.repository, self.chat = repository, chat_service
        self.profile_id, self.session_id, self.session_exp = profile_id, session_id, session_exp
        self.customer = repository.profile_customer(profile_id)
        self.source_reader = source_reader
        self.bank_service, self.source_root = bank_service, source_root
        self.bank_reads = None
        self._binding = None

    def bind_context(self, binding):
        from dataclasses import asdict, is_dataclass
        context = asdict(binding) if is_dataclass(binding) else dict(binding)
        subject, owner = self.chat._identity(self.customer, self.session_id, self.session_exp)
        if any(context.get(key) != value for key, value in {
                "owner": owner, "customer_id": self.customer, "session_id": self.session_id,
                "expires_at": self.session_exp}.items()):
            raise ValueError("workflow binding mismatch")
        self._binding = context
        self._current()
        if self.bank_service is not None:
            principal = Principal(subject, self.customer, self.session_id, context["conversation_id"], self.session_exp)
            self.bank_reads = OwnedBankReads(self.bank_service, self.repository, principal,
                source_root=self.source_root, guard=self._current)

    def _current(self):
        if self.repository.profile_customer(self.profile_id) != self.customer:
            raise ValueError("customer binding changed")
        _, owner, conversation = _admitted_session(self.chat, self.customer, self.session_id, self.session_exp)
        if self._binding and (owner != self._binding["owner"] or
                              conversation != self._binding["conversation_id"]):
            raise ValueError("conversation binding mismatch")

    @staticmethod
    def _row(row):
        return {"transaction_id": row["reference"], "transaction_date": row["occurred_at"], "process_date": row["process_date"], "amount": row["amount"], "currency": row["currency"], "transaction_status": row["status"], "transaction_type": row["type"], "merchant_name": row.get("merchant"), "channel": row.get("channel"), "ref": row.get("ref")}

    async def read(self, name, args):
        self._current()
        if self.bank_reads is not None and name != "host_action_status":
            return await self.bank_reads.read(name, args)
        if name == "get_customer_profile":
            data = self.repository.overview(self.profile_id, 1)
            return {"status": "ok", "currencies": sorted({p["currency"] for p in data["products"]}), "products": [{"currency": p["currency"]} for p in data["products"]]}
        if name == "search_transactions":
            slots = args.get("slots", {})
            unsupported = [field for field in ("city", "country", "product_hint", "product_last4")
                           if slots.get(field) not in (None, "")]
            if unsupported:
                return {"status": "error", "code": "unsupported_filter", "fields": unsupported}
            # Owner-scoped pages must be exhausted before zero/uniqueness claims.
            rows, offset, search_snapshot = [], 0, None
            metadata = {}
            for _ in range(20):
                data = self.repository.overview(self.profile_id, 500, offset=offset)
                metadata = data["metadata"]
                page_snapshot = metadata.get("build_id")
                if not isinstance(page_snapshot, str) or not page_snapshot:
                    return {"status": "error", "code": "search_snapshot_unavailable"}
                if search_snapshot is not None and page_snapshot != search_snapshot:
                    return {"status": "error", "code": "snapshot_changed"}
                search_snapshot = page_snapshot
                rows.extend(data["transactions"])
                nxt = metadata.get("next_offset")
                if nxt is None:
                    break
                offset = nxt
            else:
                return {"status": "error", "code": "search_coverage_incomplete"}
            matched = []
            event_days = [row["occurred_at"][:10] for row in rows]
            last_event = max(event_days) if event_days else None
            first_event = min(event_days) if event_days else None
            if not slots.get("date_from") and not slots.get("date_to") and last_event:
                default_from = max(first_event, (date.fromisoformat(last_event)-timedelta(days=89)).isoformat())
                date_from, date_to = default_from, last_event
            else:
                date_from, date_to = slots.get("date_from"), slots.get("date_to")
            for row in rows:
                event_date = row["occurred_at"][:10]
                if slots.get("transaction_id") and row["reference"] != slots["transaction_id"]:
                    continue
                if date_from and event_date < date_from:
                    continue
                if date_to and event_date > date_to:
                    continue
                if slots.get("currency") and row["currency"] != slots["currency"]:
                    continue
                if slots.get("transaction_type") and row["type"] != slots["transaction_type"]:
                    continue
                if slots.get("channel") and row.get("channel") != slots["channel"]:
                    continue
                if slots.get("merchant") and slots["merchant"].casefold() not in (row.get("merchant") or "").casefold():
                    continue
                if slots.get("amount") is not None:
                    tolerance = Decimal("0.10") if slots.get("amount_is_approximate") else Decimal("0.01")
                    requested = Decimal(str(slots["amount"]))
                    if abs(Decimal(str(row["amount"])) - requested) > abs(requested) * tolerance:
                        continue
                matched.append(self._row(row))
            for i, row in enumerate(matched[:5], 1):
                row["ref"] = str(i)
            snapshot = metadata.get("build_id")
            digest = hashlib.sha256(json.dumps([snapshot, [r["transaction_id"] for r in matched]], sort_keys=True).encode()).hexdigest()
            return {"status": "ok", "match_count": len(matched), "candidates": matched[:5], "snapshot_hash": digest, "search_context": {"coverage_complete": True, "snapshot_id": snapshot, "date_basis": "event_date", "date_from": date_from, "date_to": date_to, "used_snapshot_default": not slots.get("date_from") and not slots.get("date_to")}, "risk_signals": {}, "data_quality_flags": []}
        if name == "get_transaction":
            ref = args.get("transaction_id")
            row = self.repository.transaction(self.profile_id, ref)
            if row is None:
                return {"status": "error", "code": "reference_unavailable"}
            snapshot = self.repository.snapshot().build.name
            expected_snapshot = args.get("snapshot_id") or args.get("snapshot_hash")
            if expected_snapshot and expected_snapshot != snapshot:
                return {"status": "error", "code": "snapshot_changed"}
            if self.source_reader:
                # A trusted MCP bridge can return source-verified canonical data.
                result = await self.source_reader(ref)
                self._current()
                if result.get("transaction", {}).get("transaction_id") != ref:
                    return {"status": "error", "code": "target_mismatch"}
                if self.repository.snapshot().build.name != snapshot or result.get("snapshot_id", result.get("snapshot")) != snapshot:
                    return {"status": "error", "code": "snapshot_changed"}
                return result
            return {"status": "ok", "transaction": self._row(row), "source_verified": False, "risk_data_complete": False, "risk_signals": {}, "data_quality_flags": ["source_readback_unavailable"], "snapshot_id": snapshot, "snapshot": snapshot}
        if name == "get_related_complaints":
            return {"status": "ok", "complaints": [], "duplicate_check": "incomplete", "report_window": {"coverage_complete": False, "prior_distinct_verified_count": None}, "data_quality_flags": ["historical_complaint_adapter_unavailable"]}
        if name in {"get_complaint", "list_customer_complaints"}:
            return {"status": "error", "code": "unsupported_history"}
        if name == "host_action_status":
            result = await self.chat.action_status(self.customer, self.session_id, self.session_exp)
            if result.get("state") == "intake_verified":
                result["snapshot"] = result["receipt"]["snapshot"]
            self._current()
            with self.chat._connection() as db:
                row = db.execute("SELECT owner,expires,action_conversation_id FROM action_status WHERE session_id=?", (self.session_id,)).fetchone()
            verified = bool(self._binding and (result.get("state") == "none" or (row and
                row["owner"] == self._binding["owner"] and row["expires"] == self.session_exp and
                row["action_conversation_id"] == self._binding["conversation_id"])))
            for field, public in (("expected_request_id", "request_id"), ("pending_handle", "pending_handle"),
                                  ("query_id", "query_id")):
                if args.get(field) and result.get(public) != args[field]:
                    verified = False
            return {"status": "ok", **result, "binding_verified": verified,
                    "binding": dict(self._binding or {})}
        raise ValueError("read tool unavailable")


class GloriaHostFactory:
    """Explicit server injection for an isolated application instance.

Construct with a configured model callable. Creating this factory does not
replace the shared FLUJO worker, change its graph, or enable portal actions.
"""
    def __init__(self, model, state_path, *, source_reader=None, bank_service=None, source_root=None):
        self.model, self.store = model, ConversationStore(state_path)
        self.source_reader = source_reader
        self.bank_service, self.source_root = bank_service, source_root

    def __call__(self, repository, chat_service, profile_id, session_id, session_exp):
        bank = RepositoryBank(repository, chat_service, profile_id, session_id, session_exp,
                              source_reader=self.source_reader, bank_service=self.bank_service,
                              source_root=self.source_root)
        return Workflow(StageAdapters(self.model), bank, self.store)

    def query_context(self, chat, customer, sid, expiry):
        """Readonly public registry projection for the exact admitted session."""
        _, owner, conversation = _admitted_session(chat, customer, sid, expiry)
        binding = TrustedBinding(owner=owner, customer_id=customer, session_id=sid,
            conversation_id=conversation, expires_at=expiry)
        state = self.store.load(binding)
        if state is None:
            return {"queries": [], "active_query_id": None}
        runtime = state["runtime"]
        scopes = runtime.get("query_scopes", {})
        queries = [{"query_id": key, "label": scopes[key]["query_text"],
                    "transaction_reference": scopes[key]["workflow_state"].get("transaction_id")}
                   for key in runtime.get("query_scope_order", [])]
        # Revocation/rebinding during the durable read must not release history.
        if _admitted_session(chat, customer, sid, expiry)[1:] != (owner, conversation):
            raise ValueError("conversation binding mismatch")
        return {"queries": queries, "active_query_id": runtime.get("active_query_id")}
