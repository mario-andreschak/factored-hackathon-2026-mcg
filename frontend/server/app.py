from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import re
from contextlib import asynccontextmanager, suppress
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
import duckdb

from .config import PROFILE_IDS, Settings
from .repository import DatasetUnavailable, Repository
from .state import Session, State
from .action import render_action_error


COOKIE = "flujo_bank_session"
logger = logging.getLogger("banking.frontend")


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    profile: str = Field(min_length=1, max_length=24)
    code: str = Field(min_length=1, max_length=128)


class InviteBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    code: str = Field(min_length=32, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class ChatBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    message: str = Field(min_length=1, max_length=4000)
    language: Literal["es", "pt"] = "es"
    transaction_reference: str | None = Field(default=None, pattern=r"^txn_[a-f0-9]{24}$")
    query_scope_id: str | None = Field(default=None, pattern=r"^q_[a-f0-9]{32}$")


class PrepareActionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    transaction_reference: str = Field(pattern=r"^txn_[a-f0-9]{24}$")
    request_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$")
    language: Literal["es", "pt"] = "es"
    query_scope_id: str | None = Field(default=None, pattern=r"^q_[a-f0-9]{32}$")


class ConfirmActionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    pending_handle: str = Field(pattern=r"^[A-Za-z0-9_-]{32,64}$")
    transaction_reference: str = Field(pattern=r"^txn_[a-f0-9]{24}$")
    confirmed: Literal[True]
    language: Literal["es", "pt"] = "es"
    query_scope_id: str | None = Field(default=None, pattern=r"^q_[a-f0-9]{32}$")


class HandoffActionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    reason: Literal["out_of_policy", "emergency", "customer_request", "clarification_exhausted",
                    "high_risk", "missing_evidence", "duplicate_review", "action_unverified"]
    pending_handle: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{32,64}$")
    transaction_reference: str | None = Field(default=None, pattern=r"^txn_[a-f0-9]{24}$")
    request_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$")
    language: Literal["es", "pt"] = "es"
    query_scope_id: str | None = Field(default=None, pattern=r"^q_[a-f0-9]{32}$")
    unanswered_questions: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]] = Field(
        default_factory=list, max_length=8)

    @field_validator("unanswered_questions", mode="before")
    @classmethod
    def plain_questions(cls, value):
        from .action import normalize_handoff_questions
        normalized = normalize_handoff_questions(value)
        if normalized is None:
            raise ValueError("invalid unanswered questions")
        return normalized


