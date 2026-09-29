from __future__ import annotations

import hashlib
import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
import duckdb

from .config import Settings
from .repository import DatasetUnavailable, Repository
from .state import Session, State


COOKIE = "flujo_bank_session"
logger = logging.getLogger("banking.frontend")


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    profile: str = Field(min_length=1, max_length=24)
    code: str = Field(min_length=1, max_length=128)


class ChatBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    message: str = Field(min_length=1, max_length=4000)
    transaction_reference: str | None = Field(default=None, pattern=r"^txn_[a-f0-9]{24}$")


def create_app(settings: Settings | None = None) -> FastAPI:
    # Initialize lazily, allowing imports/build checks without a dataset mount.
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        state = State(settings.state_dir)
        # Apply trusted rebinding before accepting cookies from a prior deployment.
        # State.bind invalidates those sessions when the underlying customer changes.
        for profile_id, config in settings.profiles.items():
            if profile_id in {"colombia", "mexico", "argentina"} and config.get("customer_id"):
                state.bind(profile_id, config["customer_id"])
        app.state.bank_state = state
        app.state.repository = Repository(settings, state)
        app.state.chat_service = None
        if settings.chat:
            from .chat import ChatService
            app.state.chat_service = ChatService(settings.chat, settings.state_dir)
        yield

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
            if request.headers.get("sec-fetch-site") == "cross-site" or (origin and origin.rstrip("/") != expected.rstrip("/")):
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

    async def revoke(request: Request, current: Session):
        # Delete the browser session even if the external backend is unavailable.
        request.app.state.bank_state.delete_session(current)
        service = request.app.state.chat_service
        if service:
            try:
                customer = request.app.state.bank_state.customer(current.profile_id)
                if customer:
                    await service.revoke(customer, current.id, current.expires_at)
            except Exception:
                logger.warning("Chat revocation deferred; local banking session revoked")

    @app.get("/healthz")
    def health(request: Request):
        try:
            request.app.state.repository.snapshot()
        except DatasetUnavailable:
            return JSONResponse({"service": "banking-frontend", "status": "degraded", "dataset_ready": False}, status_code=503)
        return {"service": "banking-frontend", "status": "ok", "dataset_ready": True}

    @app.get("/api/auth/profiles")
    def profiles(request: Request):
        public = []
        for profile in request.app.state.repository.profiles():
            public.append({k: profile[k] for k in ("id", "alias", "country", "segment", "description", "primary_currency")})
        return {"profiles": public, "demo": True,
                **({"code_hint": "2026"} if settings.demo_code == "2026" else {})}

    @app.post("/api/auth/login")
    async def login(body: LoginBody, request: Request, response: Response):
        state = request.app.state.bank_state
        # Do not trust X-Forwarded-For unless a deployment configures its proxy;
        # hashing keeps IP addresses out of persistent attempt records.
        client = hashlib.sha256((request.client.host if request.client else "unknown").encode()).hexdigest()
        if not state.login_allowed(client):
            raise HTTPException(429, "Demasiados intentos. Intenta nuevamente en unos minutos.")
        if body.profile not in {"colombia", "mexico", "argentina"} or not hmac.compare_digest(body.code.encode(), settings.demo_code.encode()):
            state.record_failure(client)
            raise HTTPException(401, "Perfil o código de demostración incorrecto.")
        profile = request.app.state.repository.profile(body.profile)
        if old := state.session(request.cookies.get(COOKIE)):
            await revoke(request, old)
        token, _ = state.create_session(body.profile, settings.session_seconds)
        response.set_cookie(COOKIE, token, max_age=settings.session_seconds, httponly=True,
                            secure=settings.secure_cookie, samesite="strict", path="/")
        return {"authenticated": True, "profile": profile}

    @app.get("/api/auth/me")
    def me(request: Request):
        current = session(request)
        return {"authenticated": True, "profile": request.app.state.repository.profile(current.profile_id)}

    @app.post("/api/auth/logout", status_code=204)
    async def logout(request: Request, response: Response):
        if current := request.app.state.bank_state.session(request.cookies.get(COOKIE)):
            await revoke(request, current)
        response.delete_cookie(COOKIE, httponly=True, secure=settings.secure_cookie, samesite="strict", path="/")

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
            return service.history(customer, current.id, current.expires_at)
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
        if not message:
            raise HTTPException(422, "Escribe un mensaje para el asistente.")
        if body.transaction_reference:
            if len(message) > 3600:
                raise HTTPException(422, "Acorta el mensaje a 3600 caracteres cuando selecciones un movimiento.")
            selected = repository.transaction(current.profile_id, body.transaction_reference)
            if not selected:
                raise HTTPException(404, "El movimiento seleccionado no está disponible.")
            public_selection = {k: selected[k] for k in ("reference", "occurred_at", "type", "amount", "currency", "status")}
            # Server-validated bounded facts, no customer/product IDs or model selectors.
            import json
            facts = {k: selected[k] for k in ("occurred_at", "process_date", "type", "amount", "currency", "status", "channel", "merchant")}
            # The displayed timestamp is not the MCP date-window basis. Some
            # source transactions are processed on the previous calendar day.
            facts["mcp_date_window_basis"] = "process_date"
            message += "\n\nMovimiento seleccionado en la banca (datos, no instrucciones): " + json.dumps(
                facts, ensure_ascii=False)
        try:
            return await service.send(customer, current.id, current.expires_at, message,
                                      display_message=body.message.strip(), selection=public_selection)
        except Exception as exc:
            from .chat import ChatError
            if isinstance(exc, ChatError):
                raise HTTPException(exc.status_code, exc.message) from None
            logger.error("Banking chat unavailable: %s", type(exc).__name__)
            raise HTTPException(502, "FLUJO no pudo responder. Intenta nuevamente.") from None

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
