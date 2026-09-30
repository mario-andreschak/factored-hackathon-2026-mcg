"""Pure validator tests: no banking import, MCP launch, Docker, data or providers."""
from __future__ import annotations

import copy
import importlib.util
import os
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("package_verifier", Path(__file__).with_name("verify_installed.py"))
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


class ToolInventoryTests(unittest.TestCase):
    def setUp(self):
        self.schemas = {name: {"type": "object", "additionalProperties": False}
                        for name in verifier.READ_TOOLS | verifier.HOST_ACTION_TOOLS}
        self.schemas["create_verified_handoff"].update({"properties": {
            "reason": {"type": "string"}, "unanswered_questions": {"type": "array", "maxItems": 8,
                "items": {"type": "string", "minLength": 1, "maxLength": 240}}}, "required": ["reason"]})
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

    def test_independent_question_bounds_reject_drift_even_when_installed_schema_matches(self):
        mutations = [lambda schema: schema["properties"].pop("unanswered_questions"),
            lambda schema: schema["required"].append("unanswered_questions"),
            lambda schema: schema["properties"]["unanswered_questions"].update(type="string"),
            lambda schema: schema["properties"]["unanswered_questions"].update(maxItems=9),
            lambda schema: schema["properties"]["unanswered_questions"].update(minItems=1),
            lambda schema: schema["properties"]["unanswered_questions"].update(default=["question"]),
            lambda schema: schema["properties"]["unanswered_questions"]["items"].update(type="number"),
            lambda schema: schema["properties"]["unanswered_questions"]["items"].update(minLength=0),
            lambda schema: schema["properties"]["unanswered_questions"]["items"].update(minLength=True),
            lambda schema: schema["properties"]["unanswered_questions"]["items"].update(maxLength=241),
            lambda schema: schema.update(additionalProperties=True)]
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                schemas = copy.deepcopy(self.schemas)
                mutate(schemas["create_verified_handoff"])
                tools = copy.deepcopy(self.tools)
                for tool in tools:
                    tool["inputSchema"] = schemas[tool["name"]]
                with self.assertRaisesRegex(verifier.PreflightError, "handoff_questions_contract_mismatch"):
                    verifier.validate_tool_inventory(tools, schemas)

    def test_optional_schema_default_is_not_invented(self):
        schema = self.schemas["create_verified_handoff"]
        self.assertFalse(verifier.validate_handoff_question_schema(schema)["default_in_schema"])
        schema["properties"]["unanswered_questions"]["default"] = []
        self.assertTrue(verifier.validate_handoff_question_schema(schema)["default_in_schema"])
        verifier.validate_handoff_question_default([])
        for value in (None, (), False, ["question"]):
            with self.subTest(value=value), self.assertRaisesRegex(verifier.PreflightError, "questions_default_mismatch"):
                verifier.validate_handoff_question_default(value)


