"""Pure validator tests: no banking import, MCP launch, Docker, data or providers."""
from __future__ import annotations

import copy
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("package_verifier", Path(__file__).with_name("verify_installed.py"))
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


class ToolInventoryTests(unittest.TestCase):
    def setUp(self):
        self.schemas = {name: {"type": "object", "additionalProperties": False}
                        for name in verifier.READ_TOOLS | verifier.HOST_ACTION_TOOLS}
        self.tools = [{"name": name, "inputSchema": schema,
                       "annotations": {"readOnlyHint": name not in verifier.WRITE_HINT_TOOLS,
                                       "destructiveHint": False, "idempotentHint": True,
                                       "openWorldHint": False}}
                      for name, schema in self.schemas.items()]

    def test_exact_eight_names_and_installed_schema(self):
        result = verifier.validate_tool_inventory(self.tools, self.schemas)
        self.assertEqual([tool["name"] for tool in result], sorted(self.schemas))

    def test_reject_duplicate_name_even_if_length_is_eight(self):
        self.tools[-1] = copy.deepcopy(self.tools[0])
        with self.assertRaisesRegex(verifier.PreflightError, "inventory_mismatch"):
            verifier.validate_tool_inventory(self.tools, self.schemas)

    def test_reject_hidden_generic_tool_and_missing_action(self):
        self.tools[-1]["name"] = "filesystem_read"
        with self.assertRaisesRegex(verifier.PreflightError, "inventory_mismatch"):
            verifier.validate_tool_inventory(self.tools, self.schemas)

    def test_reject_schema_or_annotation_drift(self):
        with self.subTest("schema"):
            altered = copy.deepcopy(self.tools)
            altered[0]["inputSchema"]["additionalProperties"] = True
            with self.assertRaisesRegex(verifier.PreflightError, "input_schema_mismatch"):
                verifier.validate_tool_inventory(altered, self.schemas)
        with self.subTest("annotation"):
            altered = copy.deepcopy(self.tools)
            altered[0]["annotations"]["openWorldHint"] = True
            with self.assertRaisesRegex(verifier.PreflightError, "annotation_mismatch"):
                verifier.validate_tool_inventory(altered, self.schemas)


class SourceManifestTests(unittest.TestCase):
    def setUp(self):
        self.installed = [{"path": name, "sha256": "a" * 64} for name in (
            "banking_mcp/__init__.py", "pipeline/__init__.py", "pipeline/contracts.yaml",
            "requirements-mcp.txt", "requirements-pipeline.txt", "requirements-s3.txt")]
        self.manifest = {"schema_version": 1, "proof_kind": "source-context",
                         "bank_source_revision": verifier.PINNED_BANK_SOURCE,
                         "candidate_ci_head": "b" * 40,
                         "runtime_files": [{**item, "source_revision": verifier.PINNED_BANK_SOURCE}
                                           for item in self.installed],
                         "requirements": {"entrypoint": "requirements-mcp.txt", "aggregate_sha256": "d" * 64,
                                          "files": [item["path"] for item in self.installed
                                                    if item["path"].startswith("requirements")]},
                         "runtime_tree_sha256": "e" * 64,
                         "core_drift_check": {"status": "unchanged", "compared_revision": "b" * 40,
                                              "paths": [item["path"] for item in self.installed]}}

    def test_candidate_and_bank_source_revisions_stay_distinct(self):
        result = verifier.validate_source_manifest(self.manifest, self.installed, verifier.PINNED_BANK_SOURCE)
        self.assertEqual(result["bank_source_revision"], verifier.PINNED_BANK_SOURCE)
        self.assertEqual(result["candidate_ci_head"], "b" * 40)
        self.assertEqual(len(result["requirements"]), 3)

    def test_reject_changed_missing_or_extra_installed_source(self):
        alternatives = [self.installed[:-1], [*self.installed, {"path": "pipeline/unknown.py", "sha256": "c" * 64}]]
        changed = copy.deepcopy(self.installed)
        changed[0]["sha256"] = "c" * 64
        alternatives.append(changed)
        for installed in alternatives:
            with self.subTest(installed=installed):
                with self.assertRaisesRegex(verifier.PreflightError, "installed_source_bytes_mismatch"):
                    verifier.validate_source_manifest(self.manifest, installed, verifier.PINNED_BANK_SOURCE)

    def test_reject_revision_substitution_and_candidate_core_drift(self):
        for mutation in (lambda manifest: manifest.update(bank_source_revision="c" * 40),
                         lambda manifest: manifest["core_drift_check"].update(status="changed")):
            altered = copy.deepcopy(self.manifest)
            mutation(altered)
            with self.assertRaises(verifier.PreflightError):
                verifier.validate_source_manifest(altered, self.installed, verifier.PINNED_BANK_SOURCE)

    def test_manifest_cannot_escape_installed_root(self):
        for path in ("../private/config.json", "/run/secrets/banking.json", "banking_mcp\\config.py", "pipeline//fixture.py"):
            with self.subTest(path=path):
                with self.assertRaisesRegex(verifier.PreflightError, "invalid_manifest_path"):
                    verifier.safe_relative_path(path)

    def test_installed_inventory_includes_contracts_but_ignores_bytecode(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for package in verifier.IMPORTED_PACKAGES:
                (root / package / "__pycache__").mkdir(parents=True)
                (root / package / "__init__.py").write_text("", encoding="utf-8")
                (root / package / "__pycache__" / "__init__.pyc").write_bytes(b"cache")
            (root / "pipeline" / "contracts.yaml").write_text("tables: {}", encoding="utf-8")
            (root / "requirements-mcp.txt").write_text("mcp==1.30.0", encoding="utf-8")
            rows = verifier.installed_source_inventory(root)
            self.assertEqual({row["path"] for row in rows}, {
                "banking_mcp/__init__.py", "pipeline/__init__.py", "pipeline/contracts.yaml", "requirements-mcp.txt"})

    def test_reject_aggregate_receipt_hash_that_disagrees_with_installed_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for item in self.installed:
                path = root / item["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("generated-test-bytes", encoding="utf-8")
            paths = [item["path"] for item in self.installed]
            self.manifest["runtime_tree_sha256"] = verifier.context_tree_sha256(root, paths)
            self.manifest["requirements"]["aggregate_sha256"] = verifier.context_tree_sha256(
                root, self.manifest["requirements"]["files"])
            verifier.verify_context_aggregate_hashes(root, self.manifest, self.installed)
            self.manifest["requirements"]["aggregate_sha256"] = "c" * 64
            with self.assertRaisesRegex(verifier.PreflightError, "aggregate_bytes_mismatch"):
                verifier.verify_context_aggregate_hashes(root, self.manifest, self.installed)


class RemoteGuardTests(unittest.TestCase):
    def test_missing_remote_ci_flag_refuses_before_runtime_imports_or_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            receipt_dir = Path(temporary) / "must-not-exist"
            before = {name for name in sys.modules if name.startswith(("banking_mcp", "pipeline", "mcp"))}
            with patch.dict(os.environ, {}, clear=True):
                result = verifier.main(["--receipt-dir", str(receipt_dir),
                                        "--expected-source-revision", verifier.PINNED_BANK_SOURCE])
            after = {name for name in sys.modules if name.startswith(("banking_mcp", "pipeline", "mcp"))}
            self.assertEqual(result, 1)
            self.assertEqual(after, before)
            self.assertFalse(receipt_dir.exists())


if __name__ == "__main__":
    unittest.main()
