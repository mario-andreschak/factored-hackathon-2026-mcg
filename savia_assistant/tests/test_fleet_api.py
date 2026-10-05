import asyncio
import hashlib
import hmac
from types import SimpleNamespace
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from savia_assistant import InquiryService
from savia_assistant.api import install_routes
from savia_assistant.tests.test_fleet import FleetHarness


def application(service):
    app = FastAPI()
    app.state.inquiries = service
    secret = b"d"*32
    app.state.bank_state = SimpleNamespace(secret=secret)
    lookups, remembered = [], []
    selected = {"reference":"txn_"+"a"*24,"occurred_at":"2026-10-04T00:00:00Z",
                "amount":"25","currency":"USD","merchant":"Fixture café","status":"approved"}
    def transaction(profile,reference):
        lookups.append((profile,reference))
        return selected if profile=="alice" and reference==selected["reference"] else None
    app.state.repository = SimpleNamespace(profile_customer=lambda profile:profile,transaction=transaction)
    app.state.conversation = SimpleNamespace(remember_result=lambda session,reply:remembered.append((session,reply)))
    def authenticate(request):
        cookie = request.cookies.get("login","")
        if cookie not in {"alice-old","alice-renewed","bob"}:
            raise HTTPException(401)
        return SimpleNamespace(profile_id="bob" if cookie=="bob" else "alice",id=cookie)
    install_routes(app,authenticate)
    owner = hmac.new(secret,b"savia-inquiry:alice",hashlib.sha256).hexdigest()
    return app,owner,lookups,remembered,selected


def test_authenticated_retry_is_original_read_even_after_selection_or_binding_disappears(tmp_path):
    async def model(*args):
        raise AssertionError("API acceptance must not run a model")
    service = InquiryService(tmp_path,model)
    app,_,lookups,_,selected = application(service)
    body = {"message":"Ayuda con el cargo","transaction_reference":selected["reference"],"request_id":str(uuid.uuid4())}
    with TestClient(app) as client:
        assert client.post("/api/assistant/cases",json=body).status_code == 401
        client.cookies.set("login","alice-old")
        first = client.post("/api/assistant/cases",json=body)
        assert first.status_code == 202 and len(lookups)==1
        case_id = first.json()["id"]
        service.model = None
        app.state.repository.transaction = lambda *args: (_ for _ in ()).throw(AssertionError("Retry must not re-read selection"))
        client.cookies.set("login","alice-renewed")
        retry = client.post("/api/assistant/cases",json=body)
        assert retry.status_code==202 and retry.json()["id"]==case_id
        assert len(retry.json()["items"])==1
        assert client.post("/api/assistant/cases",json={**body,"message":"Other input"}).status_code==409
        assert client.post("/api/assistant/cases",json={**body,"owner":"alice"}).status_code==422
        client.cookies.set("login","bob")
        assert client.get("/api/assistant/cases").json()=={"items":[]}
        assert client.get("/api/assistant/voice-update",params={"case_id":case_id}).status_code==404
        assert client.post(f"/api/assistant/cases/{case_id}/resolve",json={"resolved":True}).status_code==404


def test_fleet_api_emits_only_verified_canonical_reply_for_current_owned_session(tmp_path,monkeypatch):
    upstream = FleetHarness(tmp_path,monkeypatch)
    app,owner,_,remembered,_ = application(upstream.service)
    body = {"message":"Ayuda con mi consulta","request_id":str(uuid.uuid4())}
    with TestClient(app) as client:
        client.cookies.set("login","alice-old")
        result = client.post("/api/assistant/cases",json=body)
        assert result.status_code==202
        upstream.case = result.json()["id"]
        asyncio.run(upstream.service.check(owner=owner))
        upstream.now[0] += 31
        upstream.state = "completed"
        upstream.result = "A human accepted and the bank paid."
        asyncio.run(upstream.service.check(owner=owner))
        held = client.get("/api/assistant/voice-update",params={"case_id":upstream.case}).json()
        assert held["inquiry_state"] == "needs_attention" and remembered==[]
        assert client.post(f"/api/assistant/cases/{upstream.case}/resolve",json={"resolved":True}).status_code==409
        upstream.complete()
        upstream.now[0] += 31
        asyncio.run(upstream.service.check(owner=owner))
        client.cookies.set("login","alice-renewed")
        spoken = client.get("/api/assistant/voice-update",params={"case_id":upstream.case,"after_event_id":held["event_id"]}).json()
        assert spoken["inquiry_state"]=="team_completed" and spoken["bank_authority"] is False
        assert remembered==[("alice-renewed",spoken["reply"])]
        assert "A human accepted" not in spoken["reply"] and "g-owned" not in spoken["reply"]
        assert client.get("/api/assistant/voice-update",params={"case_id":upstream.case,"after_event_id":spoken["event_id"]}).status_code==204
        assert len(remembered)==1
        client.cookies.set("login","bob")
        assert client.get("/api/assistant/voice-update",params={"case_id":upstream.case}).status_code==404
        assert client.post(f"/api/assistant/cases/{upstream.case}/resolve",json={"resolved":True}).status_code==404
        assert upstream.calls.count(("POST","/goals"))==1
