"""Extracted action API locale regressions; no application/runtime imports.

Only the fixed message map/helper, selected nested action handlers, ChatError,
and the side-effect-free admission guard are executed. Decorators and inspected
relative imports are removed; inert HTTP/session/repository/service callbacks
are supplied before execution. This tests fixed ES/PT text and status handling,
not routing, FastAPI, an actual ChatService, persistence, banking authority,
TLS, cryptography, a provider, or customer acceptance.
"""
from __future__ import annotations

import ast
import asyncio
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "server"
SECRET = "fictional-upstream-secret-that-must-not-be-rendered"
# Independent fixed literals: expected copy never comes from the source map.
EXPECTED = {
    "es": {
        "action_unverified": "La continuidad de la solicitud requiere revisión.",
        "authorization_denied": "La conexión segura no está disponible.",
        "action_unavailable": "La recepción simulada no está habilitada.",
        "missing_service": "El asistente no está disponible para esta sesión.",
        "fallback": "No se pudo verificar la solicitud.",
        "response": "No se pudo verificar la respuesta de la recepción simulada.",
        "status": "No se pudo verificar el estado de la recepción simulada.",
        "target": "El movimiento seleccionado no está disponible.",
        "handoff": "La solicitud no corresponde a una revisión pendiente.",
    },
    "pt": {
        "action_unverified": "A continuidade da solicitação requer revisão.",
        "authorization_denied": "A conexão segura não está disponível.",
        "action_unavailable": "A solicitação simulada não está habilitada.",
        "missing_service": "O assistente não está disponível para esta sessão.",
        "fallback": "Não foi possível verificar a solicitação.",
        "response": "Não foi possível verificar a resposta da solicitação simulada.",
        "status": "Não foi possível verificar o estado da solicitação simulada.",
        "target": "O lançamento selecionado não está disponível.",
        "handoff": "A solicitação não corresponde a uma revisão pendente.",
    },
}
STATUSES = {"action_unverified": 503, "authorization_denied": 409, "action_unavailable": 503}


def _tree(filename):
    return ast.parse((SOURCE / filename).read_text(encoding="utf-8"), filename=filename)


class _InspectedImports(ast.NodeTransformer):
    def visit_ImportFrom(self, node):
        names = tuple(alias.name for alias in node.names)
        if node.level == 1 and ((node.module == "chat" and names == ("ChatError",))
                                or (node.module == "action" and names == ("render_action_error",))):
            if any(alias.asname for alias in node.names):
                raise AssertionError("Unexpected alias in extracted import")
            return ast.copy_location(ast.Pass(), node)
        raise AssertionError("Unexpected import in extracted source")

    def visit_Import(self, node):
        raise AssertionError("Unexpected import in extracted source")


def _execute(filename, nodes, namespace):
    selected = []
    for node in nodes:
        node = deepcopy(node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            node.decorator_list = []
        selected.append(_InspectedImports().visit(node))
    # Postponed annotations keep all real application type namespaces absent.
    module = ast.Module(body=[ast.ImportFrom(module="__future__", level=0,
        names=[ast.alias(name="annotations")])] + selected, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(SOURCE / filename), "exec"), namespace)


def _selected_top_level(filename, names):
    selected = {}
    for node in _tree(filename).body:
        node_names = ([node.name] if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                      else [target.id for target in node.targets if isinstance(target, ast.Name)]
                      if isinstance(node, ast.Assign) else [])
        for name in node_names:
            if name in names:
                assert name not in selected, "Duplicate selected definition: " + name
                selected[name] = node
    assert set(selected) == set(names), (set(names) - set(selected))
    return [selected[name] for name in names]


