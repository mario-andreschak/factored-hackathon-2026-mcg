"""Owner authentication for the private hosted control plane."""
from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import time

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field


TOKEN_ENV = "SAVIA_WHATSAPP_OPERATOR_TOKEN"
SESSION_SECONDS = 8 * 60 * 60


class Login(BaseModel):
    token: str = Field(max_length=256)


class OperatorAuth:
    def __init__(self, enabled: bool):
        self.enabled = enabled
        self._sessions: dict[str, float] = {}
        self._token = os.environ.get(TOKEN_ENV, "") if enabled else ""
        if enabled and not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", self._token):
            raise ValueError(f"Private hosted control requires {TOKEN_ENV} with 32–256 URL-safe characters")

    def _matches(self, candidate: str) -> bool:
        return bool(isinstance(candidate, str) and candidate.isascii()
                    and hmac.compare_digest(candidate, self._token))

    def _now(self) -> float:
        return time.monotonic()

    def _authorized(self, request: Request) -> bool:
        authorization = request.headers.get("authorization", "")
        if authorization.startswith("Bearer ") and self._matches(authorization[7:]):
            return True
        now = self._now()
        self._sessions = {key: expiry for key, expiry in self._sessions.items() if expiry > now}
        session = authorization[7:] if authorization.startswith("Bearer ") else ""
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", session):
            return False
        return hashlib.sha256(session.encode("ascii")).hexdigest() in self._sessions

    def install(self, app):
        if not self.enabled:
            return

        @app.middleware("http")
        async def require_operator(request: Request, call_next):
            # The static login page contains no account or runtime information.
            # Host/Origin validation still applies through the existing middleware.
            if request.url.path != "/login" and not self._authorized(request):
                if request.url.path == "/" and request.method == "GET":
                    return RedirectResponse("/login", status_code=303)
                return JSONResponse({"detail": "Operator authentication required"}, status_code=401,
                                    headers={"Cache-Control": "no-store", "WWW-Authenticate": "Bearer"})
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            return response

        @app.get("/login")
        async def login_page():
            return FileResponse(Path(__file__).with_name("control.html"))

        @app.post("/login")
        async def login(body: Login):
            if not self._matches(body.token):
                raise HTTPException(401, "Invalid operator token")
            now = self._now()
            self._sessions = {key: expiry for key, expiry in self._sessions.items() if expiry > now}
            if len(self._sessions) >= 32:
                del self._sessions[min(self._sessions, key=self._sessions.get)]
            session = secrets.token_urlsafe(32)
            self._sessions[hashlib.sha256(session.encode("ascii")).hexdigest()] = now + SESSION_SECONDS
            # A cookie for localhost would also reach other localhost ports.
            # Page memory and explicit headers avoid ambient cross-port secrets.
            return JSONResponse({"authenticated": True, "access_token": session})

        @app.post("/logout")
        async def logout(request: Request):
            authorization = request.headers.get("authorization", "")
            session = authorization[7:] if authorization.startswith("Bearer ") else ""
            self._sessions.pop(hashlib.sha256(session.encode("utf-8")).hexdigest(), None)
            return JSONResponse({"authenticated": False})
