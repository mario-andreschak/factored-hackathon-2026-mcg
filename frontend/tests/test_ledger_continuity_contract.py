"""Source-extracted host continuity controls; no application/runtime imports.

Only selected definitions are executed. HTTP, JWT encoding, canonicalization,
language configuration, protocol projection, and row cursors are inert recording
callbacks installed before source execution. Cursors return scripted rows and
never parse SQL or implement bank decisions. These checks establish source call
ordering and propagation, not TLS, cryptography, SQLite atomicity, durability,
restart/restore detection, provider behavior, or customer evidence.
"""
from __future__ import annotations

import ast
import asyncio
from collections import deque
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import inspect
import json
import math
from pathlib import Path
import re
from types import MethodType, SimpleNamespace
import unittest
import uuid


SOURCE = Path(__file__).resolve().parents[1] / "server"
GENERATION = "a" * 64
OTHER_GENERATION = "b" * 64
NOW = 2_000_000_000
EXPIRY = NOW + 300
OPERATION = "11111111-1111-4111-8111-111111111111"
CONVERSATION = "22222222-2222-4222-8222-222222222222"
HANDLE = "h" * 43


def _tree(filename):
    return ast.parse((SOURCE / filename).read_text(encoding="utf-8"), filename=filename)


class _InertImports(ast.NodeTransformer):
    """Replace only the inspected nested action import with its supplied seam."""
    def visit_ImportFrom(self, node):
        if node.level == 1 and node.module == "action" and [n.name for n in node.names] == ["matches_selected_transaction"]:
            return ast.copy_location(ast.Pass(), node)
        raise AssertionError("Unexpected import in extracted source")


def _extract(filename, namespace, *, names=(), class_methods=None):
    wanted = set(names)
    nodes = []
    for node in _tree(filename).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in wanted:
            nodes.append(deepcopy(node))
            wanted.remove(node.name)
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in wanted for t in node.targets):
            nodes.append(deepcopy(node))
            wanted.difference_update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.ClassDef) and class_methods and node.name in class_methods:
            methods = set(class_methods[node.name])
            for method in node.body:
                if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) and method.name in methods:
                    selected = deepcopy(method)
                    selected.decorator_list = []
                    nodes.append(selected)
                    methods.remove(method.name)
            assert not methods, methods
    assert not wanted, wanted
    # Annotations are postponed, so real HTTP/SQLite type namespaces are absent.
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)] +
                       [_InertImports().visit(n) for n in nodes], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(SOURCE / filename), "exec"), namespace)
    return namespace


class _Encoder:
    def __init__(self):
        self.calls = []

    def encode(self, claims, key, *, algorithm, headers):
        self.calls.append((deepcopy(claims), key, algorithm, deepcopy(headers)))
        return "recorded-token-" + str(len(self.calls))


class _Client:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


class _HTTPError(Exception):
    pass


class _TimeoutError(_HTTPError):
    pass


def _canonical(value):
    # Recording seam for the bounded integer/string/list fixtures only. This is
    # deliberately not claimed to validate RFC8785's full numeric/Unicode rules.
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _rpc_source():
    encoder = _Encoder()
    namespace = {"__name__": __name__, "dataclass": dataclass, "field": field,
                 "re": re, "uuid": uuid, "inspect": inspect, "hashlib": hashlib,
                 "math": math, "json": json, "asyncio": asyncio,
                 "time": SimpleNamespace(time=lambda: NOW), "jwt": encoder,
                 "rfc8785": SimpleNamespace(dumps=_canonical),
                 "httpx": SimpleNamespace(AsyncClient=_Client, Timeout=lambda *args, **kwargs: (args, kwargs),
                                          HTTPError=_HTTPError, TimeoutException=_TimeoutError)}
    _extract("bank_rpc.py", namespace, names=("PROTOCOL_VERSION", "ASSERTION_META", "_SCOPES", "_ERRORS",
             "_text", "_uuid", "_json", "BankContext", "BankRPCError"),
             class_methods={"BankRPC": ("_timeout", "_current", "_assertion", "_result", "call", "revoke")})
    # No BankRPC constructor, key loader, HTTP implementation, or _post body is
    # extracted. The fixture object receives the exact selected source methods.
    rpc = SimpleNamespace(_issuer="fictional-host", _audience="banking-mcp", _kid="fictional-key",
                          _key=object(), _tls=object(), _transport=None)
    for method in ("_assertion", "call", "revoke"):
        setattr(rpc, method, MethodType(namespace[method], rpc))
    for method in ("_timeout", "_current", "_result"):
        setattr(rpc, method, namespace[method])
    return namespace, rpc, encoder


