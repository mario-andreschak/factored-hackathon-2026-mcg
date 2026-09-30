"""Source-only context checks: no banking imports, data processing or services."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.package_issue21_preflight import context, prepare_flujo


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
        self.commit("Audited synthetic bank runtime")
        self.audited = self.git("rev-parse", "HEAD").strip().decode()
        self.write("docs/reviewed-source-marker.md", b"# Non-runtime synthetic reviewed source metadata\n")
        self.commit("Reviewed synthetic bank source")
        self.reviewed = self.git("rev-parse", "HEAD").strip().decode()
        self.write("docs/installed-merge-marker.md", b"# Non-runtime synthetic merge metadata\n")
        self.commit("Installed synthetic source merge")
        self.source = self.git("rev-parse", "HEAD").strip().decode()
        self.pin = patch.object(context, "PINNED_BANK_SOURCE", self.source)
        self.pin.start()
        self.addCleanup(self.pin.stop)
        self.reviewed_pin = patch.object(context, "REVIEWED_BANK_SOURCE", self.reviewed)
        self.reviewed_pin.start()
        self.addCleanup(self.reviewed_pin.stop)
        self.audited_pin = patch.object(context, "AUDITED_BANK_SOURCE", self.audited)
        self.audited_pin.start()
        self.addCleanup(self.audited_pin.stop)
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
        self.assertEqual(manifest["reviewed_bank_source_revision"], self.reviewed)
        self.assertEqual(manifest["audited_bank_source_revision"], self.audited)
        self.assertNotEqual(self.audited, self.reviewed)
        self.assertNotEqual(self.reviewed, self.source)
        equivalence = manifest["reviewed_runtime_equivalence"]
        self.assertEqual(equivalence["status"], "unchanged")
        self.assertEqual(equivalence["reviewed_revision"], self.reviewed)
        self.assertEqual(equivalence["installed_revision"], self.source)
        self.assertEqual(equivalence["compared_paths"], list(context.RUNTIME_FILES))
        self.assertEqual(equivalence["reviewed_runtime_sha256"], manifest["runtime_tree_sha256"])
        self.assertEqual(equivalence["installed_runtime_sha256"], manifest["runtime_tree_sha256"])
        audited_equivalence = manifest["audited_runtime_equivalence"]
        self.assertEqual(audited_equivalence["status"], "unchanged")
        self.assertEqual(audited_equivalence["audited_revision"], self.audited)
        self.assertEqual(audited_equivalence["reviewed_revision"], self.reviewed)
        self.assertEqual(audited_equivalence["compared_paths"], list(context.RUNTIME_FILES))
        self.assertEqual(audited_equivalence["audited_runtime_sha256"], manifest["runtime_tree_sha256"])
        self.assertEqual(audited_equivalence["reviewed_runtime_sha256"], manifest["runtime_tree_sha256"])
        self.assertEqual(manifest["schema_version"], 2)
        self.assertEqual(manifest["checkpoint"], "banking-package-issue21/v2")
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

    def test_installed_merge_cannot_change_reviewed_runtime(self):
        self.write("banking_mcp/config.py", b"unreviewed_installed_change = True\n")
        self.commit("Unreviewed installed runtime drift")
        installed = self.git("rev-parse", "HEAD").strip().decode()
        with patch.object(context, "PINNED_BANK_SOURCE", installed):
            with self.assertRaisesRegex(context.ContextError, "candidate bank runtime differs.*config.py"):
                context.build_context(self.repo, self.root / "context", source_revision=installed)
        self.assertFalse((self.root / "context").exists())

    def test_reviewed_source_cannot_change_prior_audited_runtime(self):
        self.write("banking_mcp/repository.py", b"unreviewed_runtime_change = True\n")
        self.commit("Reviewed source runtime drift")
        changed_review = self.git("rev-parse", "HEAD").strip().decode()
        with patch.object(context, "REVIEWED_BANK_SOURCE", changed_review):
            with self.assertRaisesRegex(context.ContextError, "candidate bank runtime differs.*repository.py"):
                self.build()
        self.assertFalse((self.root / "context").exists())

    def test_rejects_existing_or_unignored_output(self):
        existing = self.root / "existing"
        existing.mkdir()
        with self.assertRaisesRegex(context.ContextError, "must not already exist"):
            self.build(existing)
        with self.assertRaisesRegex(context.ContextError, "inside checkout must be Git ignored"):
            self.build(self.repo / "untracked-context")

    def test_rejects_missing_candidate_helper(self):
        self.git("rm", "scripts/package_issue21_preflight/verify_installed.py")
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


class FlujoSourceContextTests(unittest.TestCase):
    """Synthetic committed source only; no application imports or builds."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "synthetic-flujo"
        self.repo.mkdir()
        self.git("init", "--quiet")
        self.git("config", "user.email", "context-tests@example.invalid")
        self.git("config", "user.name", "FLUJO source context test")
        self.git("config", "core.autocrlf", "false")
        for relative in prepare_flujo.ROOT_FILES:
            self.write(relative, b"# Synthetic build input; never executed.\n")
        self.write("package.json", json.dumps({"version": "3.46.1"}).encode())
        self.write("src/example.ts", b"throw new Error('source must never execute');\n")
        for excluded in ("docs/report.md", "data/private.csv", ".env", "tests/example.test.ts", "AGENTS.md"):
            self.write(excluded, b"EXCLUDED_SYNTHETIC_SENTINEL\n")
        self.commit()

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], stderr=subprocess.PIPE)

    def write(self, relative, content):
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def commit(self):
        self.git("add", "--all")
        self.git("commit", "--quiet", "-m", "Synthetic pinned source")
        self.head = self.git("rev-parse", "HEAD").decode().strip()
        self.tree = self.git("rev-parse", "HEAD^{tree}").decode().strip()

    def prepare(self, *, head=None, tree=None, output=None):
        with patch.object(prepare_flujo, "PIN", head or self.head), patch.object(prepare_flujo, "TREE", tree or self.tree):
            return prepare_flujo.prepare(self.repo, output or self.root / "context", self.root / "manifest.json")

    def test_pinned_source_context_is_versioned_and_contains_only_exact_allowed_blobs(self):
        self.write("src/example.ts", b"DIRTY_UNCOMMITTED_SENTINEL\n")
        receipt = self.prepare()
        self.assertEqual(receipt["schema"], "flujo-package-source-context/v2")
        self.assertEqual(receipt["schema_version"], 2)
        self.assertEqual(receipt["checkpoint"], "banking-package-issue21/v2")
        self.assertEqual(receipt["sourceRevision"], self.head)
        self.assertEqual(receipt["sourceTree"], self.tree)
        self.assertFalse(receipt["runtimeExecution"])
        expected = set(prepare_flujo.ROOT_FILES) | {"src/example.ts"}
        self.assertEqual({entry["path"] for entry in receipt["files"]}, expected)
        for entry in receipt["files"]:
            content = (self.root / "context" / entry["path"]).read_bytes()
            self.assertEqual(entry["sha256"], hashlib.sha256(content).hexdigest())
            self.assertEqual(entry["bytes"], len(content))
            self.assertEqual(entry["gitOid"], self.git("rev-parse", f"{self.head}:{entry['path']}").decode().strip())
            self.assertNotIn(b"SENTINEL", content)
        self.assertEqual(json.loads((self.root / "manifest.json").read_text()), receipt)

    def test_wrong_commit_or_tree_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "fixed reviewed commit"):
            self.prepare(head="a" * 40)
        with self.assertRaisesRegex(ValueError, "tree mismatch"):
            self.prepare(tree="a" * 40)
        self.assertFalse((self.root / "context").exists())

    def test_required_build_file_cannot_be_dropped(self):
        self.git("rm", "Dockerfile")
        self.commit()
        with self.assertRaisesRegex(ValueError, "Required FLUJO root source files missing"):
            self.prepare()

    def test_version_must_match_reviewed_application(self):
        self.write("package.json", json.dumps({"version": "0.0.0-unreviewed"}).encode())
        self.commit()
        with self.assertRaisesRegex(ValueError, "application version mismatch"):
            self.prepare()

    def test_forbidden_data_and_credential_paths_in_allowed_prefixes_are_rejected(self):
        for index, relative in enumerate(("src/.env.private", "scripts/private/key.txt", "public/customer.parquet", "bin/key.pem")):
            with self.subTest(relative=relative):
                self.write(relative, b"FORBIDDEN_SYNTHETIC_SENTINEL\n")
                self.commit()
                with self.assertRaisesRegex(ValueError, "Forbidden"):
                    self.prepare(output=self.root / ("output-" + str(index)))
                self.git("rm", relative)
                self.commit()

    def test_existing_context_cannot_be_reused(self):
        output = self.root / "existing"
        output.mkdir()
        with self.assertRaisesRegex(ValueError, "must be a new directory"):
            self.prepare(output=output)


if __name__ == "__main__":
    unittest.main()
