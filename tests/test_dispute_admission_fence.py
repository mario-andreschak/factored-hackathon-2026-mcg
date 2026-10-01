"""Real frontend logout and bank intake must share a durable admission order."""
import asyncio
from contextlib import contextmanager
import json
import sqlite3
import threading

import pytest

from frontend.server.chat import ChatError
from tests.test_dispute_action_host import joined
from tests.test_dispute_bank_read import bank, dataset


def start_call(name, call):
    outcome, done = {}, threading.Event()

    def run():
        try:
            outcome["result"] = call()
        except BaseException as error:
            outcome["error"] = error
        finally:
            done.set()

    thread = threading.Thread(target=run, name=name, daemon=True)
    thread.start()
    return thread, outcome, done


def assert_finished(thread, done):
    thread.join(timeout=12)
    assert done.is_set() and not thread.is_alive(), "admission/logout lock order deadlocked"


def ledger_counts(joined):
    # Observe committed state without waiting on the paused bank writer's
    # in-process connection gate. SQLite WAL permits this independent reader.
    uri = joined.bank.service.store.path.as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=1) as db:
        return (db.execute("SELECT count(*) FROM sandbox_cases").fetchone()[0],
                db.execute("SELECT count(*) FROM sandbox_case_receipts").fetchone()[0])


def frontend_revoked(joined):
    with joined.chat._connection() as db:
        return db.execute("SELECT revoked FROM chat_sessions WHERE session_id=?",
                          (joined.sid,)).fetchone()[0]


def test_revocation_committed_after_initial_admission_blocks_bank_writer(joined, monkeypatch):
    pending = asyncio.run(joined.prepare())
    assert pending["state"] == "pending_confirmation"
    admitted, release = threading.Event(), threading.Event()
    original = joined.backend._execute_admitted

    def pause_before_frontend_writer(*args):
        admitted.set()
        assert release.wait(8), "test never released admitted bank action"
        return original(*args)

    monkeypatch.setattr(joined.backend, "_execute_admitted", pause_before_frontend_writer)
    thread, outcome, done = start_call("confirm-before-revoke", lambda:
        asyncio.run(joined.confirm(pending["pending_handle"])))
    try:
        assert admitted.wait(5), "confirmation never reached its trusted host"
        assert joined.chat.queue_revoke(joined.customer, joined.sid, joined.expiry) == "pending"
        assert frontend_revoked(joined) == 1
        # The remote revocation queue has not run; the local durable row alone
        # must fence the write after the earlier admission was successful.
        with joined.bank.service.store.connect() as db:
            assert db.execute("SELECT count(*) FROM revoked WHERE session=?",
                              (joined.sid,)).fetchone()[0] == 0
    finally:
        release.set()
        assert_finished(thread, done)
    assert isinstance(outcome.get("error"), ChatError), outcome
    assert ledger_counts(joined) == (0, 0)


def test_overlapping_logout_waits_for_case_commit_and_verified_readback(joined, monkeypatch):
    pending = asyncio.run(joined.prepare())
    assert pending["state"] == "pending_confirmation"
    writer_ready, release_writer = threading.Event(), threading.Event()
    receipt_ready, release_receipt = threading.Event(), threading.Event()
    logout_attempted = threading.Event()
    actions = joined.bank.service.actions
    eligible, receipt, connection = actions._assert_intake_eligible, actions.receipt, joined.chat._connection
    calls, observed_receipt = [], {}

    def pause_final_bank_writer(*args):
        calls.append(1)
        if len(calls) == 2:
            writer_ready.set()
            assert release_writer.wait(8), "test never released final bank writer"
        return eligible(*args)

    def pause_verified_readback(*args):
        result = receipt(*args)
        observed_receipt.update(result)
        receipt_ready.set()
        assert release_receipt.wait(8), "test never released verified receipt readback"
        return result

    @contextmanager
    def observe_logout_begin():
        with connection() as db:
            if threading.current_thread().name == "overlapping-logout":
                def trace(statement):
                    if statement == "BEGIN IMMEDIATE":
                        logout_attempted.set()
                db.set_trace_callback(trace)
            yield db

    monkeypatch.setattr(actions, "_assert_intake_eligible", pause_final_bank_writer)
    monkeypatch.setattr(actions, "receipt", pause_verified_readback)
    monkeypatch.setattr(joined.chat, "_connection", observe_logout_begin)
    confirm_thread, confirmed, confirm_done = start_call("confirm-before-logout", lambda:
        asyncio.run(joined.confirm(pending["pending_handle"])))
    logout_thread = None
    try:
        assert writer_ready.wait(5), "confirmation never reached final case writer"
        assert ledger_counts(joined) == (0, 0)
        # This independently proves a real SQLite writer lock is already held;
        # a thread scheduling delay cannot make the blocked-logout check pass.
        with sqlite3.connect(joined.chat._db_path, timeout=0) as db:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                db.execute("BEGIN IMMEDIATE")
        logout_thread, revoked, logout_done = start_call("overlapping-logout", lambda:
            joined.chat.queue_revoke(joined.customer, joined.sid, joined.expiry))
        assert logout_attempted.wait(3), "logout never attempted its durable writer lock"
        assert not logout_done.wait(.1)
        assert frontend_revoked(joined) == 0
        release_writer.set()
        assert receipt_ready.wait(5), "bank commit did not reach durable receipt readback"
        assert observed_receipt["state"] == "created"
        assert ledger_counts(joined) == (1, 1)
        with joined.bank.service.store.connect() as db:
            saved = json.loads(db.execute("SELECT receipt_json FROM sandbox_case_receipts").fetchone()[0])
        assert observed_receipt["receipt"] == saved
        assert not logout_done.wait(.1)
        assert frontend_revoked(joined) == 0
    finally:
        release_writer.set()
        release_receipt.set()
        assert_finished(confirm_thread, confirm_done)
        if logout_thread is not None:
            assert_finished(logout_thread, logout_done)
    assert "error" not in revoked, revoked
    assert revoked["result"] == "pending"
    assert frontend_revoked(joined) == 1
    assert ledger_counts(joined) == (1, 1)
    assert len(calls) == 2
    # Logout may win the final display check after the correctly ordered bank
    # commit; the caller then gets a fixed session error instead of a receipt.
    if "error" in confirmed:
        assert isinstance(confirmed["error"], ChatError), confirmed
        assert confirmed["error"].code in {"action_authorization_failed", "session_expired"}
    else:
        assert confirmed["result"]["state"] == "intake_verified"
