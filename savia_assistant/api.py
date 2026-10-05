"""Install narrow routes into the existing authenticated Savia application."""
from datetime import datetime
from decimal import Decimal
import hashlib
import hmac
from typing import Literal

from fastapi import HTTPException, Request, Response, Query
from pydantic import BaseModel, ConfigDict, Field

from frontend.server.language import MinimizedFacts


class Intake(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    message: str = Field(min_length=1, max_length=1000)
    language: Literal["es", "pt"] = "es"
    transaction_reference: str | None = Field(default=None, pattern=r"^txn_[a-f0-9]{24}$")


class Resolution(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    resolved: Literal[True]


def install_routes(app, authenticate):
    def scoped(request):
        current = authenticate(request)
        state = request.app.state.bank_state
        customer = request.app.state.repository.profile_customer(current.profile_id)
        # Stable case ownership survives a renewed bank session; fresh cookies
        # are still required to read cases. Neither owner nor customer goes to LLM.
        owner = hmac.new(state.secret, ("savia-inquiry:"+customer).encode(), hashlib.sha256).hexdigest()
        return current, owner, request.app.state.inquiries

    @app.get("/api/assistant/cases")
    def cases(request: Request, language: Literal["es", "pt"] = "es"):
        _, owner, service = scoped(request)
        return service.list(owner, language)

    @app.get("/api/assistant/voice-update")
    def voice_update(request: Request, case_id: str = Query(pattern=r"^i_[a-f0-9]{32}$"),
                     after_event_id: int = Query(default=0, ge=0), language: Literal["es", "pt"] = "es"):
        """Authenticated bounded narration of one actual meaningful event.

        Avatar observes this exact server response and uses its existing
        receipt/single-consumption machinery. The browser supplies no prose.
        """
        _, owner, service = scoped(request)
        item = next((i for i in service.list(owner, language)["items"] if i["id"] == case_id), None)
        if item is None:
            raise HTTPException(404, "Consulta no disponible / Consulta indisponível")
        event = item["events"][-1] if item["events"] else None
        if event is None or event["id"] <= after_event_id:
            return Response(status_code=204)
        return {**item["voice_update"], "event_id":event["id"],
                "inquiry_state":item["state"], "bank_authority":False}

    @app.post("/api/assistant/cases", status_code=202)
    def create_case(body: Intake, request: Request):
        current, owner, service = scoped(request)
        if service.model is None:
            raise HTTPException(503, "Los agentes no están conectados / Os agentes não estão conectados")
        facts = None
        if body.transaction_reference:
            selected = request.app.state.repository.transaction(current.profile_id, body.transaction_reference)
            if not selected:
                raise HTTPException(404, "Movimiento no disponible / Lançamento indisponível")
            try:
                status = str(selected["status"]).lower()
                facts = MinimizedFacts(
                    datetime.fromisoformat(selected["occurred_at"].replace("Z", "+00:00")).date().isoformat(),
                    format(Decimal(str(selected["amount"])), ".2f"), selected["currency"],
                    (selected.get("merchant") or "").strip()[:80] or None,
                    status if status in {"approved", "pending", "reversed"} else "unknown")
            except (ValueError, TypeError, KeyError):
                raise HTTPException(422, "Datos visibles inválidos / Dados visíveis inválidos") from None
        try:
            case_id = service.create(owner, body.message.strip(), body.language, facts)
        except ValueError:
            raise HTTPException(422, "Consulta inválida o límite alcanzado / Consulta inválida ou limite atingido") from None
        return {"id": case_id, **service.list(owner, body.language)}

    @app.post("/api/assistant/cases/{case_id}/resolve")
    def resolve_case(case_id: str, body: Resolution, request: Request):
        _, owner, service = scoped(request)
        try:
            service.resolve(owner, case_id)
        except KeyError:
            raise HTTPException(404, "Consulta no disponible / Consulta indisponível") from None
        except ValueError:
            raise HTTPException(409, "El equipo sigue trabajando / A equipe continua trabalhando") from None
        return {"id": case_id, "state": "informational_resolved", "bank_authority": False}