class SourceManifestTests(unittest.TestCase):
    def setUp(self):
        self.installed = [{"path": name, "sha256": "a" * 64} for name in (
            "banking_mcp/__init__.py", "pipeline/__init__.py", "pipeline/contracts.yaml",
            "requirements-mcp.txt", "requirements-pipeline.txt", "requirements-s3.txt")]
        self.manifest = {"schema_version": 2, "checkpoint": verifier.CHECKPOINT, "proof_kind": "source-context",
                         "bank_source_revision": verifier.PINNED_BANK_SOURCE,
                         "reviewed_bank_source_revision": verifier.REVIEWED_BANK_SOURCE,
                         "audited_bank_source_revision": verifier.AUDITED_BANK_SOURCE,
                         "candidate_ci_head": "b" * 40,
                         "runtime_files": [{**item, "source_revision": verifier.PINNED_BANK_SOURCE}
                                           for item in self.installed],
                         "requirements": {"entrypoint": "requirements-mcp.txt", "aggregate_sha256": "d" * 64,
                                          "files": [item["path"] for item in self.installed
                                                    if item["path"].startswith("requirements")]},
                         "runtime_tree_sha256": "e" * 64,
                         "core_drift_check": {"status": "unchanged", "compared_revision": "b" * 40,
                                              "paths": [item["path"] for item in self.installed]},
                         "reviewed_runtime_equivalence": {"status": "unchanged",
                             "reviewed_revision": verifier.REVIEWED_BANK_SOURCE,
                             "installed_revision": verifier.PINNED_BANK_SOURCE,
                             "compared_paths": [item["path"] for item in self.installed],
                             "reviewed_runtime_sha256": "e" * 64, "installed_runtime_sha256": "e" * 64,
                             "scope": verifier.REVIEWED_EQUIVALENCE_SCOPE},
                         "audited_runtime_equivalence": {"status": "unchanged",
                             "audited_revision": verifier.AUDITED_BANK_SOURCE,
                             "reviewed_revision": verifier.REVIEWED_BANK_SOURCE,
                             "compared_paths": [item["path"] for item in self.installed],
                             "audited_runtime_sha256": "e" * 64, "reviewed_runtime_sha256": "e" * 64,
                             "scope": verifier.REVIEWED_EQUIVALENCE_SCOPE}}

    def test_candidate_and_bank_source_revisions_stay_distinct(self):
        result = verifier.validate_source_manifest(self.manifest, self.installed, verifier.PINNED_BANK_SOURCE)
        self.assertEqual(result["bank_source_revision"], verifier.PINNED_BANK_SOURCE)
        self.assertEqual(result["candidate_ci_head"], "b" * 40)
        self.assertEqual(result["reviewed_bank_source_revision"], verifier.REVIEWED_BANK_SOURCE)
        self.assertEqual(result["audited_bank_source_revision"], verifier.AUDITED_BANK_SOURCE)
        self.assertEqual(verifier.PINNED_BANK_SOURCE, "71ac0f020303abfd0073302a148752f0d2c9f23b")
        self.assertEqual(verifier.REVIEWED_BANK_SOURCE, "ccaedb71d127b9aae273da1ec4b9ebe7b4db8d9a")
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

    def test_old_receipt_or_source_pin_cannot_substitute_for_v2(self):
        for mutate in (lambda value: value.update(schema_version=1),
                       lambda value: value.update(checkpoint="banking-package/v1"),
                       lambda value: value.update(bank_source_revision="529bcca2ae83a705e8c372a065602f3e27fa11da"),
                       lambda value: value.update(bank_source_revision="80fce6aaff4149e2f292a9709e6963686da6dd4a"),
                       lambda value: value["runtime_files"][0].update(source_revision="529bcca2ae83a705e8c372a065602f3e27fa11da")):
            with self.subTest(mutation=mutate):
                manifest = copy.deepcopy(self.manifest)
                mutate(manifest)
                with self.assertRaises(verifier.PreflightError):
                    verifier.validate_source_manifest(manifest, self.installed, verifier.PINNED_BANK_SOURCE)

    def test_reviewed_source_identity_and_closure_equivalence_must_match(self):
        for mutate in (lambda value: value.pop("reviewed_bank_source_revision"),
                       lambda value: value.pop("reviewed_runtime_equivalence"),
                       lambda value: value["reviewed_runtime_equivalence"].update(status="changed"),
                       lambda value: value["reviewed_runtime_equivalence"].update(reviewed_revision="c" * 40),
                       lambda value: value["reviewed_runtime_equivalence"].update(installed_revision="c" * 40),
                       lambda value: value["reviewed_runtime_equivalence"].update(compared_paths=[]),
                       lambda value: value["reviewed_runtime_equivalence"]["compared_paths"].append("pipeline/contracts.yaml"),
                       lambda value: value["reviewed_runtime_equivalence"].update(reviewed_runtime_sha256="c" * 64),
                       lambda value: value["reviewed_runtime_equivalence"].update(installed_runtime_sha256="c" * 64),
                       lambda value: value["reviewed_runtime_equivalence"].pop("scope"),
                       lambda value: value["reviewed_runtime_equivalence"].update(scope="whole repository matches")):
            with self.subTest(mutation=mutate):
                manifest = copy.deepcopy(self.manifest)
                mutate(manifest)
                with self.assertRaises(verifier.PreflightError):
                    verifier.validate_source_manifest(manifest, self.installed, verifier.PINNED_BANK_SOURCE)

    def test_driver_must_be_the_new_v2_source_path_and_candidate_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            driver = Path(temporary) / "verify_installed.py"
            driver.write_text("pure synthetic driver bytes", encoding="utf-8")
            manifest = {"candidate_ci_head": "b" * 40, "packaging_files": [{
                "path": "scripts/package_issue21_preflight/verify_installed.py",
                "source_revision": "b" * 40, "sha256": verifier.file_sha256(driver)}]}
            result = verifier.verify_driver_source(manifest, driver)
            self.assertEqual(result["path"], "scripts/package_issue21_preflight/verify_installed.py")
            manifest["packaging_files"][0]["path"] = "scripts/package_preflight/verify_installed.py"
            with self.assertRaisesRegex(verifier.PreflightError, "verifier_source_mismatch"):
                verifier.verify_driver_source(manifest, driver)

    def test_audited_runtime_lineage_must_match_final_reviewed_source(self):
        mutations = (lambda value: value.pop("audited_bank_source_revision"),
            lambda value: value.update(audited_bank_source_revision="c" * 40),
            lambda value: value.pop("audited_runtime_equivalence"),
            lambda value: value["audited_runtime_equivalence"].update(status="changed"),
            lambda value: value["audited_runtime_equivalence"].update(audited_revision="c" * 40),
            lambda value: value["audited_runtime_equivalence"].update(reviewed_revision="c" * 40),
            lambda value: value["audited_runtime_equivalence"].update(compared_paths=[]),
            lambda value: value["audited_runtime_equivalence"]["compared_paths"].append("pipeline/contracts.yaml"),
            lambda value: value["audited_runtime_equivalence"].update(audited_runtime_sha256="c" * 64),
            lambda value: value["audited_runtime_equivalence"].update(reviewed_runtime_sha256="c" * 64),
            lambda value: value["audited_runtime_equivalence"].pop("scope"),
            lambda value: value["audited_runtime_equivalence"].update(scope="whole source tree equivalent"))
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                manifest = copy.deepcopy(self.manifest)
                mutate(manifest)
                with self.assertRaises(verifier.PreflightError):
                    verifier.validate_source_manifest(manifest, self.installed, verifier.PINNED_BANK_SOURCE)

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


