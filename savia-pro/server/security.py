"""Savia Pro - sessions, and the single place where rows become JSON.

Two rules are enforced here rather than trusted elsewhere:

1. The browser never learns a customer identifier. The client holds a signed
   token carrying a profile slug; the slug is resolved to a customer id on the
   server for the duration of one request.

2. A transaction row is serialised through an explicit field map. Adding a
   column to the serving database cannot silently publish it, and the fraud
   columns are not in the map at all.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from .config import SESSION_KEY, SESSION_TTL_SECONDS


class SessionError(Exception):
    """Raised when a token is absent, malformed, re-signed or expired."""


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue_session(slug: str) -> dict[str, Any]:
    expires = int(time.time()) + SESSION_TTL_SECONDS
    payload = json.dumps({"slug": slug, "exp": expires}, separators=(",", ":")).encode()
    body = _b64(payload)
    signature = _b64(hmac.new(SESSION_KEY, body.encode(), hashlib.sha256).digest())
    return {"token": f"{body}.{signature}", "expires_at": expires}


def read_session(header: str | None) -> str:
    """Returns the profile slug carried by a valid Authorization header."""
    if not header:
        raise SessionError("no session")
    token = header[7:].strip() if header.lower().startswith("bearer ") else header.strip()
    if token.count(".") != 1:
        raise SessionError("malformed session")
    body, signature = token.split(".")
    expected = _b64(hmac.new(SESSION_KEY, body.encode(), hashlib.sha256).digest())
    # Constant-time compare: a timing oracle on the signature would let a
    # caller forge a slug, which is the only authorisation this demo has.
    if not hmac.compare_digest(signature, expected):
        raise SessionError("bad signature")
    try:
        payload = json.loads(_unb64(body))
    except Exception as exc:  # pragma: no cover - malformed base64/json
        raise SessionError("unreadable session") from exc
    if int(payload.get("exp", 0)) < time.time():
        raise SessionError("session expired")
    slug = payload.get("slug")
    if not isinstance(slug, str) or not slug:
        raise SessionError("session carries no profile")
    return slug


# --------------------------------------------------------------------------
# Row serialisation
# --------------------------------------------------------------------------

def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _money(value: Any) -> Any:
    return None if value is None else round(float(value), 2)


# key in the API payload -> (column in the serving row, converter)
TRANSACTION_FIELDS: dict[str, tuple[str, Any]] = {
    "reference": ("transaction_id", str),
    "product_reference": ("product_id", str),
    "occurred_at": ("transaction_date", _iso),
    "event_date": ("event_date", _iso),
    "process_date": ("process_date", _iso),
    "date_gap_days": ("date_gap_days", lambda v: int(v) if v is not None else None),
    "type": ("transaction_type", str),
    "category": ("transaction_category", lambda v: v),
    "amount": ("amount", _money),
    "currency": ("currency", str),
    "amount_usd": ("amount_usd", _money),
    "channel": ("channel", str),
    "merchant": ("merchant_name", lambda v: v),
    "merchant_category": ("merchant_category", lambda v: v),
    "country": ("transaction_country", lambda v: v),
    "city": ("transaction_city", lambda v: v),
    "status": ("transaction_status", str),
    "response_code": ("response_code", lambda v: v),
    "direction": ("direction", str),
    "settled": ("is_settled", bool),
    "merchant_missing": ("merchant_missing", bool),
    "currency_differs_from_product": ("currency_differs_from_product", bool),
    "product_type": ("product_type", lambda v: v),
    "product_status": ("product_status", lambda v: v),
    "product_currency": ("product_currency", lambda v: v),
}

PRODUCT_FIELDS: dict[str, tuple[str, Any]] = {
    "reference": ("product_id", str),
    "type": ("product_type", str),
    "currency": ("currency", str),
    "balance": ("current_balance", _money),
    "credit_limit": ("credit_limit", _money),
    "interest_rate": ("interest_rate", lambda v: None if v is None else float(v)),
    "opened_at": ("opening_date", _iso),
    "expires_at": ("expiration_date", _iso),
    "status": ("product_status", str),
    "opened_channel": ("opening_channel", lambda v: v),
    "linked_app": ("has_linked_app", lambda v: None if v is None else bool(v)),
    "days_past_due": ("days_past_due", lambda v: None if v is None else int(v)),
    "last_transaction_at": ("last_transaction_date", _iso),
}

# Never serialise these, whatever the caller asks for.
NEVER_SERIALISE = frozenset({
    "customer_id", "is_fraud", "fraud_score", "_row_hash", "_source_file",
    "_run_id", "_partition_date", "_ingested_at", "ownership_valid",
    "_owner_mismatch_product_id", "_fk_customer_id_missing", "_fk_product_id_missing",
})


def project(row: dict[str, Any], fields: dict[str, tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, (column, convert) in fields.items():
        if key in NEVER_SERIALISE or column in NEVER_SERIALISE:
            continue
        value = row.get(column)
        out[key] = None if value is None else convert(value)
    return out


def transaction_payload(row: dict[str, Any]) -> dict[str, Any]:
    return project(row, TRANSACTION_FIELDS)


def product_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = project(row, PRODUCT_FIELDS)
    # A credit line is reported as "used", a deposit or investment as "held".
    kind = {"Tarjeta Crédito": "credit", "Préstamo Personal": "credit",
            "Préstamo Hipotecario": "credit", "Inversión": "investment"}
    payload["balance_kind"] = kind.get(payload["type"], "deposit")
    if payload["balance_kind"] == "credit" and payload["credit_limit"]:
        payload["available"] = round(payload["credit_limit"] - (payload["balance"] or 0), 2)
    else:
        payload["available"] = None
    masked = payload["reference"][-4:] if payload["reference"] else "????"
    payload["masked"] = f"•••• {masked}"
    return payload
