"""Source-only context checks: no banking imports, data processing or services."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.package_preflight import context


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "--quiet")
        self.git("config", "user.email", "context-tests@example.invalid")
        self.git("config", "user.name", "Source context test")
        self.git("config", "core.autocrlf", "false")
        for path in context.RUNTIME_PYTHON_FILES:
            self.write(path, b"# Synthetic source for a source-only test.\n")
        # These synthetic entrypoints import the entire approved closure. They
        # are parsed by ast, never imported or executed.
        self.write("banking_mcp/__main__.py", (
            "from . import actions, config, repository, security, server, service\n"
        ).encode())
        self.write("pipeline/__main__.py", (
            "from . import bronze, common, fixture, gold, lookup, report, silver, verify, writer\n"
        ).encode())
        self.write("pipeline/contracts.yaml", b"tables: {}\n")
        self.write("requirements-mcp.txt", b"-r requirements-pipeline.txt\n-r requirements-s3.txt\nmcp==1.30.0\n")
        self.write("requirements-pipeline.txt", b"duckdb==1.5.5\npyyaml>=6\n")
        self.write("requirements-s3.txt", b"boto3>=1.35,<2\n")
        self.commit("Pinned synthetic bank source")
        self.source = self.git("rev-parse", "HEAD").strip().decode()
        self.pin = patch.object(context, "PINNED_BANK_SOURCE", self.source)
        self.pin.start()
        self.addCleanup(self.pin.stop)
        for path in context.PACKAGING_FILES:
            self.write(path, f"# Candidate helper: {path}\n".encode())
        # Intentionally sensitive or irrelevant paths must never be exported.
        for path in ("organizer.pdf", ".env", "S3credentials.env", "data/customer.csv",
                     "docs/pipeline/source_objects.json", "banking_mcp/config.example.json",
                     "pipeline/prototype_fixture.py", "pipeline/prepare_invite_preview.py"):
            self.write(path, b"EXCLUDED_SYNTHETIC_SENTINEL\n")
        self.commit("Candidate packaging with excluded sentinels")
        self.candidate = self.git("rev-parse", "HEAD").strip().decode()

    def git(self, *args: str) -> bytes:
        result = subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return result.stdout

    def write(self, path: str, data: bytes):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def commit(self, message: str):
        self.git("add", "--all")
        self.git("commit", "--quiet", "-m", message)

    def build(self, output: Path | None = None, **kwargs):
        return context.build_context(self.repo, output or self.root / "context",
                                     source_revision=self.source, **kwargs)

    def test_exports_only_pinned_runtime_and_candidate_helpers(self):
        # Dirty runtime/secret content is not an input: exported bytes come from
        # Git blobs, while the compared candidate identity stays the committed HEAD.
        self.write("banking_mcp/config.py", b"DIRTY_WORKTREE_SENTINEL\n")
        self.write(".env", b"DIRTY_SECRET_SENTINEL\n")
        manifest = self.build(candidate_head=self.candidate)
        output = self.root / "context"
        actual = {path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()}
        expected = {f"bank-runtime/{path}" for path in context.RUNTIME_FILES}
        expected.update(f"packaging/{Path(path).name}" for path in context.PACKAGING_FILES)
        expected.add("source-context-manifest.json")
        self.assertEqual(actual, expected)
        self.assertEqual(manifest["bank_source_revision"], self.source)
        self.assertEqual(manifest["candidate_ci_head"], self.candidate)
        self.assertFalse(manifest["runtime_execution"])
        self.assertEqual(manifest["core_drift_check"]["status"], "unchanged")
        self.assertEqual(json.loads((output / "source-context-manifest.json").read_text()), manifest)
        for record in (*manifest["runtime_files"], *manifest["packaging_files"]):
            contents = (output / record["context_path"]).read_bytes()
            self.assertEqual(record["sha256"], hashlib.sha256(contents).hexdigest())
            expected_oid = self.git("rev-parse", f"{record['source_revision']}:{record['path']}").decode().strip()
            self.assertEqual(record["git_blob_oid"], expected_oid)
            self.assertNotIn(b"SENTINEL", contents)
        requirements = {path: (output / "bank-runtime" / path).read_bytes() for path in context.REQUIREMENT_FILES}
        self.assertEqual(manifest["requirements"]["aggregate_sha256"], context.content_digest(requirements))

    def test_rejects_committed_bank_drift_before_creating_context(self):
        self.write("banking_mcp/config.py", b"changed = True\n")
        self.commit("Bank runtime drift")
        with self.assertRaisesRegex(context.ContextError, "candidate bank runtime differs.*config.py"):
            self.build()
        self.assertFalse((self.root / "context").exists())

    def test_rejects_added_banking_module(self):
        self.write("banking_mcp/unreviewed.py", b"added = True\n")
        self.commit("New bank module")
        with self.assertRaisesRegex(context.ContextError, "candidate bank runtime differs.*unreviewed.py"):
            self.build()

    def test_rejects_requirements_drift(self):
        self.write("requirements-s3.txt", b"boto3==0.0.0\n")
        self.commit("Dependency drift")
        with self.assertRaisesRegex(context.ContextError, "candidate bank runtime differs.*requirements-s3.txt"):
            self.build()

    def test_rejects_wrong_candidate_or_source(self):
        with self.assertRaisesRegex(context.ContextError, "candidate head argument"):
            self.build(candidate_head=self.source)
        with self.assertRaisesRegex(context.ContextError, "bank source must equal pinned"):
            context.build_context(self.repo, self.root / "context", source_revision=self.candidate)

    def test_rejects_existing_or_unignored_output(self):
        existing = self.root / "existing"
        existing.mkdir()
        with self.assertRaisesRegex(context.ContextError, "must not already exist"):
            self.build(existing)
        with self.assertRaisesRegex(context.ContextError, "inside checkout must be Git ignored"):
            self.build(self.repo / "untracked-context")

    def test_rejects_missing_candidate_helper(self):
        self.git("rm", "scripts/package_preflight/verify_installed.py")
        self.commit("Missing helper")
        with self.assertRaisesRegex(context.ContextError, "required committed file missing.*verify_installed"):
            self.build()


class StaticAuditTests(unittest.TestCase):
    def test_unlisted_local_import_is_rejected(self):
        files = {"banking_mcp/__main__.py": b"from . import extra\n", "banking_mcp/__init__.py": b"",
                 "pipeline/__main__.py": b"", "pipeline/__init__.py": b""}
        available = set(files) | {"banking_mcp/extra.py"}
        with self.assertRaisesRegex(context.ContextError, "import outside explicit runtime whitelist"):
            context.audit_import_closure(files, available)

    def test_missing_local_module_is_rejected(self):
        files = {"banking_mcp/__main__.py": b"from banking_mcp.missing import thing\n",
                 "banking_mcp/__init__.py": b"", "pipeline/__main__.py": b"", "pipeline/__init__.py": b""}
        with self.assertRaisesRegex(context.ContextError, "unresolved local import"):
            context.audit_import_closure(files, set(files))

    def test_dynamic_imports_require_review(self):
        files = {"banking_mcp/__main__.py": b"__import__('banking_mcp.extra')\n",
                 "banking_mcp/__init__.py": b"", "pipeline/__main__.py": b"", "pipeline/__init__.py": b""}
        with self.assertRaisesRegex(context.ContextError, "dynamic imports require"):
            context.audit_import_closure(files, set(files))

    def test_requirement_path_traversal_is_rejected(self):
        files = {"requirements-mcp.txt": b"-r ../credentials.env\n"}
        with self.assertRaisesRegex(context.ContextError, "unsafe requirements include"):
            context.audit_requirements(files)

    def test_content_digest_includes_names_and_exact_bytes(self):
        self.assertEqual(context.content_digest({"a": b"1", "b": b"2"}),
                         context.content_digest({"b": b"2", "a": b"1"}))
        self.assertNotEqual(context.content_digest({"a": b"1"}), context.content_digest({"b": b"1"}))
        self.assertNotEqual(context.content_digest({"a": b"x\r\n"}), context.content_digest({"a": b"x\n"}))


if __name__ == "__main__":
    unittest.main()
