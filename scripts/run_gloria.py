"""Serve an isolated admitted Gloria application through restricted native stages.

Frontend inquiry and explicit action controls share one dataset and durable
sandbox ledger. Private configuration stays outside source.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from frontend.server.config import Settings
from frontend.server.app import create_app
from banking_mcp.config import load_config
from banking_mcp.service import Service
from gloria_workflow.action_host import BankingActionHost
from gloria_workflow.host import GloriaHostFactory, RepositoryBank
from gloria_workflow.prompts import StageAdapters
from gloria_workflow.runtime import Workflow
from scripts.native_gloria_qualification import NativeGloriaPort


class NativeHostFactory(GloriaHostFactory):
    def __init__(self, state_path, bank_service, native_url, authority_dir, *, source_root=None,
                 batch_preflight=False):
        super().__init__(None, state_path, bank_service=bank_service, source_root=source_root)
        self.native_url, self.authority_dir = native_url, authority_dir
        self.batch_preflight = batch_preflight

    def __call__(self, repository, chat, profile, sid, expiry):
        bank = RepositoryBank(repository, chat, profile, sid, expiry,
            bank_service=self.bank_service, source_root=self.source_root)
        return NativeGloriaPort(lambda model: Workflow(
            StageAdapters(model, timeout_seconds=90, batch_preflight=self.batch_preflight),
            bank, self.store), self.native_url, self.authority_dir)


def application(settings, bank_config, state, native_url, authority_dir, *, source_root=None,
                enable_simulated_intake=False, batch_preflight=False):
    state, authority_dir = Path(state).resolve(), Path(authority_dir).resolve()
    if state == settings.state_dir.resolve() or settings.state_dir.resolve() in state.parents:
        raise ValueError("independent application state directory required")
    if bank_config.state_db.resolve().parent != state:
        raise ValueError("the explicitly configured sandbox ledger must belong to this instance")
    if bank_config.data_dir.resolve() != settings.data_dir.resolve():
        raise ValueError("frontend and bank must share the same serving dataset")
    if bank_config.mode != "delegated" or bank_config.principal_customers != settings.chat.get("principal_customers"):
        raise ValueError("frontend and bank require the same explicit delegated customer mapping")
    if not (authority_dir / "admissions.json").is_file() or not (authority_dir / "native-profile.json").is_file():
        raise ValueError("installed isolated native authority directory required")
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    bank = Service(bank_config)
    try:
        factory = NativeHostFactory(state / "gloria-workflow.sqlite3", bank, native_url, authority_dir,
            source_root=source_root, batch_preflight=batch_preflight)
        backend = BankingActionHost(bank, factory.store, source_root=source_root)
        configured = replace(settings, state_dir=state,
            chat={**settings.chat, "mode": "gloria-host/v1", "ledger_generation": factory.ledger_generation,
                  "action_enabled": enable_simulated_intake})
        return create_app(configured, gloria_factory=factory, bank_backend=backend), bank
    except BaseException:
        bank.close()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--bank-config-file", required=True)
    parser.add_argument("--native-url", required=True)
    parser.add_argument("--native-authority-dir", required=True)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--enable-simulated-intake", action="store_true")
    parser.add_argument("--batch-preflight", action="store_true")
    parser.add_argument("--port", type=int, default=43900)
    args = parser.parse_args()
    if not 1024 < args.port < 65536:
        parser.error("private loopback port required")
    app, bank = application(Settings.from_env(), load_config(args.bank_config_file), args.state_dir,
        args.native_url, args.native_authority_dir, source_root=args.source_root,
        enable_simulated_intake=args.enable_simulated_intake, batch_preflight=args.batch_preflight)
    try:
        import uvicorn
        uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)
    finally:
        bank.close()


if __name__ == "__main__":
    main()
