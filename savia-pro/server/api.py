"""Savia Pro - HTTP API over the serving snapshot."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db, reviews
from .config import WEB_DIST
from .security import (SessionError, issue_session, product_payload, read_session,
                       transaction_payload)

app = FastAPI(title="Savia Pro", version="1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(GZipMiddleware, minimum_size=900)
app.add_middleware(
    CORSMiddleware,
    # The dev server runs on another port; only loopback origins are allowed.
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


# --------------------------------------------------------------------------
# Session plumbing
# --------------------------------------------------------------------------

class Session(BaseModel):
    slug: str
    customer_id: str
    alias: str


def session(authorization: str | None = Header(default=None)) -> Session:
    try:
        slug = read_session(authorization)
    except SessionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    customer = db.customer_for_slug(slug)
    if not customer:
        raise HTTPException(status_code=401, detail="profile is no longer available")
    return Session(slug=slug, customer_id=customer["customer_id"], alias=customer["alias"])


# --------------------------------------------------------------------------
# Public
# --------------------------------------------------------------------------

@app.get("/api/health")
def health() -> dict[str, Any]:
    try:
        info = db.build_info()
    except db.ServingUnavailable as exc:
        return JSONResponse(status_code=503, content={"ok": False, "detail": str(exc)})
    return {"ok": True, "build_id": info.get("build_id"), "served_at": info.get("serving_built_at")}


@app.get("/api/snapshot")
def snapshot() -> dict[str, Any]:
    """Facts about the published snapshot. Contains no customer data."""
    info = db.build_info()
    stats = db.snapshot_stats()
    total = max(stats.get("transactions", 0), 1)
    return {
        "build": info,
        "totals": stats,
        "shares": {
            "no_merchant": round(stats.get("no_merchant", 0) / total, 6),
            "no_category": round(stats.get("no_category", 0) / total, 6),
            "next_day_event": round(stats.get("next_day_event", 0) / total, 6),
        },
    }


@app.get("/api/profiles")
def profiles() -> dict[str, Any]:
    """Demo profiles. No customer identifier is included by design."""
    return {"profiles": db.profiles()}


class SignIn(BaseModel):
    slug: str = Field(min_length=1, max_length=40)


@app.post("/api/session")
def sign_in(body: SignIn) -> dict[str, Any]:
    customer = db.customer_for_slug(body.slug)
    if not customer:
        raise HTTPException(status_code=404, detail="unknown profile")
    token = issue_session(body.slug)
    return {**token, "customer": {
        "alias": customer["alias"], "note": customer["note"], "city": customer["city"],
        "state": customer["state"], "country": customer["country"],
        "segment": customer["segment"], "status": customer["customer_status"],
        "customer_since": str(customer["registration_date"]),
    }}


# --------------------------------------------------------------------------
# Authenticated
# --------------------------------------------------------------------------

@app.get("/api/overview")
def overview(me: Session = Depends(session)) -> dict[str, Any]:
    cid = me.customer_id
    products = [product_payload(p) for p in db.products_for(cid)]
    stats = db.customer_stats(cid)
    currencies = db.currencies_for(cid)

    buckets: dict[str, dict[str, Any]] = {}
    for product in products:
        bucket = buckets.setdefault(product["currency"], {
            "currency": product["currency"], "deposit": 0.0, "credit": 0.0,
            "investment": 0.0, "credit_limit": 0.0, "products": 0})
        bucket[product["balance_kind"]] += product["balance"] or 0.0
        bucket["credit_limit"] += product["credit_limit"] or 0.0
        bucket["products"] += 1

    recent = db.transactions(cid, {"limit": 8, "sort": "date_desc"})
    return {
        "customer": {"alias": me.alias},
        "products": products,
        "balances": sorted(buckets.values(), key=lambda b: -b["products"]),
        "currencies": currencies,
        "series": {c: db.monthly_series(cid, c) for c in currencies},
        "recent": [transaction_payload(r) for r in recent["rows"]],
        "stats": {k: (int(v) if isinstance(v, (int, float)) else str(v))
                  for k, v in stats.items() if k != "customer_id"},
        "build": db.build_info(),
    }


def _filters(
    q: str | None = None, product: str | None = None, type: str | None = None,
    status: str | None = None, channel: str | None = None, currency: str | None = None,
    direction: str | None = None, category: str | None = None,
    date_from: str | None = None, date_to: str | None = None,
    min_amount: float | None = None, max_amount: float | None = None,
    flags: list[str] | None = Query(default=None),
    sort: str = "date_desc", offset: int = 0, limit: int = 40,
) -> dict[str, Any]:
    return dict(q=q, product=product, type=type, status=status, channel=channel,
                currency=currency, direction=direction, category=category,
                date_from=date_from, date_to=date_to, min_amount=min_amount,
                max_amount=max_amount, flags=flags, sort=sort, offset=offset, limit=limit)


@app.get("/api/transactions")
def ledger(me: Session = Depends(session), f: dict = Depends(_filters)) -> dict[str, Any]:
    page = db.transactions(me.customer_id, f)
    summary = page["summary"]
    return {
        "transactions": [transaction_payload(r) for r in page["rows"]],
        "matched": int(summary.get("matched") or 0),
        "total": page["total"],
        "offset": page["offset"],
        "limit": page["limit"],
        "next_offset": page["next_offset"],
        "sums": {
            "inflow": float(summary.get("inflow") or 0),
            "outflow": float(summary.get("outflow") or 0),
            "undetermined": float(summary.get("undetermined") or 0),
            "currencies": int(summary.get("currencies") or 0),
        },
    }


@app.get("/api/transactions/{reference}")
def detail(reference: str, me: Session = Depends(session)) -> dict[str, Any]:
    row = db.transaction(me.customer_id, reference)
    if not row:
        raise HTTPException(status_code=404, detail="no such transaction for this profile")
    related = db.neighbours(me.customer_id, row)
    product = next((p for p in db.products_for(me.customer_id)
                    if p["product_id"] == row["product_id"]), None)
    return {
        "transaction": transaction_payload(row),
        "product": product_payload(product) if product else None,
        "related": {key: [transaction_payload(r) for r in value]
                    for key, value in related.items()},
        "evidence": {"source": "serving_snapshot", "build_id": db.build_info().get("build_id")},
    }


@app.get("/api/insights")
def insights(currency: str | None = None, me: Session = Depends(session)) -> dict[str, Any]:
    cid = me.customer_id
    currencies = db.currencies_for(cid)
    chosen = currency if currency in currencies else (currencies[0] if currencies else None)
    stats = db.customer_stats(cid)
    total = max(int(stats.get("transactions") or 1), 1)

    def to_float(records, *keys):
        out = []
        for record in records:
            item = dict(record)
            for key in keys:
                if item.get(key) is not None:
                    item[key] = float(item[key])
            out.append(item)
        return out

    return {
        "currency": chosen,
        "currencies": currencies,
        "categories": to_float(db.category_totals(cid, chosen) if chosen else [], "total"),
        "merchants": to_float(db.top_merchants(cid, chosen) if chosen else [], "total"),
        "channels": db.channel_mix(cid),
        "repeat_merchants": to_float(db.repeat_merchants(cid),
                                     "min_amount", "max_amount", "avg_amount"),
        "series": db.monthly_series(cid, chosen) if chosen else [],
        "completeness": [
            {"metric": "no_merchant", "count": int(stats.get("no_merchant") or 0), "of": total},
            {"metric": "no_category", "count": int(stats.get("no_category") or 0), "of": total},
            {"metric": "next_day_event", "count": int(stats.get("next_day_event") or 0), "of": total},
            {"metric": "direction_unknown", "count": int(stats.get("direction_unknown") or 0), "of": total},
            {"metric": "unsettled", "count": int(stats.get("pending") or 0) + int(stats.get("reversed") or 0)
                                              + int(stats.get("declined") or 0), "of": total},
        ],
    }


@app.get("/api/signals")
def signals(me: Session = Depends(session)) -> dict[str, Any]:
    found, clear = [], []
    for signal in db.signals(me.customer_id):
        item = {"kind": signal["kind"], "count": signal["count"],
                "examples": [transaction_payload(r) for r in signal["examples"]]}
        (found if signal["count"] else clear).append(item)
    found.sort(key=lambda s: -s["count"])
    return {"found": found, "clear": clear}


@app.get("/api/export.csv")
def export(me: Session = Depends(session), f: dict = Depends(_filters)) -> Response:
    f = {**f, "limit": db.PAGE_LIMIT_MAX, "offset": 0}
    collected: list[dict[str, Any]] = []
    while True:
        page = db.transactions(me.customer_id, f)
        collected.extend(page["rows"])
        if page["next_offset"] is None:
            break
        f = {**f, "offset": page["next_offset"]}

    columns = ["reference", "event_date", "process_date", "date_gap_days", "type", "category",
               "amount", "currency", "direction", "status", "channel", "merchant",
               "product_type", "product_reference", "country", "city"]

    def cell(value: Any) -> str:
        text = "" if value is None else str(value)
        return '"' + text.replace('"', '""') + '"' if any(c in text for c in ',";\n') else text

    lines = [",".join(columns)]
    for row in collected:
        payload = transaction_payload(row)
        lines.append(",".join(cell(payload.get(c)) for c in columns))
    body = "\n".join(lines) + "\n"
    return PlainTextResponse(body, media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="savia-{me.slug}-movements.csv"'})


class ReviewRequest(BaseModel):
    reference: str
    reason: str = "unrecognised_charge"
    answers: dict[str, str] = Field(default_factory=dict)
    note: str = ""
    urgent: bool = False


@app.post("/api/reviews")
def open_review(body: ReviewRequest, me: Session = Depends(session)) -> dict[str, Any]:
    row = db.transaction(me.customer_id, body.reference)
    if not row:
        raise HTTPException(status_code=404, detail="no such transaction for this profile")
    record = reviews.create(
        profile_slug=me.slug, reason=body.reason, answers=body.answers, note=body.note,
        facts=transaction_payload(row), build_id=db.build_info().get("build_id", "unknown"),
        urgent=body.urgent)
    return {"review": record}


@app.get("/api/reviews")
def list_reviews(me: Session = Depends(session)) -> dict[str, Any]:
    return {"reviews": reviews.listing(me.slug)}


# --------------------------------------------------------------------------
# Built client
# --------------------------------------------------------------------------

if WEB_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> Response:
        candidate = (WEB_DIST / path).resolve()
        if path and candidate.is_file() and WEB_DIST.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(WEB_DIST / "index.html")
