"""Remote container entrypoint. No secrets or raw process logs are retained."""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import sys

from contract import CheckpointError, require, require_runtime_release
from scenarios import run, run_stock, run_confirm_loss


def main() -> int:
    require_runtime_release(dict(os.environ))
    root = Path("/run/synthetic-integration/state")
    root.mkdir(mode=0o700)
    # This provider is a pending reviewed dependency, absent from bank71/FLUJO51.
    results = []
    active_phase = "startup"
    result = {"status": "failed", "failure": "fixture_startup_failed"}
    try:
        factory = importlib.import_module("integration_provider").Provider
        mode = os.environ.get("SCENARIO_MODE")
        require(mode == "stock-and-authored-coverage", "scenario_mode_invalid")
        for phase, probes in (("stock-missing-coverage", run_stock), ("authored-empty-history", run),
                              ("authored-confirm-response-loss", run_confirm_loss)):
            active_phase = phase
            provider = factory(root / phase, phase=phase)
            try:
                provider.start()
                results.append({"phase": phase, **probes(provider)})
            finally:
                provider.stop()
        result = {"status": "passed", "proof_kind": "deterministic_fixture_provider_api_assembly_safety",
                  "phases": results,
                  "unproven": ["real_model_es_pt", "human_adjudication", "customer_acceptance",
                               "observed_24h_operation", "future_business_clock_r16",
                               "browser_ui", "capacity", "held_out_baseline_comparison", "shared_deployment"]}
    except CheckpointError:
        result = {"status": "failed", "failure": "scenario_assertion_failed"}
    except Exception:
        result = {"status": "failed", "failure": "runtime_probe_failed"}
    finally:
        result.update(phases=results, last_phase=active_phase, surface="api_only")
        Path("/evidence/observations.json").write_text(json.dumps(result, indent=2) + "\n",
                                                       encoding="utf-8")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        print("Synthetic checkpoint refused before observations.")
        sys.exit(1)
