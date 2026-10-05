"""Scoped stdio MCP for a generic FLUJO tool/automation connection.

Configuration is backend-only. One server binds one trusted inquiry owner;
tools cannot select owners, bank sessions, facts, credentials or models.
"""
import os
import hmac
import json
from pathlib import Path
from mcp.server.fastmcp import FastMCP

from .service import InquiryService


def configured_service():
    from .fleet import configured_fleet
    from dispute_workflow.model import FlujoModel
    mode = os.environ.get("SAVIA_INQUIRY_PROVIDER", "flujo")
    base = os.environ.get("SAVIA_INQUIRY_MODEL_URL", "http://localhost:43420")
    model_id = os.environ.get("SAVIA_INQUIRY_MODEL_ID", "model-GPT-6 Luna")
    token = os.environ.get("SAVIA_INQUIRY_MODEL_TOKEN")
    if mode == "openrouter":
        model = FlujoModel("https://openrouter.ai", "model-provider-adapter", token, timeout=30)
        model.base_url, model.model_id = "https://openrouter.ai/api", model_id
    elif mode == "flujo":
        model = FlujoModel(base, model_id, token, timeout=30)
    else:
        raise ValueError("explicit_provider_required")
    fleet_config = {}
    if filename := os.environ.get("BANKING_CONFIG_FILE"):
        configured = json.loads(Path(filename).read_text(encoding="utf-8-sig"))
        fleet_config = configured.get("inquiries", {})
    return InquiryService(os.environ["SAVIA_INQUIRY_STATE_DIR"], model=model,
                          fleet=configured_fleet(fleet_config))


def main():
    service = configured_service()
    owner = os.environ["SAVIA_INQUIRY_OWNER"]
    if len(owner) != 64 or any(c not in "abcdef0123456789" for c in owner):
        raise ValueError("trusted_owner_required")
    transport = os.environ.get("SAVIA_INQUIRY_MCP_TRANSPORT", "stdio")
    from mcp.server.transport_security import TransportSecuritySettings
    mcp = FastMCP("Savia informational inquiry", host="127.0.0.1",
        port=int(os.environ.get("SAVIA_INQUIRY_MCP_PORT", "43952")), stateless_http=True, json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*", "host.docker.internal:*"],
            allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://host.docker.internal:*"]))

    @mcp.tool()
    def savia_inquiry_status(language: str = "es") -> dict:
        """Read only this configured owner's informational cases and events."""
        return service.list(owner, language)

    @mcp.tool()
    async def savia_inquiry_tick() -> dict:
        """Run one due scoped inquiry team/follow-up pass; no banking operations.

        Invoke from a generic FLUJO scheduled flow. Unchanged follow-ups do not
        append events. Bootstrap teams make two bounded concurrent model calls;
        an explicitly bound recovered fleet uses the original submit/status path.
        """
        await service.check(owner=owner)
        return {"provider": os.environ.get("SAVIA_INQUIRY_PROVIDER", "flujo"),
                "bank_authority": False, **service.list(owner)}

    if transport == "stdio":
        mcp.run(transport="stdio")
    elif transport == "streamable-http":
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import JSONResponse
        import uvicorn
        token = os.environ["SAVIA_INQUIRY_MCP_TOKEN"]
        if len(token) < 32:
            raise ValueError("backend_token_required")
        class Authentication(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                if not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer "+token):
                    return JSONResponse({"error":"unauthorized"}, status_code=401)
                return await call_next(request)
        app = mcp.streamable_http_app()
        app.add_middleware(Authentication)
        uvicorn.run(app, host="127.0.0.1", port=mcp.settings.port, log_level="warning", access_log=False)
    else:
        raise ValueError("unsupported_transport")


if __name__ == "__main__":
    main()
