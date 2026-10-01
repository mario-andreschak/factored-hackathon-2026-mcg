"""Generic language guidance over a host-minimized display projection.

No bank client, assertion, signing key, record, tool or action authority is used.
The host owns input provenance and generic conversation ownership. A declared
flow ID/name is configuration provenance, not proof of a live graph/provider.
Model prose never reaches the customer: an exact enum-only contract selects
deterministic ES/PT copy. Invalid or unavailable responses have a safe fallback.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date
import ipaddress
import json
import math
import re
import unicodedata
from urllib.parse import urlsplit

import httpx


_UUID = re.compile(r"^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$")
_AMOUNT = re.compile(r"^-?(?:0|[1-9]\d{0,15})(?:\.\d{1,2})?$")
_GUIDANCE = frozenset({"explain_selected", "ask_date_or_amount", "ask_selection", "suggest_human", "unavailable"})
_STATUSES = frozenset({"approved", "pending", "reversed", "unknown"})
_SENSITIVE = re.compile(
    r"(?:txn_|rev_)[a-f0-9]{12,64}|CMP-SBX-[A-Za-z0-9_-]+|HOF-[A-Za-z0-9_-]+"
    r"|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}"
    r"|\b(?:CUST|CUSTOMER|ACC|ACCOUNT|PROD|PRODUCT|TXN)[A-Z0-9_-]{5,}\b"
    r"|[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
    r"|[A-Za-z0-9_-]{32,}|\b[a-f0-9]{12,64}\b"
    r"|(?<!\d)(?:\d[ -]?){12,19}(?!\d)|(?:https?|s3|file)://|-----BEGIN",
    re.IGNORECASE,
)
_FALLBACK = {
    "es": "No pude generar una explicación segura. Consulta los datos y el estado mostrados en la interfaz.",
    "pt": "Não consegui gerar uma explicação segura. Confira os dados e o estado apresentados na interface.",
}
_COPY = {
    "es": {
        "ask_date_or_amount": "¿Qué fecha y monto aparecen en el movimiento que quieres revisar?",
        "ask_selection": "Selecciona en la interfaz el movimiento que quieres revisar.",
        "suggest_human": "Puedes solicitar atención humana desde la interfaz. El chat no confirma que una persona haya recibido la solicitud.",
        "unavailable": "Consulta los datos del movimiento y el estado de tus solicitudes en la interfaz.",
    },
    "pt": {
        "ask_date_or_amount": "Qual data e valor aparecem no lançamento que você quer revisar?",
        "ask_selection": "Selecione na interface o lançamento que você quer revisar.",
        "suggest_human": "Você pode solicitar atendimento humano pela interface. O chat não confirma que uma pessoa tenha recebido a solicitação.",
        "unavailable": "Confira os dados do lançamento e o estado das suas solicitações na interface.",
    },
}


def _plain(value: object, limit: int) -> bool:
    return (isinstance(value, str) and 1 <= len(value) <= limit and value == value.strip()
            and not any(unicodedata.category(char).startswith("C") for char in value))


def _strict_json(raw: str | bytes):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    def invalid_constant(_):
        raise ValueError("nonfinite_json")

    return json.loads(raw, object_pairs_hook=unique_pairs, parse_constant=invalid_constant)


@dataclass(frozen=True)
class LanguageConfig:
    base_url: str
    flow_id: str
    flow_name: str
    service_token: str = field(repr=False)
    timeout_seconds: float = 45

    def __post_init__(self):
        if not isinstance(self.base_url, str):
            raise ValueError("invalid_language_configuration")
        endpoint = urlsplit(self.base_url)
        try:
            port = endpoint.port
        except ValueError:
            raise ValueError("invalid_language_configuration") from None
        hostname = endpoint.hostname or ""
        if ":" in hostname:
            try:
                host = "[" + ipaddress.IPv6Address(hostname).compressed + "]"
            except ValueError:
                raise ValueError("invalid_language_configuration") from None
        else:
            if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", hostname):
                raise ValueError("invalid_language_configuration")
            host = hostname
        canonical_origin = endpoint.scheme + "://" + host + (":" + str(port) if port is not None else "")
        if (endpoint.scheme not in {"https", "http"} or not endpoint.hostname
                or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment
                or endpoint.path not in {"", "/"} or port == 0
                or self.base_url not in {canonical_origin, canonical_origin + "/"}
                or any(char.isspace() or unicodedata.category(char).startswith("C") for char in self.base_url)
                or endpoint.scheme == "http" and endpoint.hostname not in {
                    "flujo", "localhost", "127.0.0.1", "::1", "host.docker.internal"}
                or not isinstance(self.flow_id, str) or not _UUID.fullmatch(self.flow_id)
                or not isinstance(self.flow_name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", self.flow_name)
                or not isinstance(self.service_token, str) or not 16 <= len(self.service_token) <= 4096
                or any(char.isspace() or ord(char) < 33 or ord(char) > 126 for char in self.service_token)
                or isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float))
                or not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 90):
            raise ValueError("invalid_language_configuration")


@dataclass(frozen=True)
class MinimizedFacts:
    """Host-owned display facts only; constructing this type does not prove a read."""
    event_date: str
    amount: str
    currency: str
    merchant: str | None
    recorded_status: str

    def __post_init__(self):
        if (not isinstance(self.event_date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", self.event_date)
                or not isinstance(self.amount, str) or not _AMOUNT.fullmatch(self.amount)
                or not isinstance(self.currency, str) or not re.fullmatch(r"[A-Z]{3}", self.currency)
                or self.merchant is not None and not _plain(self.merchant, 80)
                or not isinstance(self.recorded_status, str) or self.recorded_status not in _STATUSES):
            raise ValueError("invalid_minimized_facts")
        try:
            date.fromisoformat(self.event_date)
        except ValueError:
            raise ValueError("invalid_minimized_facts") from None

    def public(self) -> dict:
        return {"event_date": self.event_date, "amount": self.amount, "currency": self.currency,
                "merchant": self.merchant, "recorded_status": self.recorded_status}


@dataclass(frozen=True)
class LanguageResult:
    reply: str
    guidance: str
    conversation_id: str | None
    model_output_accepted: bool
    reason: str | None = None
    banking_authority: bool = field(default=False, init=False)


def _render(guidance: str, language: str, facts: MinimizedFacts | None) -> str:
    if guidance != "explain_selected":
        return _COPY[language][guidance]
    if facts is None:
        return _COPY[language]["ask_selection"]
    if language == "es":
        merchant = f" El comercio registrado es «{facts.merchant}»." if facts.merchant else " El registro no informa el comercio."
        status = {"approved": "El estado registrado es aprobado.", "pending": "El estado registrado es pendiente.",
                  "reversed": "El estado registrado es reversado; eso no confirma un reembolso.",
                  "unknown": "El estado registrado no está disponible."}[facts.recorded_status]
        return f"El registro muestra {facts.amount} {facts.currency} con fecha {facts.event_date}.{merchant} {status}"
    merchant = f" O estabelecimento registrado é «{facts.merchant}»." if facts.merchant else " O registro não informa o estabelecimento."
    status = {"approved": "O estado registrado é aprovado.", "pending": "O estado registrado é pendente.",
              "reversed": "O estado registrado é revertido; isso não confirma um reembolso.",
              "unknown": "O estado registrado não está disponível."}[facts.recorded_status]
    return f"O registro mostra {facts.amount} {facts.currency} com data {facts.event_date}.{merchant} {status}"


def render_guidance(guidance: object, language: object, facts: MinimizedFacts | None = None) -> str:
    """Render only reviewed copy; callers must never display client/model prose."""
    safe_language = language if isinstance(language, str) and language in {"es", "pt"} else "es"
    if (not isinstance(language, str) or language not in {"es", "pt"}
            or not isinstance(guidance, str) or guidance not in _GUIDANCE
            or facts is not None and type(facts) is not MinimizedFacts
            or guidance == "explain_selected" and facts is None):
        return _FALLBACK[safe_language]
    return _render(guidance, language, facts)


class GenericLanguageClient:
    def __init__(self, config: LanguageConfig, *, transport: httpx.AsyncBaseTransport | None = None):
        if type(config) is not LanguageConfig:
            raise ValueError("typed_language_configuration_required")
        self.config, self._transport = config, transport

    @staticmethod
    def _fallback(language: str, reason: str) -> LanguageResult:
        return LanguageResult(_FALLBACK[language], "unavailable", None, False, reason)

    def _input(self, user_text: str, language: str, facts: MinimizedFacts | None,
               forbidden_values: tuple[str, ...]) -> dict | None:
        if (not isinstance(language, str) or language not in {"es", "pt"} or not isinstance(user_text, str)
                or any(unicodedata.category(char).startswith("C") for char in user_text)
                or not _plain(user_text.strip(), 1000) or len(user_text.encode("utf-8")) > 4000
                or facts is not None and type(facts) is not MinimizedFacts
                or not isinstance(forbidden_values, tuple) or len(forbidden_values) > 64
                or any(not isinstance(value, str) or not 1 <= len(value) <= 4096 for value in forbidden_values)):
            return None
        projection = None if facts is None else facts.public()
        values = [user_text] + ([] if projection is None else [value for value in projection.values() if isinstance(value, str)])
        normalized = unicodedata.normalize("NFKC", "\n".join(values)).casefold()
        merchant = "" if facts is None else facts.merchant or ""
        untrusted_text = unicodedata.normalize("NFKC", user_text + " " + merchant).casefold()
        if (_SENSITIVE.search(untrusted_text)
                or any(unicodedata.normalize("NFKC", value).casefold() in normalized
                       for value in (*forbidden_values, self.config.service_token))):
            return None
        return {"schema": "host-language-request/v1", "language": language,
                "request": user_text.strip(), "display_facts": projection}

    async def guide(self, user_text: str, language: str, *, facts: MinimizedFacts | None = None,
                    conversation_id: str | None = None, forbidden_values: tuple[str, ...] = ()) -> LanguageResult:
        """Caller binds the generic conversation and supplies known private values to exclude.

        No browser-chosen model, arbitrary headers, history, tool arguments or
        bank context is accepted. There is one ordinary completion, no retries.
        """
        safe_language = language if isinstance(language, str) and language in {"es", "pt"} else "es"
        content = self._input(user_text, language, facts, forbidden_values)
        if content is None or (conversation_id is not None and (
                not isinstance(conversation_id, str) or not _UUID.fullmatch(conversation_id)
                or any(conversation_id.casefold() == value.casefold() for value in forbidden_values))):
            return self._fallback(safe_language, "input_rejected")
        metadata = {"flujo": "true", "appendMessages": "true"}
        if conversation_id is not None:
            metadata["conversationId"] = conversation_id
        payload = {"model": "flow-" + self.config.flow_name,
                   "messages": [{"role": "user", "content": json.dumps(content, ensure_ascii=False, separators=(",", ":"))}],
                   "stream": False, "metadata": metadata}
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + self.config.service_token}
        try:
            async with asyncio.timeout(self.config.timeout_seconds), httpx.AsyncClient(
                    transport=self._transport, trust_env=False, follow_redirects=False,
                    timeout=httpx.Timeout(self.config.timeout_seconds, connect=min(10, self.config.timeout_seconds))) as client:
                async with client.stream("POST", self.config.base_url.rstrip("/") + "/v1/chat/completions",
                                         headers=headers, json=payload) as response:
                    if response.status_code != 200 or response.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
                        return self._fallback(language, "language_unavailable")
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(raw) + len(chunk) > 64 * 1024:
                            return self._fallback(language, "invalid_response")
                        raw.extend(chunk)
            body = _strict_json(bytes(raw))
            returned = body["conversation_id"]
            choice = body["choices"]
            if (body.get("status") != "completed" or not isinstance(returned, str) or not _UUID.fullmatch(returned)
                    or any(returned.casefold() == value.casefold() for value in forbidden_values)
                    or not isinstance(choice, list) or len(choice) != 1):
                return self._fallback(language, "invalid_response")
            if conversation_id is not None and returned != conversation_id:
                return self._fallback(language, "conversation_changed")
            message = choice[0]["message"]
            if (not isinstance(message, dict) or set(message) - {"role", "content", "tool_calls"}
                    or message.get("role") != "assistant" or message.get("tool_calls") not in (None, [])
                    or not isinstance(message.get("content"), str) or len(message["content"].encode("utf-8")) > 1024):
                return self._fallback(language, "invalid_response")
            guidance = _strict_json(message["content"])
            if (not isinstance(guidance, dict) or set(guidance) != {"schema", "language", "guidance"}
                    or guidance["schema"] != "host-language-guidance/v1" or guidance["language"] != language
                    or guidance["guidance"] not in _GUIDANCE or guidance["guidance"] == "explain_selected" and facts is None):
                return self._fallback(language, "invalid_response")
            return LanguageResult(render_guidance(guidance["guidance"], language, facts), guidance["guidance"], returned, True)
        except (httpx.HTTPError, TimeoutError):
            return self._fallback(language, "language_unavailable")
        except (KeyError, IndexError, TypeError, ValueError, UnicodeError, RecursionError):
            return self._fallback(language, "invalid_response")