def create_app(settings: Settings | None = None, *, dispute_factory=None, bank_backend=None) -> FastAPI:
    # Initialize lazily, allowing imports/build checks without a dataset mount.
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        state = State(settings.state_dir)
        from .chat import ChatService
        if dispute_factory is not None or bank_backend is not None:
            from .dispute_chat import DisputeChatService
            chat_service = DisputeChatService(settings.chat, settings.state_dir, bank_backend=bank_backend)
        else:
            chat_service = ChatService(settings.chat, settings.state_dir)
        invite_bindings = ({key: value["customer_id"] for key, value in settings.profiles.items()}
                           if settings.auth_mode == "invite" else None)
        demo_bindings = ({key: value["customer_id"] for key, value in settings.profiles.items()
                          if key in PROFILE_IDS and value.get("customer_id")}
                         if settings.auth_mode == "demo" else None)
        # Auth rotation or a trusted customer rebind can delete valid bank
        # cookies. First persist revocations for sessions that reached FLUJO;
        # startup fails before deletion if an admitted identity is unresolved.
        admitted_rotations = 0
        for old_session, old_customer in state.sessions_invalidated_by(
                settings.auth_fingerprint(), invite_bindings, demo_bindings):
            if not chat_service.has_active_session(old_session.id, old_session.expires_at):
                continue
            admitted_rotations += 1
            customer = old_customer or chat_service.admitted_customer(old_session.id, old_session.expires_at)
            if not customer:
                raise RuntimeError("Cannot revoke admitted chat session without its customer")
            disposition = chat_service.queue_revoke(customer, old_session.id, old_session.expires_at)
            if disposition in {"unavailable", "unresolved"}:
                raise RuntimeError("Cannot queue admitted chat session revocation")
        if admitted_rotations and not chat_service.revocation_diagnostics()["configured"]:
            # A re-used state volume cannot switch to an invite deployment (or
            # lose its signer) while previously admitted worker work may run.
            # Pending intents survive, but the old browser policy remains until
            # the approved worker configuration is restored or state isolated.
            raise RuntimeError("Cannot rotate admitted chat sessions without configured worker revocation")
        if settings.auth_mode == "invite" and chat_service.has_any_session():
            # The invited synthetic candidate must never inherit stored real
            # conversations, including expired or already revoked ones.
            raise RuntimeError("Invite mode requires an isolated chat state volume")
        if settings.auth_mode == "invite":
            state.reconcile_auth(settings.auth_fingerprint(), invite_bindings)
        else:
            state.reconcile_auth(settings.auth_fingerprint())
            # Trusted demo rebinding invalidates sessions when customer changes.
            for profile_id, config in settings.profiles.items():
                if profile_id in PROFILE_IDS and config.get("customer_id"):
                    state.bind(profile_id, config["customer_id"])
        app.state.bank_state = state
        app.state.repository = Repository(settings, state)
        if bank_backend is not None:
            bank_backend.bind_repository(app.state.repository)
        app.state.dispute_factory = dispute_factory
        if settings.auth_mode == "invite":
            # An external candidate must refuse to start with a real, stale or
            # mismatched mount; no request may trigger automatic customer choice.
            app.state.repository.snapshot()
            for profile_id in settings.profiles:
                app.state.repository.profile(profile_id)
        # Even an unconfigured restart retains and accounts for past pending
        # revocations; it cannot sign a worker request without approved config.
        app.state.chat_service = chat_service
        stop_retries = asyncio.Event()
        app.state.revoke_retry_task = asyncio.create_task(
            app.state.chat_service.retry_pending_loop(stop_retries))

        def report_retry_exit(task):
            if not task.cancelled() and task.exception():
                logger.error("Chat revocation retry loop stopped: %s", type(task.exception()).__name__)

        app.state.revoke_retry_task.add_done_callback(report_retry_exit)
        try:
            yield
        finally:
            stop_retries.set()
            app.state.revoke_retry_task.cancel()
            with suppress(asyncio.CancelledError):
                await app.state.revoke_retry_task

    app = FastAPI(title="FLUJO banking demo", version="0.1.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(DatasetUnavailable)
    @app.exception_handler(duckdb.Error)
    async def dataset_unavailable(request, exc):
        return JSONResponse({"detail": "La instantánea bancaria no está disponible. Revisa el montaje de datos."}, status_code=503)

    @app.middleware("http")
    async def browser_protection(request: Request, call_next):
        if request.url.path.startswith("/api/") and request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            expected = settings.public_origin or f"{request.url.scheme}://{request.url.netloc}"
            invalid_origin = (origin != expected if settings.auth_mode == "invite" else
                              bool(origin and origin.rstrip("/") != expected.rstrip("/")))
            if request.headers.get("sec-fetch-site") == "cross-site" or invalid_origin:
                return JSONResponse({"detail": "Origen de solicitud no permitido."}, status_code=403)
            if request.method != "DELETE" and request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
                return JSONResponse({"detail": "Se requiere una solicitud JSON."}, status_code=415)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def session(request: Request) -> Session:
        value = request.app.state.bank_state.session(request.cookies.get(COOKIE))
        if not value:
            raise HTTPException(401, "Inicia sesión para ver tu banca.")
        return value

    async def revoke(request: Request, current: Session) -> tuple[str, bool]:
        # Deny local chat and persist worker revocation before deleting the
        # browser session. A failed queue must never be reported as confirmed.
        service = request.app.state.chat_service
        disposition = "unavailable"
        failed = False
        try:
            if service:
                customer = request.app.state.bank_state.customer(current.profile_id)
                if customer:
                    disposition = service.queue_revoke(customer, current.id, current.expires_at)
        except Exception as exc:
            failed = True
            logger.error("Chat revocation persistence failed: %s", type(exc).__name__)
        try:
            request.app.state.bank_state.delete_session(current)
        except Exception as exc:
            failed = True
            logger.error("Banking session deletion failed: %s", type(exc).__name__)
        return ("persist_failed" if failed else disposition), failed

    @app.get("/healthz")
    def health(request: Request):
        service = request.app.state.chat_service
        diagnostics = {"configured": False, "pending": 0, "retrying": 0,
                       "confirmed": 0, "expired_unconfirmed": 0, "last_error_code": None}
        if service:
            try:
                diagnostics = service.revocation_diagnostics()
            except Exception as exc:
                logger.error("Chat revocation diagnostics failed: %s", type(exc).__name__)
                diagnostics = {"configured": True, "status": "unavailable"}
            task = request.app.state.revoke_retry_task
            diagnostics["retry_worker_running"] = bool(task and not task.done())
        try:
            request.app.state.repository.snapshot()
        except DatasetUnavailable:
            return JSONResponse({"service": "banking-frontend", "status": "degraded",
                                 "dataset_ready": False, "chat_revocations": diagnostics}, status_code=503)
        return {"service": "banking-frontend", "status": "ok", "dataset_ready": True,
                "chat_revocations": diagnostics}

    @app.get("/api/auth/profiles")
    def profiles(request: Request):
        if settings.auth_mode == "invite":
            return {"mode": "invite", "demo": True, "profiles": []}
        public = []
        for profile in request.app.state.repository.profiles():
            public.append({k: profile[k] for k in ("id", "alias", "country", "segment", "description", "primary_currency")})
        return {"profiles": public, "demo": True}

    @app.post("/api/auth/login")
    async def login(body: LoginBody, request: Request, response: Response):
        if settings.auth_mode != "demo":
            raise HTTPException(404, "Ruta no disponible.")
        state = request.app.state.bank_state
        # Do not trust X-Forwarded-For unless a deployment configures its proxy;
        # hashing keeps IP addresses out of persistent attempt records.
        client = hashlib.sha256((request.client.host if request.client else "unknown").encode()).hexdigest()
        if not state.login_allowed(client):
            raise HTTPException(429, "Demasiados intentos. Intenta nuevamente en unos minutos.")
        if body.profile not in PROFILE_IDS or not hmac.compare_digest(body.code.encode(), settings.demo_code.encode()):
            state.record_failure(client)
            raise HTTPException(401, "Perfil o código de demostración incorrecto.")
        return await issue_session(request, response, body.profile)

    async def issue_session(request: Request, response: Response, profile_id: str):
        state = request.app.state.bank_state
        profile = request.app.state.repository.profile(profile_id)
        if old := state.session(request.cookies.get(COOKIE)):
            disposition, failed = await revoke(request, old)
            if failed:
                error = JSONResponse({"detail": "No se pudo confirmar el cierre completo de la sesión anterior."},
                                     status_code=503, headers={"X-Banking-Revoke": disposition})
                error.delete_cookie(COOKIE, httponly=True, secure=settings.secure_cookie, samesite="strict", path="/")
                return error
        token, _ = state.create_session(profile_id, settings.session_seconds)
        response.set_cookie(COOKIE, token, max_age=settings.session_seconds, httponly=True,
                            secure=settings.secure_cookie, samesite="strict", path="/")
        return {"authenticated": True, "auth_mode": settings.auth_mode, "profile": profile}

    @app.post("/api/auth/invite")
    async def invite(body: InviteBody, request: Request, response: Response):
        if settings.auth_mode != "invite":
            raise HTTPException(404, "Ruta no disponible.")
        # Invitations have 256 random bits. A shared proxy client address must
        # not let one visitor lock out everyone else; external ingress applies
        # its own per-visitor request limits without trusting forwarded headers.
        digest = hashlib.sha256(body.code.encode()).hexdigest()
        profile_id = None
        for configured_digest, target in settings.invites.items():
            if hmac.compare_digest(digest, configured_digest):
                profile_id = target
        if profile_id is None:
            raise HTTPException(401, "Invitación no válida.")
        return await issue_session(request, response, profile_id)

    @app.get("/api/auth/me")
    def me(request: Request):
        current = session(request)
        return {"authenticated": True, "auth_mode": settings.auth_mode,
                "profile": request.app.state.repository.profile(current.profile_id)}

    @app.post("/api/auth/logout", status_code=204)
    async def logout(request: Request):
        disposition = "unavailable"
        failed = False
        if current := request.app.state.bank_state.session(request.cookies.get(COOKIE)):
            disposition, failed = await revoke(request, current)
        result = (JSONResponse({"detail": "No se pudo confirmar el cierre completo de la sesión."},
                               status_code=503) if failed else Response(status_code=204))
        result.headers["X-Banking-Revoke"] = disposition
        result.delete_cookie(COOKIE, httponly=True, secure=settings.secure_cookie, samesite="strict", path="/")
        return result

    @app.get("/api/overview")
    def overview(request: Request, limit: int = Query(500, ge=1, le=500)):
        return request.app.state.repository.overview(session(request).profile_id, limit)

    @app.get("/api/transactions")
    def transactions(request: Request, product: str | None = Query(None, max_length=64),
                     status: str | None = Query(None, max_length=24), q: str | None = Query(None, max_length=200),
                     limit: int = Query(500, ge=1, le=500), offset: int = Query(0, ge=0, le=2_147_483_647),
                     month: str | None = Query(None, pattern=r"^\d{4}-(?:0[1-9]|1[0-2])$")):
        data = request.app.state.repository.overview(session(request).profile_id, limit,
                                                    product=product, status=status, q=q, offset=offset, month=month)
        return {"transactions": data["transactions"], "metadata": data["metadata"]}

    @app.get("/api/chat/status")
    def chat_status(request: Request):
        current = session(request)
        customer = request.app.state.repository.profile_customer(current.profile_id)
        if service := request.app.state.chat_service:
            return service.status(customer)
        return {"available": False, "mode": "unconfigured", "reason": "El asistente FLUJO aún no está conectado."}

    @app.get("/api/chat/history")
    def chat_history(request: Request):
        current = session(request)
        customer = request.app.state.repository.profile_customer(current.profile_id)
        service = request.app.state.chat_service
        if not service:
            return {"available": False, "messages": [], "active": False}
        from .chat import ChatError
        try:
            result = service.history(customer, current.id, current.expires_at)
            if request.app.state.dispute_factory is not None:
                result.update(request.app.state.dispute_factory.query_context(
                    service, customer, current.id, current.expires_at))
            return result
        except ChatError as exc:
            raise HTTPException(exc.status_code, exc.message) from None

    @app.post("/api/chat")
    @app.post("/api/chat/messages")
    async def chat(body: ChatBody, request: Request):
        current = session(request)
        repository = request.app.state.repository
        customer = repository.profile_customer(current.profile_id)
        service = request.app.state.chat_service
        if not service:
            raise HTTPException(503, "El asistente FLUJO aún no está conectado.")
        message = body.message.strip()
        public_selection = None
        minimized = None
        if not message:
            raise HTTPException(422, "Escribe un mensaje para el asistente.")
        if body.transaction_reference:
            if len(message) > 3600:
                raise HTTPException(422, "Acorta el mensaje a 3600 caracteres cuando selecciones un movimiento.")
            selected = repository.transaction(current.profile_id, body.transaction_reference)
            if not selected:
                raise HTTPException(404, "El movimiento seleccionado no está disponible.")
            public_selection = {k: selected[k] for k in ("reference", "occurred_at", "type", "amount", "currency", "status")}
            from datetime import datetime
            from decimal import Decimal
            from .language import MinimizedFacts
            status = str(selected["status"]).lower()
            try:
                minimized = MinimizedFacts(
                    datetime.fromisoformat(selected["occurred_at"].replace("Z", "+00:00")).date().isoformat(),
                    format(Decimal(str(selected["amount"])), ".2f"), selected["currency"],
                    (selected.get("merchant") or "").strip()[:80] or None,
                    status if status in {"approved", "pending", "reversed"} else "unknown")
            except (ValueError, TypeError):
                # A malformed display record cannot become language context.
                minimized = None
        try:
            workflow = (request.app.state.dispute_factory(repository, service, current.profile_id,
                        current.id, current.expires_at) if request.app.state.dispute_factory else None)
            if workflow is None and dispute_factory is None and bank_backend is None:
                if getattr(body, "query_scope_id", None) is not None:
                    raise HTTPException(422, render_action_error("invalid_action", body.language))
                return await service.send(customer, current.id, current.expires_at, message,
                    display_message=body.message.strip(), selection=public_selection,
                    facts=minimized, language=body.language)
            return await service.send(customer, current.id, current.expires_at, message,
                                      display_message=body.message.strip(), selection=public_selection,
                                      **({"query_scope_id": getattr(body, "query_scope_id", None)} if getattr(body, "query_scope_id", None) else {}),
                                      **({"workflow": workflow} if workflow is not None else {}))
        except Exception as exc:
            from .chat import ChatError
            if isinstance(exc, ChatError):
                raise HTTPException(exc.status_code, exc.message) from None
            logger.error("Banking chat unavailable: %s", type(exc).__name__)
            raise HTTPException(502, "FLUJO no pudo responder. Intenta nuevamente.") from None

    def render_action_result(result: dict, language: str):
        from .action import project_action_result, render_action
        query_id = result.get("query_id")
        result = project_action_result(result)
        if isinstance(query_id, str) and re.fullmatch(r"q_[a-f0-9]{32}", query_id):
            result["query_id"] = query_id
        if result.get("state") in {"preparing", "prepare_unverified"}:
            message = (
                ({"es": "Se agotó la recuperación segura. La solicitud sigue sin resolver y bloqueada. La referencia visible no avisa al equipo ni indica que alguien la haya tomado.",
                  "pt": "A recuperação segura se esgotou. A solicitação continua sem resolução e bloqueada. A referência visível não avisa a equipe nem indica que alguém assumiu o caso."}
                 if result.get("review_reference") else
                 {"es": "Se agotó la recuperación segura. La solicitud sigue sin resolver y bloqueada. Pide ayuda al equipo que te dio acceso a la demo.",
                  "pt": "A recuperação segura se esgotou. A solicitação continua sem resolução e bloqueada. Peça ajuda à equipe que lhe deu acesso à demonstração."})
                if result.get("recovery_exhausted") else
                {"es": "Se está verificando la solicitud para este movimiento. Consulta su estado antes de iniciar otra.",
                 "pt": "A solicitação deste lançamento está sendo verificada. Consulte o estado antes de iniciar outra."}
                if result["state"] == "preparing" else
                {"es": "No se pudo verificar la preparación de esta solicitud. Consulta su estado para recuperarla.",
                 "pt": "Não foi possível verificar a preparação desta solicitação. Consulte o estado para recuperá-la."})
            rendered = message[language]
            if result.get("prior_receipt"):
                if result.get("recovery_exhausted"):
                    rendered += (" La recepción simulada anterior sigue verificada; la preparación del seguimiento continúa sin verificar."
                                 if language == "es" else
                                 " A solicitação simulada anterior continua verificada; a preparação do acompanhamento permanece sem verificação.")
                else:
                    rendered = render_action(result, language)["message"]
            return {**result, "language": language, "message": rendered}
        rendered = render_action(result, language)
        if isinstance(query_id, str) and re.fullmatch(r"q_[a-f0-9]{32}", query_id):
            rendered["query_id"] = query_id
        return rendered

    async def run_action(request: Request, operation: dict, language: str,
                         target_reference: str | None = None, *, target_context: dict | None = None,
                         query_scope_id: str | None = None):
        current = session(request)
        customer = request.app.state.repository.profile_customer(current.profile_id)
        service = request.app.state.chat_service
        if not service:
            raise HTTPException(503, render_action_error("chat_unavailable", language))
        if query_scope_id is not None and dispute_factory is None and bank_backend is None:
            raise HTTPException(422, render_action_error("invalid_action", language))
        from .chat import ChatError
        try:
            context = ({"expected_snapshot": target_context["snapshot"],
                        "expected_transaction": target_context["transaction"]} if target_context else {})
            result = await service.action(customer, current.id, current.expires_at,
                                          operation, target_reference=target_reference,
                                          **({"query_scope_id": query_scope_id} if query_scope_id else {}), **context)
            return render_action_result(result, language)
        except ChatError as exc:
            raise HTTPException(exc.status_code, render_action_error(exc.code, language)) from None
        except ValueError:
            raise HTTPException(502, render_action_error("action_response_unverified", language)) from None

    @app.get("/api/action/status")
    async def action_status(request: Request, language: Literal["es", "pt"] = "es"):
        current = session(request)
        customer = request.app.state.repository.profile_customer(current.profile_id)
        service = request.app.state.chat_service
        if not service:
            raise HTTPException(503, render_action_error("chat_unavailable", language))
        from .chat import ChatError
        try:
            result = await service.action_status(customer, current.id, current.expires_at)
            return result if result.get("state") == "none" else render_action_result(result, language)
        except ChatError as exc:
            raise HTTPException(exc.status_code, render_action_error(exc.code, language)) from None
        except ValueError:
            raise HTTPException(502, render_action_error("action_status_unverified", language)) from None

    @app.post("/api/action/prepare")
    async def action_prepare(body: PrepareActionBody, request: Request):
        current = session(request)
        target = request.app.state.repository.action_target(current.profile_id, body.transaction_reference)
        if not target:
            raise HTTPException(404, render_action_error("action_target_unavailable", body.language))
        return await run_action(request, {"operation": "prepare", "transactionId": target["transaction_id"],
                                          "snapshot": target["snapshot"]},
                                body.language, body.transaction_reference, target_context=target,
                                query_scope_id=getattr(body, "query_scope_id", None))

    @app.post("/api/action/confirm")
    async def action_confirm(body: ConfirmActionBody, request: Request):
        current = session(request)
        target = request.app.state.repository.action_target(current.profile_id, body.transaction_reference)
        if not target:
            raise HTTPException(404, render_action_error("action_target_unavailable", body.language))
        return await run_action(request, {"operation": "confirm", "pendingHandle": body.pending_handle,
                                          "confirmed": body.confirmed}, body.language,
                                body.transaction_reference, target_context=target,
                                query_scope_id=getattr(body, "query_scope_id", None))

    @app.post("/api/action/handoff")
    async def action_handoff(body: HandoffActionBody, request: Request):
        questions = ({"unansweredQuestions": body.unanswered_questions}
                     if "unanswered_questions" in body.model_fields_set else {})
        if not body.pending_handle and body.reason not in {
                "out_of_policy", "emergency", "customer_request", "clarification_exhausted"}:
            raise HTTPException(409, render_action_error("handoff_mismatch", body.language))
        if body.pending_handle:
            if not body.transaction_reference:
                raise HTTPException(422, render_action_error("handoff_target_required", body.language))
            current = session(request)
            if not request.app.state.repository.action_target(current.profile_id, body.transaction_reference):
                raise HTTPException(404, render_action_error("action_target_unavailable", body.language))
            handed = await run_action(request, {"operation": "handoff", "reason": body.reason,
                "pendingHandle": body.pending_handle,
                **questions,
                **({"requestId": body.request_id} if body.request_id else {})},
                body.language, body.transaction_reference, query_scope_id=getattr(body, "query_scope_id", None))
            return handed
        if body.transaction_reference and not body.pending_handle:
            current = session(request)
            target = request.app.state.repository.action_target(current.profile_id, body.transaction_reference)
            if not target:
                raise HTTPException(404, render_action_error("action_target_unavailable", body.language))
            selected_scope = getattr(body, "query_scope_id", None)
            service = request.app.state.chat_service
            backend = getattr(service, "_bank_backend", None)
            if backend is not None:
                from .chat import ChatError
                try:
                    customer = request.app.state.repository.profile_customer(current.profile_id)
                    selected_scope = backend.query_scope(service, customer, current.id,
                        current.expires_at, body.transaction_reference, selected_scope)["query_id"]
                except ChatError as exc:
                    raise HTTPException(exc.status_code, render_action_error(exc.code, language)) from None
            previous = await action_status(request, body.language)
            same_target = (previous.get("target_reference") == body.transaction_reference
                           and previous.get("query_id") == selected_scope)
            if same_target and previous.get("state") == "handoff_verified":
                if ((previous.get("reason") or previous.get("handoff", {}).get("reason")) != body.reason
                        or ("unanswered_questions" in body.model_fields_set and
                            body.unanswered_questions != previous.get("handoff", {}).get("unanswered_questions"))
                        or (body.request_id is not None and body.request_id != previous.get("request_id"))):
                    raise HTTPException(409, render_action_error("handoff_previous_mismatch", body.language))
                return previous
            if same_target and previous.get("state") in {"preparing", "prepare_unverified",
                                                            "action_unverified"}:
                return previous
            if same_target and previous.get("state") in {"pending_confirmation", "existing_case_verified", "handoff_unverified"}:
                if (previous.get("state") == "handoff_unverified"
                        and previous.get("reason") != body.reason):
                    raise HTTPException(409, render_action_error("handoff_previous_mismatch", body.language))
                prepared = previous
            else:
                if previous.get("state") not in {"none", "intake_verified", "existing_case_verified", "handoff_verified"}:
                    raise HTTPException(409, render_action_error("action_in_progress", body.language))
                prepared = await run_action(request, {"operation": "prepare",
                    "transactionId": target["transaction_id"], "snapshot": target["snapshot"]},
                    body.language, body.transaction_reference, target_context=target,
                    query_scope_id=selected_scope)
                if prepared.get("state") not in {"pending_confirmation", "existing_case_verified"}:
                    return prepared
            pending = prepared.get("pending_handle")
            request_id = prepared.get("request_id")
            if (not isinstance(pending, str) or not isinstance(request_id, str)
                    or not re.fullmatch(r"[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}",
                                        request_id)):
                raise HTTPException(502, render_action_error("handoff_unverified", body.language))
            handed = await run_action(request, {"operation": "handoff", "reason": body.reason,
                "pendingHandle": pending, "requestId": request_id, **questions},
                body.language, body.transaction_reference, query_scope_id=selected_scope)
            if handed.get("state") == "handoff_unverified":
                handed["pending_handle"] = pending
            return handed
        handed = await run_action(request, {"operation": "handoff", "reason": body.reason,
                                            **questions,
                                            **({"pendingHandle": body.pending_handle} if body.pending_handle else {}),
                                            **({"requestId": body.request_id} if body.request_id else {})},
                                  body.language, query_scope_id=getattr(body, "query_scope_id", None))
        if handed.get("state") == "handoff_unverified" and body.pending_handle:
            handed["pending_handle"] = body.pending_handle
        return handed

    @app.get("/{path:path}")
    def frontend(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Ruta no disponible.")
        target = (settings.static_dir / path).resolve()
        if settings.static_dir in target.parents and target.is_file():
            return FileResponse(target)
        index = settings.static_dir / "index.html"
        if index.is_file():
            return FileResponse(index)
        return JSONResponse({"detail": "La interfaz todavía no ha sido compilada."}, status_code=503)

    return app


app = create_app()
