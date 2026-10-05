"""Bounded live API acceptance for two explicitly authorized fictional card blocks.

Does not call anything until run with --execute after deployment. RC_DEMO_CODE is
read from the environment; cookies, consent handles, profile/customer payloads and
raw receipts stay in memory. Public output contains status/invariant checks only.
There is no Brazil profile in current source: defaults are Mexico/ES and Colombia/PT.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha(value):
    raw = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class CheckFailed(Exception):
    pass


def require(condition, name):
    if not condition:
        raise CheckFailed(name)


class Client:
    def __init__(self, origin, timeout, receipt):
        self.origin, self.timeout, self.receipt = origin, timeout, receipt
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def call(self, method, path, payload=None, *, form=False, label):
        headers = {"Origin": self.origin, "Accept": "application/json", "User-Agent": "savia-card-block-acceptance/1.0"}
        if payload is None:
            body = None
        elif form:
            body = urllib.parse.urlencode(payload).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        started, tick = utc(), time.perf_counter()
        req = urllib.request.Request(self.origin + path, data=body, headers=headers, method=method)
        try:
            response = self.opener.open(req, timeout=self.timeout)
        except urllib.error.HTTPError as response_error:
            response = response_error
        with response:
            status, raw = response.status, response.read()
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeError):
            data = None
        self.receipt["http_steps"].append({"step": label, "method": method, "path": path,
            "status": status, "started_utc": started, "finished_utc": utc(),
            "latency_seconds": round(time.perf_counter() - tick, 6)})
        return status, data


def main(args):
    parsed = urllib.parse.urlsplit(args.origin)
    require(parsed.scheme in {"https", "http"} and parsed.netloc and not parsed.username
            and not parsed.password and parsed.path in {"", "/"} and not parsed.query and not parsed.fragment,
            "origin_must_be_plain_http_or_https_origin_without_credentials")
    origin = f"{parsed.scheme}://{parsed.netloc}"
    code = os.environ.get("RC_DEMO_CODE")
    require(bool(code), "RC_DEMO_CODE_environment_value_required")
    receipt = {"schema": "savia-live-card-block-api/v1", "origin": origin,
        "started_utc": utc(), "status": "running", "fictional_simulated_only": True,
        "script_sha256": sha(Path(__file__).read_bytes()),
        "operator_expected_source": args.expected_source,
        "source_scope": "Operator-provided deployment source; this harness does not independently establish image/source identity",
        "http_steps": [], "cases": [],
        "limits": ["API/cookie/host acceptance, not a graphical browser recording", "No real-bank action or refund", "Portuguese interaction does not imply a Brazilian demo profile", "No FLUJO/swarm or voice quality claim"]}
    client = Client(origin, args.timeout, receipt)
    try:
        status, _ = client.call("GET", "/healthz", label="public_health")
        require(status == 200, "public_health_must_be_200")
        # The redirect is followed; the Secure gateway cookie remains in memory.
        status, _ = client.call("POST", "/_rc/enter", {"code": code}, form=True, label="gateway_enter")
        require(status == 200 and any(c.name == "__Host-rc-visitor" for c in client.jar), "gateway_entry_cookie_required")
        status, _ = client.call("POST", "/api/cards/block", {"product_reference": "prod_" + "a" * 24,
            "operation": "status"}, label="application_unauthenticated_denial")
        require(status == 401, "application_cookie_required_before_card_access")

        def login(profile, label):
            status, _ = client.call("POST", "/api/auth/login", {"profile": profile, "code": code}, label=label)
            require(status == 200, label + "_must_be_200")

        def logout(label):
            status, _ = client.call("POST", "/api/auth/logout", {}, label=label)
            require(status == 204, label + "_must_be_204")

        def card(target, operation, label, **extra):
            return client.call("POST", "/api/cards/block", {"product_reference": target,
                "operation": operation, **extra}, label=label)

        profiles = [(args.es_profile, "es", "bloquea mi tarjeta"), (args.pt_profile, "pt", "bloqueie meu cartão")]
        require(args.es_profile != args.pt_profile, "two_distinct_profiles_required_for_foreign_profile_check")
        for index, (profile, language, message) in enumerate(profiles):
            prefix = f"case_{index + 1}_{language}"
            login(profile, prefix + "_login")
            status, overview = client.call("GET", "/api/overview", label=prefix + "_overview_before")
            require(status == 200 and isinstance(overview, dict), prefix + "_overview_required")
            candidates = [p["reference"] for p in overview.get("products", []) if p.get("type") == "Tarjeta Crédito" and p.get("reference")]
            require(bool(candidates), prefix + "_owned_credit_card_required")
            target = None
            initial = None
            # Bound read-only selection; never unblock/revert or mutate an existing receipt.
            for candidate in candidates[:3]:
                status, state = card(candidate, "status", prefix + "_select_unblocked_card", language=language)
                require(status == 200, prefix + "_status_must_be_200")
                if state.get("state") == "card_unblocked":
                    target, initial = candidate, state
                    break
            require(target is not None, prefix + "_fresh_unblocked_fixture_card_required")

            status, chat = client.call("POST", "/api/chat/messages", {"message": message, "language": language}, label=prefix + "_chat_hint")
            require(status == 200 and chat.get("action_hint") == "card_block", prefix + "_chat_card_block_hint_required")
            require("real" in chat.get("reply", ""), prefix + "_chat_fictional_caveat_required")
            status, pending = card(target, "prepare", prefix + "_prepare", request_id=str(uuid.uuid4()), language=language)
            require(status == 200 and pending.get("state") == "pending_confirmation" and pending.get("pending_handle"), prefix + "_pending_confirmation_required")
            handle = pending["pending_handle"]
            status, after_prepare = card(target, "status", prefix + "_prepare_readback_no_change", language=language)
            require(status == 200 and after_prepare.get("state") == "card_unblocked", prefix + "_prepare_must_not_block")
            status, _ = card(target, "confirm", prefix + "_omitted_consent_denied", pending_handle=handle, language=language)
            require(status == 422, prefix + "_omitted_consent_must_be_422")
            status, after_denial = card(target, "status", prefix + "_denial_readback_no_change", language=language)
            require(status == 200 and after_denial.get("state") == "card_unblocked", prefix + "_omitted_consent_must_not_block")

            # The sole new simulated write for this case: explicit confirmation.
            status, blocked = card(target, "confirm", prefix + "_explicit_confirm", pending_handle=handle, confirmed=True, language=language)
            saved = blocked.get("receipt") if isinstance(blocked, dict) else None
            require(status == 200 and blocked.get("state") == "card_block_verified" and isinstance(saved, dict)
                    and saved.get("status") == "blocked" and saved.get("simulated") is True,
                    prefix + "_verified_simulated_block_required")
            expected_caveat = "Nenhum banco real" if language == "pt" else "Ningún banco real"
            require(expected_caveat in blocked.get("message", ""), prefix + "_localized_fictional_caveat_required")
            status, readback = card(target, "receipt", prefix + "_receipt_readback", pending_handle=handle, language=language)
            require(status == 200 and readback.get("receipt") == saved, prefix + "_receipt_must_match")
            status, repeated = card(target, "confirm", prefix + "_repeat_confirmation_same_receipt", pending_handle=handle, confirmed=True, language=language)
            require(status == 200 and repeated.get("receipt") == saved, prefix + "_repeat_confirmation_must_deduplicate")
            status, overlay = client.call("GET", "/api/overview", label=prefix + "_overview_after")
            require(status == 200 and next((p.get("card_protection_status") for p in overlay.get("products", []) if p.get("reference") == target), None) == "blocked", prefix + "_overview_must_show_blocked")
            logout(prefix + "_logout")
            login(profile, prefix + "_relogin")
            status, durable = card(target, "status", prefix + "_relogin_durable_status", language=language)
            require(status == 200 and durable.get("state") == "card_block_verified" and durable.get("receipt") == saved, prefix + "_relogin_receipt_must_match")
            logout(prefix + "_logout_before_foreign")
            other_profile = profiles[1 - index][0]
            login(other_profile, prefix + "_foreign_login")
            status, _ = card(target, "status", prefix + "_foreign_profile_status_denied", language=language)
            require(status == 404, prefix + "_foreign_profile_status_must_be_404")
            status, _ = card(target, "confirm", prefix + "_foreign_profile_confirmation_denied", pending_handle=handle, confirmed=True, language=language)
            require(status == 404, prefix + "_foreign_profile_confirmation_must_be_404")
            logout(prefix + "_foreign_logout")
            receipt["cases"].append({"language": language, "fixture_profile": profile,
                "initial_state": initial["state"], "prepare_changed_card": False, "omitted_consent_denied": True,
                "confirmed_state": "card_block_verified", "receipt_status": "blocked", "simulated": True,
                "receipt_sha256": sha(saved), "receipt_readback_equal": True, "repeat_confirmation_equal": True,
                "overview_blocked": True, "relogin_receipt_equal": True, "foreign_profile_denied": True,
                "localized_no_real_bank_caveat": True})
        receipt["status"] = "passed"
    except CheckFailed as exc:
        receipt["status"], receipt["failed_invariant"] = "failed", str(exc)
    except Exception as exc:
        # No arbitrary HTTP bodies, exception strings, cookies or identifiers in output.
        receipt["status"], receipt["error_type"] = "failed", type(exc).__name__
    finally:
        receipt["finished_utc"] = utc()
        receipt["completed_cases"] = len(receipt["cases"])
        destination = Path(args.out).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--out", required=True, help="Sanitized public JSON receipt path")
    parser.add_argument("--expected-source", help="Operator-provided deployed source identity, not independently verified")
    parser.add_argument("--es-profile", default="mexico")
    parser.add_argument("--pt-profile", default="colombia")
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--execute", action="store_true", help="Explicitly enable two authorized simulated card blocks after deployment")
    args = parser.parse_args()
    if not args.execute:
        parser.error("No requests made. Pass --execute only after deploying the authorized fictional card-block build.")
    raise SystemExit(main(args))