def _context(namespace, **changes):
    values = {"subject": "fictional-subject", "session_id": "fictional-bank-session",
              "conversation_id": CONVERSATION, "operation_id": OPERATION,
              "host_revision": "c" * 40, "session_expires": EXPIRY,
              "ledger_generation": GENERATION}
    values.update(changes)
    return namespace["BankContext"](**values)


def _controller_source(rpc_namespace):
    namespace = {"__name__": __name__, "re": re, "BankContext": rpc_namespace["BankContext"],
                 "BankRPCError": rpc_namespace["BankRPCError"],
                 "validate_action_result": lambda tool, value: value,
                 "handoff_questions": lambda value: value if isinstance(value, list) else None,
                 "public_facts": lambda value: value if isinstance(value, dict) else None,
                 "verified_receipt": lambda value: value if isinstance(value, dict) else None,
                 "verified_handoff": lambda value: value.get("packet") if isinstance(value, dict) else None,
                 "matches_selected_transaction": lambda facts, expected: facts == expected}
    return _extract("bank_controller.py", namespace, names=("_HANDLE", "_REASONS", "BankController"))


def _sql(text):
    return " ".join(text.split())


class _ScriptedRows:
    """Exact callback script, without a database or SQL interpretation."""
    def __init__(self, steps):
        self.steps = deque(steps)
        self.calls = []
        self.current = None

    def execute(self, statement, arguments=()):
        self.calls.append((_sql(statement), arguments))
        assert self.steps, "Unexpected cursor callback: " + _sql(statement)
        expected, value = self.steps.popleft()
        assert _sql(statement) == _sql(expected), (statement, expected)
        self.current = value
        return self

    def fetchone(self):
        return self.current

    def __iter__(self):
        return iter(self.current)

    def complete(self):
        assert not self.steps, list(self.steps)


PIN_QUERY = "SELECT value FROM host_policy WHERE key='ledger_generation'"
SESSION_QUERY = "SELECT owner,expires,revoked,ledger_generation FROM chat_sessions WHERE session_id=?"
BANK_CONTEXT_QUERY = "SELECT bank_context_id,ledger_generation FROM chat_sessions WHERE session_id=?"


class _Connections:
    def __init__(self, plans):
        self.plans = deque(plans)
        self.used = []

    @contextmanager
    def connect(self):
        assert self.plans, "Unexpected connection callback"
        cursor = _ScriptedRows(self.plans.popleft())
        self.used.append(cursor)
        try:
            yield cursor
        finally:
            cursor.complete()

    def complete(self):
        assert not self.plans, list(self.plans)


def _host_source(rpc_namespace, controller_namespace):
    constructor_calls = []

    def bank_factory(config):
        constructor_calls.append(("bank", config))
        return SimpleNamespace(authority_identity={"endpoint": "fictional-private-authority"})

    def language_factory(config):
        constructor_calls.append(("language", config))
        return SimpleNamespace()

    namespace = {"__name__": __name__, "re": re, "hashlib": hashlib, "json": json,
                 "uuid": uuid, "asyncio": asyncio, "time": SimpleNamespace(time=lambda: NOW),
                 "BankContext": rpc_namespace["BankContext"], "BankRPCError": rpc_namespace["BankRPCError"],
                 "BankRPC": bank_factory, "BankController": controller_namespace["BankController"],
                 "GenericLanguageClient": language_factory, "LanguageConfig": lambda **kwargs: kwargs,
                 "_REVOKE_TIMEOUT": 10}
    methods = ("_configure", "_retained_ledger_generation", "_assert_ledger_binding", "_require_action_admission",
               "_owner_for_subject", "_assert_action_session", "_reserve_action", "_claim_prepare_recovery",
               "_bind", "_bank_context", "_bank_post", "_finish_revoke", "attempt_revoke", "status",
               "_release_rejected_prepare_recovery")
    _extract("chat.py", namespace, names=("_LEDGER_GENERATION", "ChatError"), class_methods={"ChatService": methods})
    host = SimpleNamespace(_configured=True, _namespace="fictional", _issuer="fictional-host",
                           _host_revision="c" * 40, _ledger_generation=GENERATION,
                           _action_enabled=True, _ledger_continuity_approved=True,
                           _approved_subject_customers={"fictional-subject": "fictional-customer"},
                           _approved_owner_subjects={}, _customer_subjects={}, _reason="fictional")
    for method in methods:
        if method != "_retained_ledger_generation":
            setattr(host, method, MethodType(namespace[method], host))
    return namespace, host, constructor_calls


