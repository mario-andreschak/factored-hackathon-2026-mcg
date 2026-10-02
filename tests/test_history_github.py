"""Collector contract tests without credentials, network access, or source writes."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from history_sources import docs, github


class HistorySourceTests(unittest.TestCase):
    def test_remote_url_formats(self):
        for url in ("https://github.com/owner/repo.git", "git@github.com:owner/repo.git", "ssh://git@github.com/owner/repo.git"):
            with self.subTest(url=url), patch.object(github, "_run", return_value=url):
                self.assertEqual(github._repository(Path("."), {}), ("owner/repo", "github.com"))

    def test_paginated_array_contract(self):
        with patch.object(github, "_run", return_value=json.dumps([[{"id": 1}], [{"id": 2}]])):
            self.assertEqual(github._api("endpoint", Path("."), "github.com"), [{"id": 1}, {"id": 2}])
        with patch.object(github, "_run", return_value=json.dumps([{"workflow_runs": [{"id": 1}]}])):
            self.assertEqual(github._api("endpoint", Path("."), "github.com"), [{"workflow_runs": [{"id": 1}]}])

    def test_commit_message_timezone_and_excluded_internal_refs(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            def git(*args):
                return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, encoding="utf-8").stdout.strip()
            git("init")
            (repo / "README.md").write_text("# Project\n\nFull original text", encoding="utf-8")
            git("add", "README.md")
            git("-c", "user.name=Collector Test", "-c", "user.email=test@example.invalid", "commit", "-m", "First commit\n\nDetailed second paragraph.")
            first = git("rev-parse", "HEAD")
            branch = git("branch", "--show-current")
            git("checkout", "--orphan", "internal")
            git("-c", "user.name=Collector Test", "-c", "user.email=test@example.invalid", "commit", "-m", "Internal snapshot")
            snapshot = git("rev-parse", "HEAD")
            git("update-ref", "refs/codex/snapshots/test", snapshot)
            git("checkout", branch)
            git("branch", "-D", "internal")
            result = github.collect(repo, {"github_enabled": False})
            self.assertEqual([item["metadata"]["sha"] for item in result["events"]], [first])
            self.assertIn("Detailed second paragraph.", result["events"][0]["body"])
            self.assertTrue(result["events"][0]["timestamp"].endswith("Z"))
            self.assertEqual(len(github.collect(repo, {"github_enabled": False, "github_include_internal_refs": True})["events"]), 2)
            doc_result = docs.collect(repo, {})
            self.assertEqual(doc_result["stats"]["documents"], 1)
            self.assertEqual(doc_result["events"][0]["metadata"]["timestampBasis"], "git_committer_time")
            self.assertEqual(doc_result["events"][0]["body"], "# Project\n\nFull original text")

    def test_credential_docs_are_excluded_and_ci_yaml_included(self):
        self.assertFalse(docs._is_doc("private/original.pdf"))
        self.assertFalse(docs._is_doc("docs/LATAM_Bank_Complete_Data_Dictionary.pdf"))
        self.assertTrue(docs._is_doc("docs/reference/LATAM_Bank_Complete_Data_Dictionary_REDACTED.pdf"))
        self.assertTrue(docs._is_doc(".github/workflows/ci.yml"))
        self.assertFalse(docs._is_doc("node_modules/package/README.md"))

    def test_local_remote_commit_overlap_retains_one_complete_record(self):
        sha = "a" * 40
        local = github._event("git:commit:" + sha, "2026-09-25T12:00:00-05:00", "commit", "First commit",
                              "First commit\n\nFull explanation.", "Local Author", metadata={"sha": sha, "collectedFrom": ["local-git"]})
        def api(endpoint, repo, hostname, paginate=True):
            if endpoint == "repos/owner/repo":
                return {"default_branch": "main"}
            if "/branches?" in endpoint:
                return [{"name": "main", "commit": {"sha": sha}}]
            if "/commits?" in endpoint:
                return [{"sha": sha, "html_url": "https://github.com/owner/repo/commit/" + sha,
                         "author": {"login": "author"}, "commit": {"message": "First commit", "committer": {"date": "2026-09-25T17:00:00Z"}}}]
            return []
        with patch.object(github, "_local_commits", return_value=([local], {})), patch.object(github, "_api", side_effect=api), patch.object(github.shutil, "which", return_value="gh"):
            result = github.collect(Path("."), {"github_repository": "owner/repo"})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["events"]), 1)
        self.assertIn("Full explanation.", result["events"][0]["body"])
        self.assertEqual(result["events"][0]["metadata"]["collectedFrom"], ["local-git", "github:ref:main"])
        self.assertIn(sha, result["events"][0]["url"])


if __name__ == "__main__":
    unittest.main()
