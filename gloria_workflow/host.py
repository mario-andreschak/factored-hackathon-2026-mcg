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
from .state import ConversationStore


class RepositoryBank:
    def __init__(self, repository, chat_service, profile_id, session_id, session_exp, *, source_reader=None):
        self.repository, self.chat = repository, chat_service
        self.profile_id, self.session_id, self.session_exp = profile_id, session_id, session_exp
        self.customer = repository.profile_customer(profile_id)
        self.source_reader = source_reader
        self._binding = None

    def bind_context(self, binding):
        from dataclasses import asdict, is_dataclass
        context = asdict(binding) if is_dataclass(binding) else dict(binding)
        _, owner = self.chat._identity(self.customer, self.session_id, self.session_exp)
        if any(context.get(key) != value for key, value in {
                "owner": owner, "customer_id": self.customer, "session_id": self.session_id,
                "expires_at": self.session_exp}.items()):
            raise ValueError("workflow binding mismatch")
        self._binding = context
        self._current()

    def _current(self):
        if self.repository.profile_customer(self.profile_id) != self.customer:
            raise ValueError("customer binding changed")
        self.chat._identity(self.customer, self.session_id, self.session_exp)
        with self.chat._connection() as db:
            row = db.execute("SELECT revoked,customer_id FROM chat_sessions WHERE session_id=?", (self.session_id,)).fetchone()
            if row and (row["revoked"] or row["customer_id"] != self.customer):
                raise ValueError("session unavailable")
            if self._binding:
                conversation = db.execute("SELECT conversation_id FROM chat_sessions WHERE session_id=?", (self.session_id,)).fetchone()
                if conversation and conversation[0] and conversation[0] != self._binding["conversation_id"]:
                    raise ValueError("conversation binding mismatch")

    @staticmethod
    def _row(row):
        return {"transaction_id": row["reference"], "transaction_date": row["occurred_at"], "process_date": row["process_date"], "amount": row["amount"], "currency": row["currency"], "transaction_status": row["status"], "transaction_type": row["type"], "merchant_name": row.get("merchant"), "channel": row.get("channel"), "ref": row.get("ref")}

    async def read(self, name, args):
        self._current()
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
            self._current()
            with self.chat._connection() as db:
                row = db.execute("SELECT owner,expires,prepare_conversation_id FROM action_status WHERE session_id=?", (self.session_id,)).fetchone()
            verified = bool(self._binding and (result.get("state") == "none" or (row and
                row["owner"] == self._binding["owner"] and row["expires"] == self.session_exp and
                row["prepare_conversation_id"] == self._binding["conversation_id"])))
            for field, public in (("expected_request_id", "request_id"), ("pending_handle", "pending_handle")):
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
    def __init__(self, model, state_path, *, source_reader=None):
        self.model, self.store = model, ConversationStore(state_path)
        self.source_reader = source_reader

    def __call__(self, repository, chat_service, profile_id, session_id, session_exp):
        bank = RepositoryBank(repository, chat_service, profile_id, session_id, session_exp, source_reader=self.source_reader)
        return Workflow(StageAdapters(self.model), bank, self.store)
