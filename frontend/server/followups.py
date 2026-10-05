"""Opt-in, durable receipt follow-up. Never submits or repeats bank writes."""
from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from contextlib import contextmanager
import json
import logging
from pathlib import Path
import sqlite3
import time
import uuid

from .action import verified_receipt
from .chat import ChatError

logger = logging.getLogger("banking.frontend.followups")


class Followups:
    interval = 1800  # Half-hour receipt checks while the authorized session lives.

    def __init__(self, state_dir: Path, service):
        self.path = Path(state_dir) / "frontend-followups.sqlite3"
        self.service = service
        with self.connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS followups (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL, owner TEXT NOT NULL,
                customer_id TEXT NOT NULL, expires INTEGER NOT NULL,
                target_reference TEXT NOT NULL, receipt_json TEXT NOT NULL,
                handle TEXT NOT NULL, conversation TEXT NOT NULL, query_id TEXT,
                created_at INTEGER NOT NULL, last_checked_at INTEGER,
                next_check_at INTEGER, state TEXT NOT NULL, updates_json TEXT NOT NULL,
                lease TEXT, lease_until INTEGER NOT NULL DEFAULT 0,
                UNIQUE(session_id, handle))""")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def authorized(self, customer, session_id, expires):
        subject, owner = self.service._identity(customer, session_id, expires)
        with self.service._connection() as db:
            self.service._assert_action_session(db, session_id, owner, expires)
        return subject, owner

    def enroll(self, customer, session_id, expires):
        _, owner = self.authorized(customer, session_id, expires)
        with self.service._connection() as db:
            row = self.service._action_row(db, session_id, owner, expires)
            saved = self.service._action_result(row) if row else {}
            receipt = verified_receipt(saved.get("receipt"))
            if (saved.get("state") not in {"intake_verified", "existing_case_verified"}
                    or not receipt or not saved.get("pending_handle")
                    or not saved.get("target_reference")):
                raise ChatError("action_invalid_state", 409, "Verified receipt required")
            binding = db.execute("SELECT * FROM chat_sessions WHERE session_id=?", (session_id,)).fetchone()
            conversation = (binding["bank_context_id"] if "bank_context_id" in binding.keys()
                            else row["action_conversation_id"] or binding["conversation_id"])
            query_id = row["query_scope_id"] if "query_scope_id" in row.keys() else None
        now = int(time.time())
        with self.connection() as db:
            db.execute("""INSERT OR IGNORE INTO followups
                (id,session_id,owner,customer_id,expires,target_reference,receipt_json,handle,
                 conversation,query_id,created_at,next_check_at,state,updates_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'scheduled','[]')""",
                ("f_" + uuid.uuid4().hex, session_id, owner, customer, expires,
                 saved["target_reference"], json.dumps(receipt), saved["pending_handle"],
                 conversation, query_id, now, now))

    @staticmethod
    def wording(state, language, receipt):
        pt = language == "pt"
        facts = receipt["transaction"]
        event = date.fromisoformat(facts["transaction_date"][:10])
        months = (["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
                  if pt else ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"])
        when = f"{event.day} de {months[event.month - 1]} de {event.year}"
        amount = format(Decimal(facts["amount"]), ",.2f").replace(",", "_").replace(".", ",").replace("_", ".")
        charge = f"{amount} {facts['currency']} · {when}"
        if facts.get("merchant"):
            charge += f" · {facts['merchant']}"
        if state == "checked":
            message = ("Conferi novamente: seu comprovante continua registrado. Ainda não há decisão do banco nem reembolso verificado."
                       if pt else "Volví a comprobarlo: tu recibo sigue registrado. Aún no hay decisión del banco ni reembolso verificado.")
        elif state == "unavailable":
            message = ("Não consegui consultar agora. O último comprovante permanece salvo; isto não indica mudança no caso."
                       if pt else "No pude consultar ahora. El último recibo sigue guardado; esto no indica un cambio en el caso.")
        elif state == "paused":
            message = ("A consulta automática foi pausada porque a autorização desta sessão terminou."
                       if pt else "La consulta automática se pausó porque terminó la autorización de esta sesión.")
        else:
            message = ("Vou conferir este comprovante simulado em segundo plano a cada 30 minutos enquanto esta sessão estiver autorizada."
                       if pt else "Comprobaré este recibo simulado en segundo plano cada 30 minutos mientras esta sesión esté autorizada.")
        step = (f"Guarde o protocolo {receipt['id']} e o lançamento {charge}. Se reconhecer o estabelecimento ou tiver mais informações, conte aqui. Para solicitar uma decisão sobre a cobrança real, use o canal oficial do seu banco."
                if pt else f"Guarda el folio {receipt['id']} y el cargo {charge}. Si reconoces el comercio o tienes más información, cuéntamelo aquí. Para solicitar una decisión sobre el cargo real, usa el canal oficial de tu banco.")
        return message, step

    def list(self, customer, session_id, expires, language="es"):
        # A valid bank cookie precedes the first admitted chat turn. Reading
        # an empty follow-up view must not report that fresh login as expired.
        with self.service._connection() as db:
            binding = db.execute("SELECT 1 FROM chat_sessions WHERE session_id=?", (session_id,)).fetchone()
        if not binding:
            with self.connection() as db:
                retained = db.execute("SELECT 1 FROM followups WHERE session_id=?", (session_id,)).fetchone()
            if retained:
                raise ChatError("session_mismatch", 401, "Follow-up admission missing")
            return {"items": []}
        _, owner = self.authorized(customer, session_id, expires)
        with self.connection() as db:
            rows = db.execute("SELECT * FROM followups WHERE session_id=? AND owner=? AND expires=? ORDER BY created_at DESC LIMIT 20",
                              (session_id, owner, expires)).fetchall()
        items = []
        for row in rows:
            receipt = json.loads(row["receipt_json"])
            message, step = self.wording(row["state"], language, receipt)
            items.append({"id": row["id"], "target_reference": row["target_reference"],
                "receipt_id": receipt["id"], "simulated": True, "state": row["state"],
                "created_at": row["created_at"], "last_checked_at": row["last_checked_at"],
                "next_check_at": row["next_check_at"], "message": message, "next_step": step,
                "updates": [{**update, "message": self.wording(update["state"], language, receipt)[0]}
                            for update in json.loads(row["updates_json"])]})
        return {"items": items}

    async def check(self, *, session_id=None, force=False):
        now = int(time.time())
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("""SELECT * FROM followups WHERE next_check_at IS NOT NULL
                AND (? IS NULL OR session_id=?) AND (? OR next_check_at<=?)
                AND lease_until<=? ORDER BY next_check_at LIMIT 8""",
                (session_id, session_id, force, now, now)).fetchall()
            leases = []
            for row in rows:
                lease = uuid.uuid4().hex
                db.execute("UPDATE followups SET lease=?,lease_until=? WHERE id=?", (lease, now + 120, row["id"]))
                leases.append((row, lease))
        for row, lease in leases:
            state = "unavailable"
            try:
                subject, owner = self.authorized(row["customer_id"], row["session_id"], row["expires"])
                if owner != row["owner"]:
                    raise ChatError("session_mismatch", 401, "Session changed")
                payload = {"operation": "receipt", "conversationId": row["conversation"], "pendingHandle": row["handle"]}
                if row["query_id"]:
                    payload["queryId"] = row["query_id"]
                if hasattr(self.service, "_bank_post"):
                    result = await self.service._bank_post(subject, row["session_id"], row["expires"], payload, timeout_seconds=10)
                else:
                    result = await self.service._post("/v1/banking/action",
                        self.service._headers(subject, row["session_id"], row["expires"]), payload, timeout_seconds=10)
                self.authorized(row["customer_id"], row["session_id"], row["expires"])
                if result.get("state") == "intake_verified" and verified_receipt(result.get("receipt")) == json.loads(row["receipt_json"]):
                    state = "checked"
            except ChatError as exc:
                if exc.status_code == 401 or row["expires"] <= int(time.time()):
                    state = "paused"
            except asyncio.CancelledError:
                raise
            except Exception:
                pass  # Fixed public state; transport bodies/credentials never enter history.
            checked = int(time.time())
            updates = json.loads(row["updates_json"])
            # Unchanged checks refresh the visible clock silently; only a new
            # result enters the customer's activity log.
            if not updates or updates[-1]["state"] != state:
                updates = (updates + [{"checked_at": checked, "state": state}])[-12:]
            next_check = min(checked + self.interval, row["expires"]) if state != "paused" else None
            with self.connection() as db:
                db.execute("""UPDATE followups SET state=?,last_checked_at=?,next_check_at=?,
                    updates_json=?,lease=NULL,lease_until=0 WHERE id=? AND lease=?""",
                    (state, checked, next_check, json.dumps(updates), row["id"], lease))

    async def loop(self, stop):
        while not stop.is_set():
            try:
                await self.check()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # A storage outage must not kill the lifespan worker. Leases
                # expire naturally; the durable request is never resubmitted.
                logger.error("Receipt follow-up check unavailable: %s", type(exc).__name__)
            try:
                await asyncio.wait_for(stop.wait(), timeout=5)
            except TimeoutError:
                pass