class _HTTPException(Exception):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _source():
    calls = []
    current = SimpleNamespace(profile_id="fictional-profile", id="fictional-session", expires_at=2_000_000_300)
    target = {"transaction_id": "fictional-owned-row", "snapshot": "fictional-snapshot",
              "transaction": {"fixture": "bounded-owned-display"}}

    def session(request):
        calls.append(("session", request))
        return current

    def profile_customer(profile_id):
        calls.append(("profile_customer", profile_id))
        return "fictional-customer"

    def action_target(profile_id, reference):
        calls.append(("action_target", profile_id, reference))
        return target

    def render_action_result(result, language):
        calls.append(("render_action_result", result, language))
        return {"fixture": "rendered", "language": language}

    namespace = {"__name__": __name__, "HTTPException": _HTTPException,
                 "session": session, "render_action_result": render_action_result}
    _execute("action.py", _selected_top_level("action.py", ("_ACTION_ERROR_MESSAGES", "render_action_error")), namespace)
    _execute("chat.py", _selected_top_level("chat.py", ("ChatError",)), namespace)
    chat = next(node for node in _tree("chat.py").body if isinstance(node, ast.ClassDef) and node.name == "ChatService")
    guard = [node for node in chat.body if isinstance(node, ast.FunctionDef) and node.name == "_require_action_admission"]
    assert len(guard) == 1
    _execute("chat.py", guard, namespace)
    app = next(node for node in _tree("app.py").body if isinstance(node, ast.FunctionDef) and node.name == "create_app")
    names = ("run_action", "action_status", "action_prepare", "action_confirm", "action_handoff")
    handlers = {node.name: node for node in app.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in names}
    assert set(handlers) == set(names)
    _execute("app.py", [handlers[name] for name in names], namespace)
    repository = SimpleNamespace(profile_customer=profile_customer, action_target=action_target)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(repository=repository, chat_service=None)))
    return namespace, request, calls, target