class EmptyStateTests(unittest.TestCase):
    """SQLite fixtures contain fictional schemas only; no StateStore import."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.state = Path(self.temporary.name) / "fixture.db"
        with closing(sqlite3.connect(self.state)) as connection, connection:
            for table in verifier.EMPTY_STATE_TABLES:
                if table == "action_pending":
                    connection.execute("CREATE TABLE action_pending(id TEXT, request_key TEXT, confirmation_state TEXT)")
                    connection.execute("CREATE UNIQUE INDEX action_pending_request_key ON action_pending(request_key)")
                elif table == "sandbox_handoffs":
                    connection.execute("CREATE TABLE sandbox_handoffs(id TEXT, packet_json TEXT)")
                elif table == "sandbox_case_receipts":
                    connection.execute("CREATE TABLE sandbox_case_receipts(case_id TEXT PRIMARY KEY, receipt_json TEXT NOT NULL)")
                else:
                    connection.execute(f'CREATE TABLE "{table}"(id TEXT)')
            connection.execute("CREATE TABLE sandbox_ledger_identity(id INTEGER PRIMARY KEY, generation TEXT NOT NULL)")
            connection.execute("INSERT INTO sandbox_ledger_identity VALUES (1, 'fictional-secret-row-value')")

    def test_nine_tables_empty_and_bootstrap_identity_one(self):
        receipt = verifier.empty_state_receipt(self.state)
        self.assertEqual(receipt["empty_table_row_counts"], {table: 0 for table in verifier.EMPTY_STATE_TABLES})
        self.assertEqual(len(receipt["empty_table_row_counts"]), 9)
        self.assertEqual(receipt["bootstrap_ledger_identity_rows"], 1)
        self.assertEqual(receipt["declared_tables"], sorted([*verifier.EMPTY_STATE_TABLES, "sandbox_ledger_identity"]))
        self.assertTrue(receipt["schema_only_no_row_values"])
        self.assertEqual(receipt["tool_calls"], 0)
        self.assertEqual(receipt["action_writes"], 0)

    def test_schema_and_index_inventory_exposes_new_columns_without_row_values(self):
        receipt = verifier.empty_state_receipt(self.state)
        self.assertNotIn("fictional-secret-row-value", json.dumps(receipt))
        self.assertEqual(receipt["schema_sha256"], verifier.value_sha256(receipt["schema"]))
        pending = receipt["schema"]["action_pending"]
        self.assertIn({"ordinal": 2, "name": "confirmation_state", "type": "TEXT",
                       "not_null": False, "default": None, "primary_key": 0}, pending["columns"])
        self.assertEqual(pending["indexes"], [{"name": "action_pending_request_key", "unique": True,
            "origin": "c", "partial": False, "columns": [{"ordinal": 0, "column_ordinal": 1, "column": "request_key"}]}])
        packet = next(column for column in receipt["schema"]["sandbox_handoffs"]["columns"]
                      if column["name"] == "packet_json")
        self.assertFalse(packet["not_null"])
        self.assertIsNone(packet["default"])
        self.assertEqual(len(receipt["schema"]["sandbox_case_receipts"]["columns"]), 2)

    def test_receipt_row_is_action_state_even_when_all_other_tables_are_empty(self):
        with closing(sqlite3.connect(self.state)) as connection, connection:
            connection.execute("INSERT INTO sandbox_case_receipts VALUES ('fictional-case', '{}')")
        with self.assertRaisesRegex(verifier.PreflightError, "created_action_or_authority_state"):
            verifier.empty_state_receipt(self.state)

    def test_missing_case_receipt_table_is_rejected(self):
        with closing(sqlite3.connect(self.state)) as connection, connection:
            connection.execute("DROP TABLE sandbox_case_receipts")
        with self.assertRaisesRegex(verifier.PreflightError, "schema_missing"):
            verifier.empty_state_receipt(self.state)

    def test_extra_authority_table_is_rejected_even_if_empty(self):
        with closing(sqlite3.connect(self.state)) as connection, connection:
            connection.execute("CREATE TABLE unreported_authority(id TEXT)")
        with self.assertRaisesRegex(verifier.PreflightError, "table_inventory_mismatch"):
            verifier.empty_state_receipt(self.state)

    def test_sqlite_like_names_cannot_hide_an_extra_authority_table(self):
        with closing(sqlite3.connect(self.state)) as connection, connection:
            connection.execute("CREATE TABLE sqliteXauthority(id TEXT)")
        with self.assertRaisesRegex(verifier.PreflightError, "table_inventory_mismatch"):
            verifier.empty_state_receipt(self.state)

    def test_missing_confirmation_state_is_rejected(self):
        with closing(sqlite3.connect(self.state)) as connection, connection:
            connection.execute("ALTER TABLE action_pending DROP COLUMN confirmation_state")
        with self.assertRaisesRegex(verifier.PreflightError, "new_schema_mismatch"):
            verifier.empty_state_receipt(self.state)

    def test_packet_must_remain_nullable_without_fabricated_default(self):
        for declaration in ("TEXT NOT NULL", "TEXT DEFAULT '{}'"):
            with self.subTest(declaration=declaration):
                with closing(sqlite3.connect(self.state)) as connection, connection:
                    connection.execute("DROP TABLE sandbox_handoffs")
                    connection.execute(f"CREATE TABLE sandbox_handoffs(id TEXT, packet_json {declaration})")
                with self.assertRaisesRegex(verifier.PreflightError, "new_schema_mismatch"):
                    verifier.empty_state_receipt(self.state)

    def test_receipt_table_must_keep_exact_columns_and_constraints(self):
        for declaration in ("case_id TEXT, receipt_json TEXT NOT NULL",
                            "case_id TEXT PRIMARY KEY, receipt_json TEXT",
                            "case_id TEXT PRIMARY KEY, receipt_json TEXT NOT NULL, invented_authority TEXT"):
            with self.subTest(declaration=declaration):
                with closing(sqlite3.connect(self.state)) as connection, connection:
                    connection.execute("DROP TABLE sandbox_case_receipts")
                    connection.execute(f"CREATE TABLE sandbox_case_receipts({declaration})")
                with self.assertRaisesRegex(verifier.PreflightError, "new_schema_mismatch"):
                    verifier.empty_state_receipt(self.state)

    def test_bootstrap_identity_cannot_be_missing_or_duplicated(self):
        for rows in (0, 2):
            with self.subTest(rows=rows):
                with closing(sqlite3.connect(self.state)) as connection, connection:
                    connection.execute("DELETE FROM sandbox_ledger_identity")
                    for index in range(rows):
                        connection.execute("INSERT INTO sandbox_ledger_identity VALUES (?, 'fictional')", (index + 1,))
                with self.assertRaisesRegex(verifier.PreflightError, "created_action_or_authority_state"):
                    verifier.empty_state_receipt(self.state)

    def test_unreadable_sqlite_does_not_publish_raw_database_error(self):
        self.state.write_bytes(b"fictional non-database bytes")
        with self.assertRaisesRegex(verifier.PreflightError, "^discovery_state_schema_unreadable$"):
            verifier.empty_state_receipt(self.state)


class GeneratedSnapshotTests(unittest.TestCase):
    """Manifest and byte inventory tests; fixture bytes are not actual Parquet."""

    def setUp(self):
        self.fingerprint = "a" * 16
        self.event = {"basis": "transaction_date", "calendar": "source_timestamp_calendar_date",
                      "first": "2023-06-17", "last": "2026-06-17", "ownership_valid_rows": 42,
                      "missing_event_dates": 0, "source_fingerprint": self.fingerprint}
        self.manifest = {"source_fingerprint": self.fingerprint, "transaction_event_dates": self.event}

    def test_generated_event_metadata_keeps_declared_basis_calendar_and_bounds(self):
        result = verifier.validate_generated_event_dates(self.manifest)
        self.assertEqual(result, self.event)
        self.assertIsNot(result, self.event)

    def test_event_metadata_cannot_be_missing_substituted_or_reversed(self):
        mutations = [lambda value: value.pop("transaction_event_dates"),
            lambda value: value.update(transaction_event_dates=None),
            lambda value: value["transaction_event_dates"].pop("first"),
            lambda value: value["transaction_event_dates"].update(invented_freshness=True),
            lambda value: value["transaction_event_dates"].update(basis="wall_time"),
            lambda value: value["transaction_event_dates"].update(calendar="UTC_partition_date"),
            lambda value: value["transaction_event_dates"].update(source_fingerprint="b" * 16),
            lambda value: value["transaction_event_dates"].update(ownership_valid_rows=0),
            lambda value: value["transaction_event_dates"].update(ownership_valid_rows=True),
            lambda value: value["transaction_event_dates"].update(missing_event_dates=1),
            lambda value: value["transaction_event_dates"].update(missing_event_dates=False),
            lambda value: value["transaction_event_dates"].update(first="2023-6-17"),
            lambda value: value["transaction_event_dates"].update(first="2023-02-30"),
            lambda value: value["transaction_event_dates"].update(first="2026-06-18"),
            lambda value: value["transaction_event_dates"].update(last=None)]
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                manifest = copy.deepcopy(self.manifest)
                mutate(manifest)
                with self.assertRaisesRegex(verifier.PreflightError, "event_date_metadata_invalid"):
                    verifier.validate_generated_event_dates(manifest)

    def write_snapshot(self, out):
        build = out / "builds" / "fictional-build"
        file = build / "gold" / "transactions_by_customer" / "bucket=0" / "fiction.parquet"
        file.parent.mkdir(parents=True)
        file.write_bytes(b"pure validator fixture, not actual Parquet")
        (out / "CURRENT").write_text("fictional-build\n", encoding="utf-8")
        manifest = copy.deepcopy(self.manifest)
        manifest.update(build_id="fictional-build", gold_files={file.relative_to(build / "gold").as_posix(): file.stat().st_size})
        (build / "snapshot.json").write_text(json.dumps(manifest), encoding="utf-8")
        return build, file, manifest

    def test_snapshot_receipt_records_generated_metadata_without_source_or_freshness_claim(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            self.write_snapshot(out)
            receipt = verifier.fixture_snapshot_receipt(out)
            self.assertEqual(receipt["transaction_event_dates"], self.event)
            self.assertEqual(receipt["event_date_validation"], "generated_snapshot_metadata_only")
            self.assertEqual(receipt["source_fingerprint"], self.fingerprint)
            self.assertTrue(receipt["synthetic"])
            self.assertFalse(receipt["organizer_data_used"])
            self.assertEqual(receipt["gold_file_count"], 1)
            self.assertNotIn("freshness", receipt)
            self.assertNotIn("live_s3_verified", receipt)

    def test_snapshot_manifest_cannot_omit_event_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            build, _, manifest = self.write_snapshot(out)
            manifest.pop("transaction_event_dates")
            (build / "snapshot.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(verifier.PreflightError, "event_date_metadata_invalid"):
                verifier.fixture_snapshot_receipt(out)

    def test_changed_or_missing_gold_bytes_fail_before_receipt(self):
        for missing in (False, True):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as temporary:
                out = Path(temporary)
                _, file, _ = self.write_snapshot(out)
                if missing:
                    file.unlink()
                else:
                    file.write_bytes(b"changed")
                with self.assertRaisesRegex(verifier.PreflightError, "gold_inventory_mismatch"):
                    verifier.fixture_snapshot_receipt(out)


class CompiledEvidenceTests(unittest.TestCase):
    """Exercise only the Node verifier's pure copy helper using invented bytes."""

    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if not cls.node:
            raise unittest.SkipTest("Node is required for pure JavaScript helper tests")
        cls.driver = Path(__file__).with_name("verify_flujo.cjs").resolve()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.app = self.root / "fictional-installed-app"
        self.receipts = self.root / "fixture-receipts"
        self.contents = {
            ".next/server/app-paths-manifest.json": b'{"/v1/banking/action/route":"app/v1/banking/action/route.js"}\n',
            ".next/server/app/v1/banking/action/route.js": b"// fictional generated route bytes\r\n",
            ".next/server/app/v1/banking/action/route.js.nft.json": b'{"version":1,"files":[]}\n',
            ".next/server/chunks/fictional-adapter.js": b"// fictional module byte fixture, not evaluated\n",
            "scripts/launch-next.mjs": b"// fictional launcher byte fixture, not executed\n",
            "scripts/healthcheck.mjs": b"// fictional healthcheck byte fixture, not executed\n",
        }
        self.selected = [
            {"path": ".next/server/app-paths-manifest.json", "role": "app_paths_manifest"},
            {"path": ".next/server/app/v1/banking/action/route.js", "role": "action_route_entry"},
            {"path": ".next/server/app/v1/banking/action/route.js", "role": "userland_module"},
            {"path": ".next/server/app/v1/banking/action/route.js.nft.json", "role": "action_route_trace"},
            {"path": ".next/server/chunks/fictional-adapter.js", "role": "execution_core_module"},
            {"path": ".next/server/chunks/fictional-adapter.js", "role": "configured_adapter_module"},
            {"path": ".next/server/chunks/fictional-adapter.js", "role": "adapter_resolution_module"},
            {"path": "scripts/launch-next.mjs", "role": "application_launcher"},
            {"path": "scripts/healthcheck.mjs", "role": "healthcheck_launcher"},
        ]
        self.hashes = {}
        for relative, content in self.contents.items():
            target = self.app / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            self.hashes[relative] = verifier.file_sha256(target)

    def invoke_copy(self, selected=None, hashes=None, receipt_dir=None):
        fixture = {"appRoot": str(self.app), "receiptDir": str(receipt_dir or self.receipts),
                   "selected": self.selected if selected is None else selected,
                   "hashes": self.hashes if hashes is None else hashes}
        code = """const verifier = require(process.argv[1]);
let input = ''; process.stdin.setEncoding('utf8'); process.stdin.on('data', value => input += value);
process.stdin.on('end', () => { const fixture = JSON.parse(input);
  try { console.log(JSON.stringify({ok:true, receipt:verifier.retainCompiledEvidence(
    fixture.appRoot, fixture.receiptDir, fixture.selected, fixture.hashes)})); }
  catch(error) { console.log(JSON.stringify({ok:false, code:error.message})); }
});"""
        result = subprocess.run([self.node, "-e", code, str(self.driver)], input=json.dumps(fixture),
                                text=True, capture_output=True, check=True, timeout=15)
        self.assertEqual(result.stderr, "")
        return json.loads(result.stdout)

    def test_whole_file_bytes_paths_hashes_roles_and_source_identity_are_retained(self):
        result = self.invoke_copy()
        self.assertTrue(result["ok"], result)
        receipt = result["receipt"]
        self.assertEqual(receipt["schema_version"], 2)
        self.assertEqual(receipt["checkpoint"], verifier.CHECKPOINT)
        self.assertEqual(receipt["sourceRevision"], "51ff39fc5bac84cbbb49bbd2b21b5ab89de8b14b")
        self.assertEqual(receipt["reviewedSourceRevision"], "3037c1423f7d39ede4d4a9b50afae038e4dd7baa")
        self.assertEqual(receipt["reviewedSourceTree"], "b754c1cae7def51ab9a1343c1726a63c30d2c53a")
        self.assertEqual(receipt["fileCount"], len(self.contents))
        self.assertEqual(receipt["totalBytes"], sum(map(len, self.contents.values())))
        self.assertTrue(receipt["rawBytesRetained"])
        self.assertFalse(receipt["truncation"])
        self.assertFalse(receipt["applicationExecuted"])
        for entry in receipt["files"]:
            relative = entry["installedRelativePath"]
            copied = self.receipts / entry["artifactPath"]
            self.assertEqual(copied.read_bytes(), self.contents[relative])
            self.assertEqual(entry["installedPath"], str((self.app / relative).resolve()))
            self.assertEqual(entry["artifactPath"], "compiled-evidence/" + relative)
            self.assertEqual(entry["bytes"], len(self.contents[relative]))
            self.assertEqual(entry["sha256"], self.hashes[relative])
            self.assertEqual(entry["sha256"], verifier.file_sha256(copied))
            self.assertEqual(entry["sourceRevision"], receipt["sourceRevision"])
            self.assertEqual(entry["roles"], sorted({item["role"] for item in self.selected if item["path"] == relative}))

    def test_source_drift_cannot_be_copied_as_the_approved_hash(self):
        (self.app / "scripts/launch-next.mjs").write_bytes(b"changed fictional launcher")
        result = self.invoke_copy()
        self.assertEqual(result, {"ok": False, "code": "compiled_evidence_installed_hash_mismatch"})
        self.assertFalse((self.receipts / "compiled-evidence").exists())

    def test_missing_hash_cannot_become_an_unverified_raw_attachment(self):
        hashes = dict(self.hashes)
        hashes.pop("scripts/healthcheck.mjs")
        self.assertEqual(self.invoke_copy(hashes=hashes),
                         {"ok": False, "code": "compiled_evidence_installed_hash_mismatch"})
        self.assertFalse((self.receipts / "compiled-evidence").exists())

    def test_unapproved_data_or_traversal_path_is_rejected_before_copy(self):
        for relative, role in (("../private.env", "configured_adapter_module"),
                               (".next/server/../../private.env", "configured_adapter_module"),
                               (".next/cache/config.json", "configured_adapter_module"),
                               (".next/server/chunks/data.parquet", "configured_adapter_module"),
                               ("scripts/private.mjs", "application_launcher"),
                               ("scripts/launch-next.mjs", "unapproved_role")):
            with self.subTest(path=relative):
                result = self.invoke_copy(selected=[{"path": relative, "role": role}])
                self.assertEqual(result, {"ok": False, "code": "compiled_evidence_path_not_approved"})
                self.assertFalse((self.receipts / "compiled-evidence").exists())

    def test_too_many_whole_files_fails_without_silent_truncation(self):
        selected = [{"path": f".next/server/chunks/fiction-{index}.js", "role": "adapter_resolution_module"}
                    for index in range(17)]
        self.assertEqual(self.invoke_copy(selected=selected),
                         {"ok": False, "code": "compiled_evidence_file_count_exceeded"})
        self.assertFalse((self.receipts / "compiled-evidence").exists())

    def test_oversized_file_fails_before_creating_bundle(self):
        target = self.app / ".next/server/chunks/fictional-adapter.js"
        with target.open("r+b") as source:
            source.truncate(8 * 1024 * 1024 + 1)
        self.assertEqual(self.invoke_copy(), {"ok": False, "code": "compiled_evidence_file_size_exceeded"})
        self.assertFalse((self.receipts / "compiled-evidence").exists())

    def test_total_size_limit_cannot_be_evaded_by_several_allowed_files(self):
        selected, hashes = [], {}
        for index in range(4):
            relative = f".next/server/chunks/fiction-{index}.js"
            target = self.app / relative
            with target.open("wb") as source:
                source.truncate(8 * 1024 * 1024)
            hashes[relative] = verifier.file_sha256(target)
            selected.append({"path": relative, "role": "adapter_resolution_module"})
        self.assertEqual(self.invoke_copy(selected=selected, hashes=hashes),
                         {"ok": False, "code": "compiled_evidence_total_size_exceeded"})
        self.assertFalse((self.receipts / "compiled-evidence").exists())

    def test_existing_bundle_is_not_overwritten_or_mixed_with_new_evidence(self):
        self.assertTrue(self.invoke_copy()["ok"])
        self.assertEqual(self.invoke_copy(), {"ok": False, "code": "compiled_evidence_directory_already_exists"})

    def test_evidence_output_cannot_write_into_the_installed_application(self):
        self.assertEqual(self.invoke_copy(receipt_dir=self.app / "evidence"),
                         {"ok": False, "code": "compiled_evidence_output_inside_application"})
        self.assertFalse((self.app / "evidence").exists())

    def test_node_main_refuses_without_remote_flag_before_reading_application(self):
        environment = dict(os.environ)
        environment.pop("GITHUB_ACTIONS", None)
        result = subprocess.run([self.node, str(self.driver)], env=environment, capture_output=True,
                                text=True, timeout=15)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stderr), {"verified": False, "code": "remote_github_actions_linux_required"})
        self.assertEqual(result.stdout, "")

    def invoke_wrapper(self, wrapper=None, receipt_dir=None):
        fixture = {"wrapper": str(wrapper or self.root / "base" / "docker-entrypoint.sh"),
                   "receiptDir": str(receipt_dir or self.receipts)}
        code = """const verifier = require(process.argv[1]);
let input = ''; process.stdin.setEncoding('utf8'); process.stdin.on('data', value => input += value);
process.stdin.on('end', () => { const fixture = JSON.parse(input);
  try { console.log(JSON.stringify({ok:true, receipt:verifier.retainObservedBaseLauncher(
    fixture.wrapper, fixture.receiptDir)})); }
  catch(error) { console.log(JSON.stringify({ok:false, code:error.message})); }
});"""
        result = subprocess.run([self.node, "-e", code, str(self.driver)], input=json.dumps(fixture),
                                text=True, capture_output=True, check=True, timeout=15)
        self.assertEqual(result.stderr, "")
        return json.loads(result.stdout)

    def write_wrapper(self):
        wrapper = self.root / "base" / "docker-entrypoint.sh"
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        content = b"#!/bin/sh\n# generated fictional wrapper, never executed\nexit 99\n"
        wrapper.write_bytes(content)
        return wrapper, content

    def test_inherited_wrapper_bytes_are_observed_without_claiming_flujo_source_review(self):
        wrapper, content = self.write_wrapper()
        result = self.invoke_wrapper()
        self.assertTrue(result["ok"], result)
        receipt = result["receipt"]
        self.assertEqual(receipt["checkpoint"], verifier.CHECKPOINT)
        self.assertEqual(receipt["schema_version"], 2)
        self.assertEqual(receipt["installedPath"], str(wrapper.resolve()))
        self.assertEqual(receipt["artifactPath"], "observed-base-launcher/docker-entrypoint.sh")
        self.assertEqual(receipt["expectedEntrypoint"], ["docker-entrypoint.sh"])
        self.assertEqual(receipt["bytes"], len(content))
        self.assertEqual(receipt["sha256"], verifier.file_sha256(wrapper))
        self.assertEqual((self.receipts / receipt["artifactPath"]).read_bytes(), content)
        self.assertFalse(receipt["sourceReviewedFlujoScript"])
        self.assertFalse(receipt["upstreamOriginIndependentlyCertified"])
        self.assertFalse(receipt["executed"])
        self.assertTrue(receipt["rawBytesRetained"])
        self.assertNotIn("sourceRevision", receipt)

    def test_missing_inherited_wrapper_fails_without_creating_artifact(self):
        self.assertEqual(self.invoke_wrapper(), {"ok": False, "code": "observed_base_launcher_missing"})
        self.assertFalse((self.receipts / "observed-base-launcher").exists())

    def test_inherited_wrapper_must_be_a_regular_file(self):
        wrapper = self.root / "base" / "docker-entrypoint.sh"
        wrapper.mkdir(parents=True)
        self.assertEqual(self.invoke_wrapper(), {"ok": False, "code": "observed_base_launcher_not_regular_file"})
        self.assertFalse((self.receipts / "observed-base-launcher").exists())

    def test_inherited_wrapper_symlink_is_rejected(self):
        target = self.root / "fictional-wrapper-bytes"
        target.write_bytes(b"fictional linked wrapper")
        wrapper = self.root / "base" / "docker-entrypoint.sh"
        wrapper.parent.mkdir()
        try:
            wrapper.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("This platform does not permit generated symlink fixtures")
        self.assertEqual(self.invoke_wrapper(), {"ok": False, "code": "observed_base_launcher_not_regular_file"})
        self.assertFalse((self.receipts / "observed-base-launcher").exists())

    def test_inherited_wrapper_size_is_bounded_before_copy(self):
        wrapper, _ = self.write_wrapper()
        for size in (0, 256 * 1024 + 1):
            with self.subTest(size=size):
                with wrapper.open("r+b") as source:
                    source.truncate(size)
                self.assertEqual(self.invoke_wrapper(), {"ok": False, "code": "observed_base_launcher_size_exceeded"})
                self.assertFalse((self.receipts / "observed-base-launcher").exists())

    def test_inherited_wrapper_existing_evidence_is_never_overwritten(self):
        self.write_wrapper()
        self.assertTrue(self.invoke_wrapper()["ok"])
        self.assertEqual(self.invoke_wrapper(), {"ok": False, "code": "observed_base_launcher_directory_already_exists"})

    def test_inherited_wrapper_cannot_write_inside_its_source_directory(self):
        wrapper, _ = self.write_wrapper()
        self.assertEqual(self.invoke_wrapper(receipt_dir=wrapper.parent / "evidence"),
                         {"ok": False, "code": "observed_base_launcher_output_inside_source"})
        self.assertFalse((wrapper.parent / "evidence").exists())


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

    def test_direct_discovery_refuses_before_runtime_imports_without_remote_flag(self):
        before = {name for name in sys.modules if name.startswith(("banking_mcp", "pipeline", "mcp"))}
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(
                verifier.PreflightError, "remote_github_actions_linux_required"):
            verifier.generated_discovery(Path("unopened-root"), Path("unopened-temporary"))
        after = {name for name in sys.modules if name.startswith(("banking_mcp", "pipeline", "mcp"))}
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
