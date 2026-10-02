"""Infrastructure collectors preserve source times and exclude secret/config data."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from history_sources import infrastructure as infra


class InfrastructureTests(unittest.TestCase):
    def test_shell_tools_only_not_patches_or_planned_text(self):
        code = 'text(await tools.exec_command({cmd:"docker build -t savia .",workdir:"C:/repo"}));'
        self.assertEqual(list(infra._commands(code, "exec")), ["docker build -t savia ."])
        self.assertEqual(list(infra._commands('text(await tools.apply_patch("docker build -t savia ."));', "exec")), [])
        self.assertEqual(infra._classify('Write-Output "docker build -t savia ."'), [])
        self.assertEqual(infra._classify('python run_modal.py --dry-run'), [])
        self.assertEqual(infra._classify('python run_modal.py --execute')[0][:2], ("modal", "ci_execution"))
        self.assertEqual(infra._classify('flyctl deploy -a flujo-factored-2026')[0][:2], ("fly", "deployment"))

    def test_json_decoding_fly_pretty_objects_and_arrays(self):
        self.assertEqual(list(infra._json_values('[{"id":"a"},{"id":"b"}]')), [{"id": "a"}, {"id": "b"}])
        self.assertEqual(list(infra._json_values('{\n "id":"a"\n}\n{\n "id":"b"\n}\n')), [{"id": "a"}, {"id": "b"}])

    def test_docker_machine_lifecycle_not_snapshot_date_and_secret_fields_not_requested(self):
        observed = "2026-10-02T02:00:00.000000Z"
        row = {"Id": "abc", "Name": "/flujo-worker", "Created": "2026-09-25T15:00:00Z", "Image": "flujo:test", "ImageId": "sha256:def",
            "State": {"Status": "exited", "StartedAt": "2026-09-25T15:01:00Z", "FinishedAt": "2026-09-25T15:05:00Z", "ExitCode": 1, "OOMKilled": False},
            "Ports": {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "43420"}]}}
        calls = []
        def run(args, repo, timeout=40):
            calls.append(args)
            if args[1:3] == ["ps", "-aq"]:
                return "abc\nunrelated", ""
            if args[1] == "inspect":
                return json.dumps(row) + "\n" + json.dumps({**row, "Id": "other", "Name": "/unrelated", "Image": "postgres"}), ""
            if args[1] == "context":
                return "desktop-linux", ""
            if args[1] == "logs":
                return "2026-09-25T15:02:00.123456789Z first line\n", "2026-09-25T15:03:00Z API_KEY=supersecret123456\n"
            if args[1:3] == ["image", "inspect"]:
                return json.dumps({"Id": "sha256:def", "Created": "2026-09-25T14:55:00Z", "Tags": ["flujo:test"], "Size": 10}), ""
            raise AssertionError(args)
        events, machines, builds, notes = [], {}, [], []
        from collections import Counter
        stats = Counter()
        with patch.object(infra.shutil, "which", return_value="docker"), patch.object(infra, "_run", side_effect=run):
            infra._docker(Path("."), {}, observed, events, machines, builds, notes, stats)
        machine = machines["docker:abc"]
        self.assertEqual(machine["createdAt"], "2026-09-25T15:00:00.000000Z")
        self.assertEqual(machine["lastObservedAt"], observed)
        self.assertEqual(machine["state"], "exited")
        self.assertEqual(stats["dockerContainers"], 1)
        self.assertEqual(len([event for event in events if event["kind"] == "container_log"]), 2)
        self.assertEqual(next(event for event in events if event["kind"] == "machine_snapshot")["timestamp"], observed)
        self.assertNotIn("supersecret123456", json.dumps(events))
        inspect_format = next(args[3] for args in calls if args[1] == "inspect")
        self.assertNotIn(".Config.Env", inspect_format)
        self.assertNotIn(".Config.Cmd", inspect_format)
        self.assertTrue(inspect_format.endswith("}}}"), "Template must close both the Go expression and outer JSON object")

    def test_fly_allowlist_excludes_env_and_creation_date_is_authoritative(self):
        row = {"id": "abc", "name": "test", "region": "iad", "state": "started", "created_at": "2026-09-28T12:00:00Z",
            "config": {"image": "registry/test", "env": {"TOKEN": "supersecret"}, "guest": {"cpus": 2, "memory_mb": 4096}},
            "events": [{"type": "start", "status": "started", "timestamp": 1790596860000, "request": {"token": "supersecret"}}]}
        events, machines = [], {}
        infra._fly_machine(row, "app", "2026-10-02T01:00:00.000000Z", events, machines)
        self.assertEqual(machines["fly:app:abc"]["createdAt"], "2026-09-28T12:00:00.000000Z")
        self.assertEqual(machines["fly:app:abc"]["location"], "iad")
        self.assertNotIn("supersecret", json.dumps({"events": events, "machines": machines}))
        self.assertEqual(events[1]["metadata"]["timestampBasis"], "fly.machine.events.timestamp")

    def test_command_failed_output_is_not_success_or_created_machine(self):
        events, builds, deployments = [], [], []
        from collections import Counter
        call = {"key": "a", "source": "codex", "command": "docker build -t test .", "timestamp": "2026-09-25T12:00:00Z",
            "outputTimestamp": "2026-09-25T12:01:00Z", "cwd": "C:/repo", "threadId": "thread"}
        infra._record_command(call, {"exit_code": 1, "output": "permission denied\nTOKEN=secretvalue123"}, events, builds, deployments, Counter())
        self.assertEqual(events[0]["metadata"]["state"], "failed")
        self.assertEqual(builds[0]["state"], "failed")
        self.assertEqual(builds[0]["finishedAt"], call["outputTimestamp"])
        self.assertNotIn("machineId", events[0]["metadata"])
        self.assertNotIn("secretvalue123", events[0]["body"])
        self.assertEqual(deployments, [])

    def test_report_executed_false_skipped_and_no_mtime_fallback(self):
        from collections import Counter
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ci").mkdir()
            (root / "ci/summary.json").write_text(json.dumps({"executed": True, "status": "PASS", "started_at": "2026-09-28T10:00:00Z",
                "owner_token": "do-not-export", "repository": "owner/repo", "head_sha": "abc", "receipts": [{"gate_id": "frontend", "exit_code": 0, "secret": "hidden"}]}), encoding="utf-8")
            (root / "ci/result.json").write_text(json.dumps({"executed": False, "status": "PASS", "started_at": "2026-09-28T11:00:00Z"}), encoding="utf-8")
            (root / "ci/report.json").write_text(json.dumps({"executed": True, "status": "PASS"}), encoding="utf-8")
            events, machines, builds, notes, stats = [], {}, [], [], Counter()
            infra._ci_reports(root, {"codex_home": str(root), "ci_evidence_roots": [str(root / "ci")], "github_repository": "owner/repo"}, "2026-10-02T00:00:00Z",
                events, machines, builds, notes, stats, set())
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["timestamp"], "2026-09-28T10:00:00.000000Z")
            self.assertEqual(events[0]["metadata"]["timestampBasis"], "execution report.started_at")
            self.assertNotIn("do-not-export", events[0]["body"])
            self.assertNotIn("hidden", events[0]["body"])
            self.assertEqual(stats["reportsWithoutAuthoritativeTime"], 1)

    def test_modal_help_example_is_not_a_real_app_and_saved_app_list_has_real_date(self):
        help_event = infra._event("help", "2026-10-01T10:00:00Z", "inspection_command_output", "Help", "Example: modal app rollback ap-abcdefghABCDEFGH123456", "modal", "cloud",
            command="modal workspace settings --help", state="completed")
        app_row = {"app_id": "ap-actualAppIdentifier1234", "description": "private-ci", "state": "stopped", "created_at": "2026-10-01 08:23:32-05:00"}
        list_event = infra._event("list", "2026-10-01T15:00:00Z", "inspection_command_output", "List", json.dumps({"output": json.dumps([app_row])}), "modal", "cloud",
            command="modal app list --json", state="completed")
        machines = {}
        infra._associate_machine_evidence([help_event, list_event], machines)
        self.assertEqual(list(machines), ["modal:ap-actualAppIdentifier1234"])
        self.assertEqual(machines["modal:ap-actualAppIdentifier1234"]["createdAt"], "2026-10-01T13:23:32.000000Z")
        self.assertFalse(machines["modal:ap-actualAppIdentifier1234"]["currentSnapshot"])


if __name__ == "__main__":
    unittest.main()
