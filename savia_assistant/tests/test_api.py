from types import SimpleNamespace
import asyncio
import json

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from savia_assistant import InquiryService
from savia_assistant.api import install_routes


def test_cookie_auth_stable_owner_server_projection_and_explicit_resolution(tmp_path):
    calls = []
    async def model(stage, system, user):
        calls.append(json.loads(user))
        return json.dumps({"suggestion":"review_date_amount" if stage.endswith("evidence") else "await_bank"})
    service = InquiryService(tmp_path, model)
    app = FastAPI()
    app.state.inquiries = service
    app.state.bank_state = SimpleNamespace(secret=b"a"*32)
    selected = {"reference":"txn_"+"f"*24,"occurred_at":"2026-10-04T00:00:00Z", "amount":"25", "currency":"USD", "merchant":"Café ficticio", "status":"approved", "private_customer":"never send"}
    app.state.repository = SimpleNamespace(profile_customer=lambda p:p, transaction=lambda p,r:selected if p=="alice" and r==selected["reference"] else None)
    def authenticate(request):
        token = request.cookies.get("login")
        if token not in {"alice-old","alice-renewed","bob"}:
            raise HTTPException(401)
        return SimpleNamespace(profile_id="bob" if token=="bob" else "alice",id=token,expires_at=9999999999)
    install_routes(app, authenticate)
    with TestClient(app) as client:
        assert client.get("/api/assistant/cases").status_code == 401
        client.cookies.set("login","alice-old")
        assert client.post("/api/assistant/cases",json={"message":"Ayuda","facts":selected}).status_code==422
        created = client.post("/api/assistant/cases",json={"message":"No reconozco el cargo", "transaction_reference":selected["reference"]})
        assert created.status_code == 202
        case = created.json()["id"]
        first = client.get("/api/assistant/voice-update", params={"case_id":case}).json()
        assert first["mode"] == "assistant" and first["inquiry_state"] == "queued"
        assert client.get("/api/assistant/voice-update", params={"case_id":case,"after_event_id":first["event_id"]}).status_code==204
        asyncio.run(service.check())
        spoken = client.get("/api/assistant/voice-update", params={"case_id":case,"after_event_id":first["event_id"]}).json()
        assert spoken["event_id"] > first["event_id"] and "Compara" in spoken["reply"]
        embedded = client.get("/api/assistant/cases").json()["items"][0]["voice_update"]
        assert all(spoken[k] == embedded[k] for k in ("version","reply","mode","status"))
        assert selected["reference"] not in json.dumps(spoken) and case not in spoken["reply"]
        assert len(calls)==2 and all(set(c["display_facts"])=={"event_date","amount","currency","merchant","recorded_status"} for c in calls)
        assert all("never send" not in json.dumps(c) and selected["reference"] not in json.dumps(c) for c in calls)
        client.cookies.set("login","bob")
        assert client.get("/api/assistant/cases").json()=={"items":[]}
        assert client.get("/api/assistant/voice-update",params={"case_id":case}).status_code==404
        assert client.post(f"/api/assistant/cases/{case}/resolve",json={"resolved":True}).status_code==404
        assert client.post("/api/assistant/cases",json={"message":"Ayuda", "transaction_reference":selected["reference"]}).status_code==404
        client.cookies.set("login","alice-renewed")
        assert client.get("/api/assistant/cases").json()["items"][0]["id"]==case
        assert client.post(f"/api/assistant/cases/{case}/resolve",json={"resolved":False}).status_code==422
        assert client.post(f"/api/assistant/cases/{case}/resolve",json={"resolved":True}).status_code==200
        assert client.get("/api/assistant/cases").json()["items"][0]["next_check_at"] is None
        service.model = None
        assert client.post("/api/assistant/cases",json={"message":"Otra pregunta"}).status_code==503
