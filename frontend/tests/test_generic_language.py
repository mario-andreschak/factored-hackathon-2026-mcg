"""Pure MockTransport tests; no app, bank client, socket, browser or model runs."""
from __future__ import annotations

import asyncio
from dataclasses import asdict
import json
import unittest

import httpx

from frontend.server.language import GenericLanguageClient, LanguageConfig, MinimizedFacts, render_guidance


FLOW_ID = "11111111-1111-4111-8111-111111111111"
CONVERSATION = "22222222-2222-4222-8222-222222222222"
OTHER_CONVERSATION = "33333333-3333-4333-8333-333333333333"
TOKEN = "generic-service-token-private"
CONFIG = LanguageConfig("http://flujo:4200", FLOW_ID, "Language_Guidance", TOKEN)
FACTS = MinimizedFacts("2026-09-20", "42.00", "COP", "Tienda Ejemplo", "pending")


def completion(language="es", guidance="explain_selected", *, content=None, **changes):
    return {"conversation_id": CONVERSATION, "status": "completed", "choices": [{"message": {
        "role": "assistant", "content": content if content is not None else json.dumps({
            "schema": "host-language-guidance/v1", "language": language, "guidance": guidance})}}], **changes}


class GenericLanguageTests(unittest.IsolatedAsyncioTestCase):
    def client(self, response, *, config=CONFIG):
        requests = []

        async def respond(request):
            requests.append(request)
            if callable(response):
                return response(request)
            return httpx.Response(200, json=response)

        return GenericLanguageClient(config, transport=httpx.MockTransport(respond)), requests

    async def test_generic_route_headers_and_minimized_body_have_no_bank_authority(self):
        client, requests = self.client(completion())
        result = await client.guide("Explica el movimiento", "es", facts=FACTS,
                                    forbidden_values=("customer-private-a", "TXN_PRIVATE_1", "pending-private-capability"))
        self.assertTrue(result.model_output_accepted)
        self.assertFalse(result.banking_authority)
        self.assertEqual(result.conversation_id, CONVERSATION)
        request = requests[0]
        self.assertEqual((request.method, request.url.path), ("POST", "/v1/chat/completions"))
        self.assertEqual(request.headers["authorization"], "Bearer " + TOKEN)
        self.assertNotIn("x-flujo-user-assertion", request.headers)
        self.assertFalse(any("bank" in key.lower() for key in request.headers))
        body = json.loads(request.content)
        self.assertEqual(set(body), {"model", "messages", "stream", "metadata"})
        self.assertEqual(body["model"], "flow-Language_Guidance")
        self.assertEqual(body["metadata"], {"flujo": "true", "appendMessages": "true"})
        content = json.loads(body["messages"][0]["content"])
        self.assertEqual(content, {"schema": "host-language-request/v1", "language": "es",
                                  "request": "Explica el movimiento", "display_facts": asdict(FACTS)})
        for private in (TOKEN, FLOW_ID, "customer-private-a", "TXN_PRIVATE_1", "pending-private-capability",
                        "customer_id", "transaction_id", "pending_handle", "scope", "assertion"):
            self.assertNotIn(private, request.content.decode())
        self.assertIn("42.00 COP", result.reply)
        self.assertIn("pendiente", result.reply)
        self.assertNotIn(TOKEN, repr(CONFIG))

    async def test_es_pt_copy_preserves_exact_host_amount_and_never_claims_refund(self):
        facts = MinimizedFacts("2026-09-20", "9007199254740993.01", "COP", None, "reversed")
        for language in ("es", "pt"):
            with self.subTest(language=language):
                client, _ = self.client(completion(language))
                result = await client.guide("Explica", language, facts=facts)
                self.assertTrue(result.model_output_accepted)
                self.assertIn(facts.amount, result.reply)
                self.assertIn(facts.event_date, result.reply)
                self.assertIn("no confirma un reembolso" if language == "es" else "não confirma um reembolso", result.reply)

    async def test_generic_conversation_continuity_is_host_supplied_and_drift_fails_closed(self):
        client, requests = self.client(completion(guidance="ask_selection"))
        result = await client.guide("Ayuda", "es", conversation_id=CONVERSATION)
        self.assertEqual(result.conversation_id, CONVERSATION)
        self.assertEqual(json.loads(requests[0].content)["metadata"]["conversationId"], CONVERSATION)
        client, _ = self.client(completion(guidance="ask_selection", conversation_id=OTHER_CONVERSATION))
        result = await client.guide("Ayuda", "es", conversation_id=CONVERSATION)
        self.assertFalse(result.model_output_accepted)
        self.assertEqual(result.reason, "conversation_changed")
        self.assertIsNone(result.conversation_id)

    async def test_bank_private_conversation_cannot_leak_through_generic_metadata(self):
        client, requests = self.client(completion(guidance="ask_selection"))
        result = await client.guide("Ayuda", "es", conversation_id=CONVERSATION,
                                    forbidden_values=("customer-private-a", CONVERSATION))
        self.assertEqual(requests, [])
        self.assertEqual(result.reason, "input_rejected")
        self.assertIsNone(result.conversation_id)

    async def test_worker_returned_private_conversation_is_not_accepted_or_persistable(self):
        client, requests = self.client(completion(guidance="ask_selection"))
        result = await client.guide("Ayuda", "es", forbidden_values=(CONVERSATION,))
        self.assertEqual(len(requests), 1)
        self.assertEqual(result.reason, "invalid_response")
        self.assertFalse(result.model_output_accepted)
        self.assertIsNone(result.conversation_id)

    async def test_sensitive_user_inputs_do_not_reach_worker(self):
        private_inputs = ["txn_" + "a" * 24, "CMP-SBX-abcdefgh", "HOF-abcdefgh", CONVERSATION,
            "customer-private-a", "a" * 43, "eyJhbGciOiJFZERTQSJ9.eyJzdWIiOiJzZWNyZXQifQ.signature123",
            "1234 5678 9012 3456", "TXN0000000001", "https://private.invalid/object", TOKEN,
            "a\x00b", "a\x1bb", "a\u200bb", "a\ud800b", "\nAyuda", "Ayuda\r\n", "x" * 1001]
        for text in private_inputs:
            with self.subTest(text_index=private_inputs.index(text)):
                client, requests = self.client(completion())
                result = await client.guide("Explica " + text, "es", facts=FACTS,
                                            forbidden_values=("customer-private-a",))
                self.assertEqual(requests, [])
                self.assertEqual(result.reason, "input_rejected")
                self.assertFalse(result.banking_authority)
                self.assertNotIn(text, result.reply)

    async def test_sensitive_merchant_and_untyped_full_record_do_not_reach_worker(self):
        for facts in (MinimizedFacts("2026-09-20", "42.00", "COP", "txn_" + "a" * 24, "pending"),
                      {**asdict(FACTS), "customer_id": "customer-private-a"}):
            client, requests = self.client(completion())
            result = await client.guide("Explica", "es", facts=facts)
            self.assertEqual(requests, [])
            self.assertEqual(result.reason, "input_rejected")

    async def test_known_private_values_are_checked_before_json_escaping(self):
        for private in ('cust"private', "customer\\private", "café-private"):
            client, requests = self.client(completion())
            result = await client.guide("Explica " + private.upper(), "es", forbidden_values=(private,))
            self.assertEqual(requests, [])
            self.assertEqual(result.reason, "input_rejected")

    async def test_model_prose_action_fields_duplicate_keys_and_unknown_enums_never_render(self):
        rejected = ["Recepción creada CMP-SBX-abcdefgh; devolvimos el dinero.",
            json.dumps({"schema": "host-language-guidance/v1", "language": "es", "guidance": "explain_selected",
                        "receipt": "CMP-SBX-abcdefgh"}),
            json.dumps({"schema": "host-language-guidance/v1", "language": "es", "guidance": "confirm_intake"}),
            json.dumps({"schema": "host-language-guidance/v1", "language": "pt", "guidance": "explain_selected"}),
            '{"schema":"host-language-guidance/v1","language":"es","guidance":"suggest_human","guidance":"explain_selected"}',
            '["confirmed", true]', '```json\n{"guidance":"unavailable"}\n```', "x" * 1025]
        for content in rejected:
            with self.subTest(content_index=rejected.index(content)):
                client, _ = self.client(completion(content=content))
                result = await client.guide("Explica", "es", facts=FACTS)
                self.assertFalse(result.model_output_accepted)
                self.assertFalse(result.banking_authority)
                self.assertEqual(result.reason, "invalid_response")
                self.assertNotIn("CMP-SBX", result.reply)
                self.assertNotIn(content, result.reply)

    async def test_deep_bounded_json_response_falls_back_without_recursion_error(self):
        client, requests = self.client(completion(content="[" * 2000 + "0" + "]" * 2000))
        result = await client.guide("Explica", "es", facts=FACTS)
        self.assertFalse(result.model_output_accepted)
        self.assertEqual(result.reason, "invalid_response")
        self.assertEqual(len(requests), 1)

    async def test_tools_or_incomplete_wrapper_and_unverified_explanation_fail_closed(self):
        tool_message = {"role": "assistant", "content": "{}", "tool_calls": [{"function": {"name": "confirm_simulated_intake"}}]}
        responses = [completion(choices=[{"message": tool_message}]), completion(status="waiting_for_input"),
                     completion(conversation_id="foreign-private-id"), completion(choices=[]), {}, []]
        for response in responses:
            client, _ = self.client(response)
            result = await client.guide("Ayuda", "es", facts=FACTS)
            self.assertFalse(result.model_output_accepted)
            self.assertFalse(result.banking_authority)
        client, _ = self.client(completion())
        self.assertFalse((await client.guide("Explica", "es")).model_output_accepted)

    async def test_safe_human_guidance_does_not_claim_handoff_or_human_pickup(self):
        for language in ("es", "pt"):
            client, _ = self.client(completion(language, "suggest_human"))
            result = await client.guide("Quiero hablar con una persona", language)
            self.assertTrue(result.model_output_accepted)
            self.assertFalse(result.banking_authority)
            self.assertIn("no confirma" if language == "es" else "não confirma", result.reply)
            self.assertNotIn("HOF-", result.reply)

    def test_host_renderer_does_not_accept_arbitrary_client_prose_or_action_claims(self):
        claimed_reply = "Caso creado CMP-SBX-abcdefgh; devolvimos el dinero."
        for language in ("es", "pt"):
            safe = render_guidance("ask_selection", language, FACTS)
            self.assertIn("Selecciona" if language == "es" else "Selecione", safe)
            for guidance, facts in ((claimed_reply, FACTS), ("confirm_intake", FACTS),
                                    ([], FACTS), ("explain_selected", None),
                                    ("explain_selected", asdict(FACTS))):
                with self.subTest(language=language, guidance_type=type(guidance).__name__):
                    rendered = render_guidance(guidance, language, facts)
                    self.assertNotIn("CMP-SBX", rendered)
                    self.assertNotIn(claimed_reply, rendered)
                    self.assertIn("segura", rendered)
        self.assertIn("segura", render_guidance("ask_selection", "invalid"))
        self.assertIn("42.00 COP", render_guidance("explain_selected", "es", FACTS))

    async def test_redirect_errors_and_oversized_response_never_retry_or_echo_secrets(self):
        def redirect(_):
            return httpx.Response(302, headers={"location": "https://untrusted.invalid"}, text=TOKEN)

        def unavailable(_):
            return httpx.Response(503, text=TOKEN)

        def lost(request):
            raise httpx.ReadError(TOKEN, request=request)

        def oversized(_):
            return httpx.Response(200, content=b"x" * (64 * 1024 + 1), headers={"content-type": "application/json"})

        for response in (redirect, unavailable, lost, oversized):
            client, requests = self.client(response)
            result = await client.guide("Ayuda", "es")
            self.assertEqual(len(requests), 1)
            self.assertFalse(result.model_output_accepted)
            self.assertNotIn(TOKEN, repr(result))

    async def test_total_deadline_bounds_mock_transport_without_retries(self):
        requests = []

        async def stalled(request):
            requests.append(request)
            await asyncio.Event().wait()

        config = LanguageConfig("http://flujo:4200", FLOW_ID, "Language_Guidance", TOKEN, timeout_seconds=0.01)
        client = GenericLanguageClient(config, transport=httpx.MockTransport(stalled))
        result = await client.guide("Ayuda", "pt")
        self.assertEqual(result.reason, "language_unavailable")
        self.assertEqual(len(requests), 1)

    def test_config_and_projection_reject_extra_authority_or_invalid_fields(self):
        for changes in ({"base_url": "http://public.invalid"}, {"base_url": "https://user:secret@host.invalid"},
                        {"base_url": "http://flujo:99999"}, {"base_url": "https://host.invalid\n"},
                        {"base_url": "HTTP://flujo:4200"}, {"base_url": "https://HOST.invalid"},
                        {"base_url": "https://host.invalid:00443"}, {"base_url": "https://host.invalid%2Fpath"},
                        {"flow_id": "browser-selected"}, {"flow_name": "../../other"}, {"service_token": "a\nb"},
                        {"timeout_seconds": float("nan")}):
            with self.assertRaises(ValueError):
                LanguageConfig(**{**asdict(CONFIG), **changes})
        with self.assertRaises(TypeError):
            LanguageConfig(**{**asdict(CONFIG), "headers": {"X-Flujo-User-Assertion": "private"}})
        with self.assertRaises(TypeError):
            MinimizedFacts(**{**asdict(FACTS), "pending_handle": "private"})
        for changes in ({"event_date": "2026-02-30"}, {"amount": "nan"}, {"merchant": "a\nb"},
                        {"currency": "cop"}, {"recorded_status": "refunded"}):
            with self.assertRaises(ValueError):
                MinimizedFacts(**{**asdict(FACTS), **changes})