class ActionErrorLocaleTests(unittest.TestCase):
    def setUp(self):
        self.ns, self.request, self.calls, self.target = _source()

    def _service_error(self, code, status):
        async def action(*args, **kwargs):
            self.calls.append(("action", args, kwargs))
            raise self.ns["ChatError"](code, status, SECRET, possibly_sent=True)

        async def action_status(*args, **kwargs):
            self.calls.append(("action_status", args, kwargs))
            raise self.ns["ChatError"](code, status, SECRET, possibly_sent=True)

        self.request.app.state.chat_service = SimpleNamespace(action=action, action_status=action_status)

    def _error(self, coroutine):
        with self.assertRaises(_HTTPException) as caught:
            asyncio.run(coroutine)
        self.assertNotIn(SECRET, caught.exception.detail)
        return caught.exception

    def _body(self, language):
        return SimpleNamespace(language=language, transaction_reference="txn_fictional",
                               pending_handle="fictional-pending", confirmed=True)

    def test_fixed_known_messages_have_independent_es_pt_literals(self):
        for language in ("es", "pt"):
            for code in STATUSES:
                with self.subTest(language=language, code=code):
                    self.assertEqual(self.ns["render_action_error"](code, language), EXPECTED[language][code])

    def test_status_translates_fixed_codes_and_preserves_http_status(self):
        for language in ("es", "pt"):
            for code, status in STATUSES.items():
                with self.subTest(language=language, code=code):
                    self._service_error(code, status)
                    error = self._error(self.ns["action_status"](self.request, language))
                    self.assertEqual((error.status_code, error.detail), (status, EXPECTED[language][code]))

    def test_prepare_translates_fixed_codes_through_run_action(self):
        for language in ("es", "pt"):
            for code, status in STATUSES.items():
                with self.subTest(language=language, code=code):
                    self._service_error(code, status)
                    error = self._error(self.ns["action_prepare"](self._body(language), self.request))
                    self.assertEqual((error.status_code, error.detail), (status, EXPECTED[language][code]))
                    args, kwargs = [call[1:] for call in self.calls if call[0] == "action"][-1]
                    self.assertEqual(args, ("fictional-customer", "fictional-session", 2_000_000_300,
                        {"operation": "prepare", "transactionId": self.target["transaction_id"], "snapshot": self.target["snapshot"]}))
                    self.assertEqual(kwargs, {"target_reference": "txn_fictional", "expected_snapshot": self.target["snapshot"],
                                             "expected_transaction": self.target["transaction"]})

    def test_confirm_translates_fixed_codes_through_run_action(self):
        for language in ("es", "pt"):
            for code, status in STATUSES.items():
                with self.subTest(language=language, code=code):
                    self._service_error(code, status)
                    error = self._error(self.ns["action_confirm"](self._body(language), self.request))
                    self.assertEqual((error.status_code, error.detail), (status, EXPECTED[language][code]))
                    args, kwargs = [call[1:] for call in self.calls if call[0] == "action"][-1]
                    self.assertEqual(args[-1], {"operation": "confirm", "pendingHandle": "fictional-pending", "confirmed": True})
                    self.assertEqual(kwargs, {"target_reference": "txn_fictional", "expected_snapshot": self.target["snapshot"],
                                             "expected_transaction": self.target["transaction"]})

    def test_unknown_error_uses_fixed_fallback_without_upstream_message(self):
        for language in ("es", "pt"):
            self._service_error("fictional_unknown_code", 418)
            for handler in (lambda: self.ns["action_status"](self.request, language),
                            lambda: self.ns["action_prepare"](self._body(language), self.request),
                            lambda: self.ns["action_confirm"](self._body(language), self.request)):
                with self.subTest(language=language):
                    error = self._error(handler())
                    self.assertEqual((error.status_code, error.detail), (418, EXPECTED[language]["fallback"]))

    def test_missing_service_status_is_localized_and_does_not_dispatch(self):
        for language in ("es", "pt"):
            with self.subTest(language=language):
                error = self._error(self.ns["action_status"](self.request, language))
                self.assertEqual((error.status_code, error.detail), (503, EXPECTED[language]["missing_service"]))
        self.assertFalse(any(call[0] in {"action", "action_status", "render_action_result"} for call in self.calls))

    def test_missing_service_prepare_confirm_is_localized_and_does_not_dispatch(self):
        for language in ("es", "pt"):
            for name in ("action_prepare", "action_confirm"):
                with self.subTest(language=language, handler=name):
                    error = self._error(self.ns[name](self._body(language), self.request))
                    self.assertEqual((error.status_code, error.detail), (503, EXPECTED[language]["missing_service"]))
        self.assertFalse(any(call[0] in {"action", "action_status", "render_action_result"} for call in self.calls))

    def test_safe_default_continuity_guard_is_translated_at_pt_api_boundary(self):
        fixture = SimpleNamespace(_action_enabled=True, _ledger_continuity_approved=False)

        async def action(*args, **kwargs):
            self.ns["_require_action_admission"](fixture)
            self.fail("Guard must deny before returning a result")

        self.request.app.state.chat_service = SimpleNamespace(action=action, action_status=action)
        for handler in (lambda: self.ns["action_status"](self.request, "pt"),
                        lambda: self.ns["action_prepare"](self._body("pt"), self.request),
                        lambda: self.ns["action_confirm"](self._body("pt"), self.request)):
            with self.subTest(handler=handler):
                error = self._error(handler())
                self.assertEqual((error.status_code, error.detail), (503, EXPECTED["pt"]["action_unverified"]))

    def test_value_error_response_and_status_are_fixed_and_localized(self):
        async def invalid(*args, **kwargs):
            raise ValueError(SECRET)

        self.request.app.state.chat_service = SimpleNamespace(action=invalid, action_status=invalid)
        for language in ("es", "pt"):
            for name, expected in (("action_status", "status"), ("action_prepare", "response"),
                                   ("action_confirm", "response")):
                with self.subTest(language=language, handler=name):
                    coroutine = (self.ns[name](self.request, language) if name == "action_status"
                                 else self.ns[name](self._body(language), self.request))
                    error = self._error(coroutine)
                    self.assertEqual((error.status_code, error.detail), (502, EXPECTED[language][expected]))

    def test_unavailable_owned_target_is_localized_before_dispatch(self):
        self.request.app.state.repository.action_target = lambda *args: None
        for language in ("es", "pt"):
            for name in ("action_prepare", "action_confirm"):
                with self.subTest(language=language, handler=name):
                    error = self._error(self.ns[name](self._body(language), self.request))
                    self.assertEqual((error.status_code, error.detail), (404, EXPECTED[language]["target"]))
        self.assertFalse(any(call[0] in {"action", "action_status", "render_action_result"} for call in self.calls))

    def test_handoff_preflight_mismatch_is_localized_before_dispatch(self):
        for language in ("es", "pt"):
            body = SimpleNamespace(language=language, model_fields_set=set(), pending_handle=None,
                                   reason="duplicate_review")
            with self.subTest(language=language):
                error = self._error(self.ns["action_handoff"](body, self.request))
                self.assertEqual((error.status_code, error.detail), (409, EXPECTED[language]["handoff"]))
        self.assertEqual(self.calls, [])

    def test_malformed_code_or_locale_cannot_escape_fixed_fallback(self):
        render = self.ns["render_action_error"]
        for code in (None, {}, [], 7, True, SECRET):
            for language in ("es", "pt"):
                with self.subTest(code=code, language=language):
                    self.assertEqual(render(code, language), EXPECTED[language]["fallback"])
        for language in (None, {}, [], True, "en", SECRET):
            with self.subTest(language=language):
                self.assertEqual(render("action_unverified", language), EXPECTED["es"]["action_unverified"])


if __name__ == "__main__":
    unittest.main()