def _admission_plan(owner):
    return [("BEGIN", None), (PIN_QUERY, (GENERATION,)), (PIN_QUERY, (GENERATION,)),
            (SESSION_QUERY, {"owner": owner, "expires": EXPIRY, "revoked": 0, "ledger_generation": GENERATION}),
            (BANK_CONTEXT_QUERY, {"bank_context_id": CONVERSATION, "ledger_generation": GENERATION})]


class LedgerContinuityContractTests(unittest.TestCase):
    def setUp(self):
        self.rpc_ns, self.rpc, self.encoder = _rpc_source()
        self.controller_ns = _controller_source(self.rpc_ns)
        self.host_ns, self.host, self.constructors = _host_source(self.rpc_ns, self.controller_ns)

    def test_context_requires_exact_mandatory_generation(self):
        with self.assertRaises(TypeError):
            self.rpc_ns["BankContext"]("subject", "session", "conversation", OPERATION, "c" * 40, EXPIRY)
        for generation in (None, "", "a" * 63, "a" * 65, "A" * 64, "g" * 64, 7, True, " a" + "a" * 62):
            with self.subTest(generation=generation), self.assertRaisesRegex(ValueError, "invalid_bank_context"):
                _context(self.rpc_ns, ledger_generation=generation)
        self.assertEqual(_context(self.rpc_ns).ledger_generation, GENERATION)

    def test_exact_generation_claim_in_both_existing_token_types(self):
        expected_keys = {"iss", "aud", "sub", "iat", "nbf", "exp", "jti", "session_id", "conversation_id",
                         "run_id", "graph_revision", "ledger_generation", "tool", "scope", "args_sha256"}
        for tool, scope, token_type, args in (
            ("confirm_simulated_intake", "bank:write", "bank-mcp+jwt", {"pending_handle": HANDLE, "confirmed": True}),
            ("revoke_session", "bank:revoke", "bank-revoke+jwt", {}),
        ):
            with self.subTest(token_type=token_type):
                token = self.rpc._assertion(tool, args, _context(self.rpc_ns), scope, token_type, NOW + 15)
                claims, key, algorithm, headers = self.encoder.calls[-1]
                self.assertEqual(set(claims), expected_keys)
                self.assertEqual(claims["ledger_generation"], GENERATION)
                self.assertEqual(claims["args_sha256"], hashlib.sha256(_canonical(args)).hexdigest())
                self.assertEqual((claims["tool"], claims["scope"], claims["run_id"]), (tool, [scope], OPERATION))
                self.assertEqual((claims["iat"], claims["nbf"], claims["exp"]), (NOW, NOW, NOW + 15))
                self.assertEqual((algorithm, headers), ("EdDSA", {"typ": token_type, "kid": "fictional-key"}))
                self.assertIs(key, self.rpc._key)
                self.assertTrue(token.startswith("recorded-token-"))
        self.assertNotEqual(self.encoder.calls[0][0]["jti"], self.encoder.calls[1][0]["jti"])

    def test_signing_denies_changed_continuity_before_encoder(self):
        def deny():
            raise self.rpc_ns["BankRPCError"]("action_unverified")
        with self.assertRaises(self.rpc_ns["BankRPCError"]) as error:
            self.rpc._assertion("confirm_simulated_intake", {}, _context(self.rpc_ns, admission_check=deny),
                                "bank:write", "bank-mcp+jwt", NOW + 10)
        self.assertEqual((error.exception.code, error.exception.possibly_sent), ("action_unverified", False))
        self.assertEqual(self.encoder.calls, [])

    def test_generation_configuration_invalid_before_constructor_or_cursor(self):
        base = self._config()
        for generation in (None, "", "A" * 64, "a" * 63, "a" * 65, "g" * 64, 1, True):
            with self.subTest(generation=generation), self.assertRaises(ValueError):
                self.host._configure({**base, "ledger_generation": generation})
        missing = dict(base)
        missing.pop("ledger_generation")
        with self.assertRaises(ValueError):
            self.host._configure(missing)
        self.assertEqual(self.constructors, [])

    def _config(self):
        return {"mode": "host-direct-mcp/v1", "namespace": "fictional", "host_revision": "c" * 40,
                "action_enabled": True, "ledger_generation": GENERATION,
                "bank": {"issuer": "fictional-host", "audience": "banking-mcp", "service_token": "bank-fixture"},
                "language": {"service_token": "language-fixture"},
                "principal_customers": {"fictional-subject": "fictional-customer"}}

    def test_continuity_default_false_disables_actions_with_valid_pin(self):
        db = _Connections([[('BEGIN IMMEDIATE', None), (PIN_QUERY, None),
                            ("SELECT value FROM host_policy WHERE key='bank_binding'", None),
                            ("INSERT OR IGNORE INTO host_policy VALUES ('bank_binding', ?)", None),
                            ("INSERT OR IGNORE INTO host_policy VALUES ('ledger_generation', ?)", None)]])
        self.host._connection = db.connect
        self.host._configure(self._config())
        self.assertFalse(self.host._ledger_continuity_approved)
        self.assertEqual(self.host._ledger_generation, GENERATION)
        with self.assertRaises(self.host_ns["ChatError"]) as error:
            self.host._require_action_admission()
        self.assertEqual(error.exception.code, "action_unverified")
        self.assertTrue(self.host.status("fictional-customer")["read_only"])
        self.assertFalse(self.host.status("fictional-customer")["sandbox_intake_available"])
        db.complete()

    def test_legacy_nonempty_unpinned_history_rejected_with_reads_only(self):
        for table in ("chat_sessions", "action_status", "pending_revocations", "chat_messages"):
            with self.subTest(table=table):
                db = _ScriptedRows([(f"SELECT 1 FROM {table} LIMIT 1", (1,))])
                with self.assertRaisesRegex(RuntimeError, "no generation adoption"):
                    self.host_ns["_retained_ledger_generation"](db, {table})
                self.assertEqual(len(db.calls), 1)
                db.complete()

    def test_empty_new_volume_is_not_assigned_an_existing_pin(self):
        db = _ScriptedRows([])
        self.assertIsNone(self.host_ns["_retained_ledger_generation"](db, set()))
        self.assertEqual(db.calls, [])

    def test_pinned_retained_authority_rows_require_same_generation(self):
        for table, columns, mismatch in (
            ("chat_sessions", [(0, "owner")], None),
            ("pending_revocations", [(0, "ledger_generation")], (1,)),
        ):
            with self.subTest(table=table):
                steps = [(PIN_QUERY, (GENERATION,)), (f"SELECT 1 FROM {table} LIMIT 1", (1,)),
                         (f"PRAGMA table_info({table})", columns)]
                if mismatch is not None:
                    steps.append((f"SELECT 1 FROM {table} WHERE ledger_generation IS NULL OR ledger_generation != ? LIMIT 1", mismatch))
                db = _ScriptedRows(steps)
                with self.assertRaisesRegex(RuntimeError, "history generation is unverified"):
                    self.host_ns["_retained_ledger_generation"](db, {"host_policy", table})
                self.assertTrue(all(query.startswith(("SELECT", "PRAGMA")) for query, _ in db.calls))
                db.complete()

    def test_pre_migration_source_calls_retained_pin_scan_before_ddl(self):
        klass = next(node for node in _tree("chat.py").body if isinstance(node, ast.ClassDef) and node.name == "ChatService")
        constructor = next(node for node in klass.body if isinstance(node, ast.FunctionDef) and node.name == "__init__")
        scan = [n.lineno for n in ast.walk(constructor) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "_retained_ledger_generation"]
        ddl = [n.lineno for n in ast.walk(constructor) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "execute" and n.args and isinstance(n.args[0], ast.Constant)
               and isinstance(n.args[0].value, str) and n.args[0].value.lstrip().startswith(("CREATE", "ALTER", "INSERT", "UPDATE"))]
        self.assertEqual(len(scan), 1)
        self.assertLess(scan[0], min(ddl))

    def test_bad_binding_blocks_new_session_row_before_insert(self):
        db = _ScriptedRows([(PIN_QUERY, (OTHER_GENERATION,))])
        with self.assertRaises(self.host_ns["ChatError"]) as error:
            self.host._bind(db, "fictional-session", "owner", EXPIRY)
        self.assertEqual(error.exception.code, "authorization_denied")
        self.assertEqual(len(db.calls), 1)
        db.complete()

    def test_quarantine_blocks_reservation_and_recovery_before_counters(self):
        for method, arguments in (
            ("_reserve_action", ("fictional-session", "owner", EXPIRY, None, {"state": "preparing"})),
            ("_claim_prepare_recovery", ("fictional-session", "owner", EXPIRY, "action", 1, CONVERSATION)),
        ):
            with self.subTest(method=method):
                db = _Connections([[('BEGIN IMMEDIATE', None)]])
                self.host._connection = db.connect
                self.host._ledger_continuity_approved = False
                with self.assertRaises(self.host_ns["ChatError"]) as error:
                    getattr(self.host, method)(*arguments)
                self.assertEqual(error.exception.code, "action_unverified")
                self.assertEqual(db.used[0].calls, [("BEGIN IMMEDIATE", ())])
                db.complete()

    def test_admission_rechecked_after_handshake_before_tool_or_signing(self):
        owner = self.host._owner_for_subject("fictional-subject")
        initial = [(PIN_QUERY, (GENERATION,)),
                   (SESSION_QUERY, {"owner": owner, "expires": EXPIRY, "revoked": 0, "ledger_generation": GENERATION}),
                   ("SELECT ledger_generation FROM chat_sessions WHERE session_id=?", {"ledger_generation": GENERATION})]
        db = _Connections([initial, _admission_plan(owner), _admission_plan(owner), _admission_plan(owner), [("BEGIN", None)]])
        self.host._connection = db.connect
        self.host._bank = self.rpc
        messages = []

        async def post(client, path, body, **kwargs):
            messages.append(body["method"])
            if body["method"] == "initialize":
                return {"jsonrpc": "2.0", "id": body["id"], "result": {
                    "protocolVersion": self.rpc_ns["PROTOCOL_VERSION"], "capabilities": {"tools": {}},
                    "serverInfo": {"name": "banking-mcp", "version": "fixture"}}}
            self.assertEqual(body["method"], "notifications/initialized")
            self.host._ledger_continuity_approved = False
            return None

        self.rpc._post = post
        with self.assertRaises(self.host_ns["ChatError"]) as error:
            asyncio.run(self.host._bank_post("fictional-subject", "fictional-session", EXPIRY,
                {"operation": "confirm", "conversationId": CONVERSATION, "confirmed": True, "pendingHandle": HANDLE}))
        self.assertEqual(error.exception.code, "action_unverified")
        self.assertIs(error.exception.possibly_sent, False)
        self.assertEqual(messages, ["initialize", "notifications/initialized"])
        self.assertEqual(self.encoder.calls, [])
        db.complete()

    def test_post_confirm_admission_change_stops_receipt_followup(self):
        owner = self.host._owner_for_subject("fictional-subject")
        initial = [(PIN_QUERY, (GENERATION,)),
                   (SESSION_QUERY, {"owner": owner, "expires": EXPIRY, "revoked": 0, "ledger_generation": GENERATION}),
                   ("SELECT ledger_generation FROM chat_sessions WHERE session_id=?", {"ledger_generation": GENERATION})]
        db = _Connections([initial, _admission_plan(owner), _admission_plan(owner), [("BEGIN", None)]])
        self.host._connection = db.connect
        calls = []

        async def call(tool, args, context, **kwargs):
            calls.append(tool)
            self.assertEqual(context.ledger_generation, GENERATION)
            self.host._ledger_continuity_approved = False
            return {"state": "created", "receipt": {"id": "fixture"}}

        self.host._bank = SimpleNamespace(call=call)
        with self.assertRaises(self.host_ns["ChatError"]) as error:
            asyncio.run(self.host._bank_post("fictional-subject", "fictional-session", EXPIRY,
                {"operation": "confirm", "conversationId": CONVERSATION, "confirmed": True, "pendingHandle": HANDLE}))
        self.assertEqual(error.exception.code, "action_unverified")
        self.assertIs(error.exception.possibly_sent, True)
        self.assertEqual(calls, ["confirm_simulated_intake"])
        db.complete()

    def test_continuity_errors_propagate_without_confirm_or_handoff_followups(self):
        for operation, expected_tool in (("confirm", "confirm_simulated_intake"), ("handoff", "create_verified_handoff")):
            for code in ("authorization_denied", "action_unverified"):
                with self.subTest(operation=operation, code=code):
                    calls = []

                    async def call(tool, args, context, **kwargs):
                        calls.append(tool)
                        raise self.rpc_ns["BankRPCError"](code, possibly_sent=True)

                    controller = self.controller_ns["BankController"](SimpleNamespace(call=call))
                    payload = ({"operation": "confirm", "confirmed": True, "pendingHandle": HANDLE}
                               if operation == "confirm" else {"operation": "handoff", "reason": "customer_request",
                                                               "requestId": OPERATION, "unanswered_questions": []})
                    with self.assertRaises(self.rpc_ns["BankRPCError"]) as error:
                        asyncio.run(controller.execute(payload, _context(self.rpc_ns)))
                    self.assertEqual((error.exception.code, error.exception.possibly_sent), (code, True))
                    self.assertEqual(calls, [expected_tool])

    def test_readback_continuity_error_preserves_uncertainty_without_retry(self):
        for code in ("authorization_denied", "action_unverified"):
            with self.subTest(code=code):
                calls = []

                async def call(tool, args, context, **kwargs):
                    calls.append(tool)
                    if tool == "confirm_simulated_intake":
                        return {"state": "created", "receipt": {"id": "fixture"}}
                    raise self.rpc_ns["BankRPCError"](code, possibly_sent=False)

                controller = self.controller_ns["BankController"](SimpleNamespace(call=call))
                with self.assertRaises(self.rpc_ns["BankRPCError"]) as error:
                    asyncio.run(controller.execute({"operation": "confirm", "confirmed": True, "pendingHandle": HANDLE},
                                                   _context(self.rpc_ns)))
                self.assertEqual((error.exception.code, error.exception.possibly_sent), (code, True))
                self.assertEqual(calls, ["confirm_simulated_intake", "read_intake_receipt"])

    def test_original_outbox_generation_used_during_quarantine_and_current_pin_change(self):
        owner = self.host._owner_for_subject("fictional-subject")
        outbox = {"subject": "fictional-subject", "owner": owner, "expires": EXPIRY, "ledger_generation": GENERATION}
        binding = {**outbox, "customer_id": "fictional-customer", "bank_context_id": CONVERSATION}
        self.host._ledger_generation = OTHER_GENERATION
        self.host._ledger_continuity_approved = False
        self.host._action_enabled = False
        self.host._claim_revoke = lambda session: (outbox, "fixture-lease")
        db = _Connections([[("SELECT owner,expires,subject,customer_id,bank_context_id,ledger_generation FROM chat_sessions WHERE session_id=?", binding)]])
        self.host._connection = db.connect
        contexts = []
        finishes = []

        async def revoke(context, **kwargs):
            contexts.append(context)
            raise self.rpc_ns["BankRPCError"]("authorization_denied", possibly_sent=True)

        def finish(session, lease, *, expected_intent, confirmed, error_code=None):
            finishes.append((session, lease, expected_intent, confirmed, error_code))
            return "pending"

        self.host._bank = SimpleNamespace(revoke=revoke)
        self.host._finish_revoke = finish
        self.assertEqual(asyncio.run(self.host.attempt_revoke("fictional-session")), "pending")
        self.assertEqual(len(contexts), 1)
        self.assertEqual(contexts[0].ledger_generation, GENERATION)
        self.assertIsNone(contexts[0].admission_check)
        self.assertEqual(finishes, [("fictional-session", "fixture-lease",
                                    (owner, "fictional-subject", EXPIRY, GENERATION), False, "authorization_denied")])
        db.complete()

    def test_mismatched_outbox_binding_never_dispatches_or_confirms(self):
        owner = self.host._owner_for_subject("fictional-subject")
        outbox = {"subject": "fictional-subject", "owner": owner, "expires": EXPIRY, "ledger_generation": GENERATION}
        binding = {**outbox, "ledger_generation": OTHER_GENERATION, "customer_id": "fictional-customer", "bank_context_id": CONVERSATION}
        self.host._claim_revoke = lambda session: (outbox, "fixture-lease")
        db = _Connections([[("SELECT owner,expires,subject,customer_id,bank_context_id,ledger_generation FROM chat_sessions WHERE session_id=?", binding)]])
        self.host._connection = db.connect
        calls = []
        self.host._bank = SimpleNamespace(revoke=lambda *args, **kwargs: calls.append(args))
        finishes = []
        self.host._finish_revoke = lambda session, lease, **kwargs: finishes.append(kwargs) or "pending"
        self.assertEqual(asyncio.run(self.host.attempt_revoke("fictional-session")), "pending")
        self.assertEqual(calls, [])
        self.assertEqual(finishes, [{"expected_intent": (owner, "fictional-subject", EXPIRY, GENERATION),
                                    "confirmed": False, "error_code": "revoke_configuration_unavailable"}])
        db.complete()

    def test_late_revoke_ack_never_updates_replacement_generation_or_owner(self):
        intent = ("fictional-owner", "fictional-subject", EXPIRY, GENERATION)
        query = "SELECT owner,subject,expires,ledger_generation,state,attempts,lease_token FROM pending_revocations WHERE session_id=?"
        for owner, generation in (("replacement-owner", GENERATION), ("fictional-owner", OTHER_GENERATION)):
            for confirmed in (True, False):
                with self.subTest(owner=owner, generation=generation, confirmed=confirmed):
                    row = {"owner": owner, "subject": "fictional-subject", "expires": EXPIRY,
                           "ledger_generation": generation, "state": "pending", "attempts": 1,
                           "lease_token": "replacement-lease"}
                    db = _Connections([[('BEGIN IMMEDIATE', None), (query, row)]])
                    self.host._connection = db.connect
                    state = self.host._finish_revoke("fictional-session", "expired-lease", expected_intent=intent,
                                                    confirmed=confirmed, error_code="authorization_denied")
                    self.assertEqual(state, "unresolved")
                    self.assertEqual(len(db.used[0].calls), 2)
                    db.complete()

    def test_same_original_late_revoke_ack_can_confirm_after_lease_expiry(self):
        intent = ("fictional-owner", "fictional-subject", EXPIRY, GENERATION)
        row = {"owner": intent[0], "subject": intent[1], "expires": intent[2], "ledger_generation": intent[3],
               "state": "expired_unconfirmed", "attempts": 2, "lease_token": "newer-lease"}
        db = _Connections([[('BEGIN IMMEDIATE', None),
            ("SELECT owner,subject,expires,ledger_generation,state,attempts,lease_token FROM pending_revocations WHERE session_id=?", row),
            ("UPDATE pending_revocations SET state='confirmed',lease_token=NULL, lease_until=0,last_error_code=NULL,updated_at=? WHERE session_id=?", None)]])
        self.host._connection = db.connect
        self.assertEqual(self.host._finish_revoke("fictional-session", "expired-lease", expected_intent=intent,
                                                 confirmed=True), "confirmed")
        self.assertEqual(db.used[0].calls[-1][1], (NOW, "fictional-session"))
        db.complete()

    def test_recovery_refund_only_matches_own_reserved_attempt(self):
        for current_attempt, should_update in ((3, False), (2, True)):
            with self.subTest(current_attempt=current_attempt):
                row = {"action_id": "fictional-action", "revision": 4, "prepare_recovery_attempts": current_attempt}
                # The callbacks identify a previously selected action row. They
                # do not synthesize/reconcile the host FSM or parse SQL.
                self.host._action_row = lambda *args: row
                self.host._action_result = lambda supplied: {"state": "prepare_unverified"}
                steps = [('BEGIN IMMEDIATE', None), (PIN_QUERY, (GENERATION,)),
                         (SESSION_QUERY, {"owner": "fictional-owner", "expires": EXPIRY, "revoked": 0,
                                          "ledger_generation": GENERATION})]
                if should_update:
                    steps.append(("UPDATE action_status SET prepare_recovery_attempts=?, prepare_recovery_after=? WHERE session_id=? AND action_id=? AND revision=?", None))
                db = _Connections([steps])
                self.host._connection = db.connect
                self.host._release_rejected_prepare_recovery("fictional-session", "fictional-owner", EXPIRY,
                                                              "fictional-action", 4, 2)
                if should_update:
                    self.assertEqual(db.used[0].calls[-1][1], (1, NOW + 2, "fictional-session", "fictional-action", 4))
                else:
                    self.assertEqual(len(db.used[0].calls), 3)
                db.complete()


if __name__ == "__main__":
    unittest.main()
