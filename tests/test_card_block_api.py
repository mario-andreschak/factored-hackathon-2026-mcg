"""Actual RC application, cookies and host join; no model/network calls."""
import json
import uuid

from fastapi.testclient import TestClient

from deploy.rc.run import prepare, application


def test_savia_spanish_portuguese_card_block_is_owned_confirmed_and_read_back(tmp_path):
    root = tmp_path / "fictional-rc"
    # Match public_start.py's private state directory on POSIX. The durable
    # bank-generation pin correctly refuses an insecure 0755 parent.
    root.mkdir(mode=0o700)
    prepare(root)
    fixture = json.loads((root / "fixture.json").read_text(encoding="utf-8"))
    app, bank = application(root, port=43905, base_url="http://localhost:43420", model_id="model-GPT-6 Luna")
    try:
        with TestClient(app, base_url="http://127.0.0.1:43905") as client:
            assert client.post("/api/cards/block", json={"product_reference": "prod_" + "a" * 24,
                "operation": "prepare", "request_id": str(uuid.uuid4())}).status_code == 401
            assert client.post("/api/auth/login", json={"profile": "mexico", "code": fixture["demo_code"]}).status_code == 200
            cards = [p for p in client.get("/api/overview").json()["products"] if p["type"] == "Tarjeta Crédito"]
            assert cards
            target = cards[0]["reference"]
            old_pending = client.post("/api/cards/block", json={"product_reference": target,
                "operation": "prepare", "request_id": str(uuid.uuid4())}).json()
            assert client.post("/api/auth/logout", json={}).status_code == 204
            assert client.post("/api/auth/login", json={"profile": "mexico", "code": fixture["demo_code"]}).status_code == 200
            stale = client.post("/api/cards/block", json={"product_reference": target,
                "operation": "status", "pending_handle": old_pending["pending_handle"]}).json()
            assert stale["state"] == "card_unblocked" and stale["pending_handle_current"] is False
            for message, language in [("bloquea mi tarjeta", "es"), ("bloqueie meu cartão", "pt")]:
                response = client.post("/api/chat/messages", json={"message": message, "language": language})
                assert response.status_code == 200, response.text
                assert response.json()["action_hint"] == "card_block"
                assert "real" in response.json()["reply"]
            prepared = client.post("/api/cards/block", json={"product_reference": target,
                "operation": "prepare", "request_id": str(uuid.uuid4())})
            assert prepared.status_code == 200, prepared.text
            pending = prepared.json()
            assert pending["state"] == "pending_confirmation"
            with bank.store.connect() as db:
                assert db.execute("SELECT count(*) FROM sandbox_card_blocks").fetchone()[0] == 0
            body = {"product_reference": target, "operation": "confirm", "pending_handle": pending["pending_handle"]}
            assert client.post("/api/cards/block", json=body).status_code == 422
            blocked = client.post("/api/cards/block", json={**body, "confirmed": True, "language": "pt"})
            assert blocked.status_code == 200, blocked.text
            verified = blocked.json()
            assert verified["state"] == "card_block_verified"
            assert verified["receipt"]["status"] == "blocked" and verified["receipt"]["simulated"] is True
            assert "Nenhum banco real" in verified["message"]
            assert client.post("/api/cards/block", json={**body, "confirmed": True, "customer_id": "foreign"}).status_code == 422
            recovered = client.post("/api/cards/block", json={**body, "operation": "receipt"}).json()
            assert recovered["receipt"] == verified["receipt"]
            overlay = client.get("/api/overview").json()
            assert next(p for p in overlay["products"] if p["reference"] == target)["card_protection_status"] == "blocked"
            assert client.post("/api/auth/logout", json={}).status_code == 204
            assert client.post("/api/auth/login", json={"profile": "mexico", "code": fixture["demo_code"]}).status_code == 200
            fresh = client.post("/api/cards/block", json={"product_reference": target, "operation": "status"}).json()
            assert fresh["receipt"] == verified["receipt"]
            # A new published snapshot preserves the original block receipt and shows current protection.
            from pipeline.__main__ import main
            assert main(["run", "--source", fixture["source"], "--out", fixture["data"],
                "--reports", str(root / "refreshed-reports")]) == 0
            after_refresh = client.post("/api/cards/block", json={"product_reference": target, "operation": "status"}).json()
            assert after_refresh["receipt"] == verified["receipt"]
            assert after_refresh["current_snapshot"] != verified["receipt"]["snapshot"]
            already = client.post("/api/cards/block", json={"product_reference": target, "operation": "prepare", "request_id": str(uuid.uuid4())}).json()
            assert already["receipt"] == verified["receipt"]
            assert client.post("/api/auth/logout", json={}).status_code == 204
            assert client.post("/api/auth/login", json={"profile": "colombia", "code": fixture["demo_code"]}).status_code == 200
            assert client.post("/api/cards/block", json={**body, "confirmed": True}).status_code == 404
            with bank.store.connect() as db:
                assert db.execute("SELECT count(*) FROM sandbox_card_blocks").fetchone()[0] == 1
    finally:
        bank.close()
