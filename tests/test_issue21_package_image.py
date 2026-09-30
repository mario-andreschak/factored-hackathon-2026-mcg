"""Pure provenance checks. No Docker, banking imports or services."""
import importlib.util
import json
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location("issue21_package_image", Path(__file__).parents[1] / "scripts/package_issue21_preflight/record_image.py")
IMAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(IMAGE)


class FullBaseProvenance(unittest.TestCase):
    def pair(self):
        def image(layers):
            return {"Id": "sha256:" + str(len(layers)), "RootFS": {"Layers": layers}, "Config": {
                "Labels": {"org.opencontainers.image.revision": IMAGE.FLUJO, "io.flujo.application.version": "3.46.1",
                    "io.flujo.banking.source.revision": IMAGE.BANKING},
                "Env": ["FLUJO_BUILD_REVISION=" + IMAGE.FLUJO], "User": "node", "Cmd": ["node", "scripts/launch-next.mjs"],
                "Entrypoint": ["docker-entrypoint.sh"], "WorkingDir": "/app",
                "Healthcheck": {"Test": ["CMD", "node", "scripts/healthcheck.mjs"]}}}
        return image(["full-app", "full-dependencies"]), image(["full-app", "full-dependencies", "banking-source"])

    def test_all_base_layers_are_retained(self):
        base, final = self.pair()
        receipt = IMAGE.record(base, final, "a" * 40)
        self.assertTrue(receipt["baseLayersRetained"])
        self.assertEqual(receipt["schema_version"], 2)
        self.assertEqual(receipt["checkpoint"], "banking-package-issue21/v2")
        self.assertEqual(receipt["schema"], "banking-full-image-package/v2")

    def test_runtime_receipt_preserves_only_safe_launcher_metadata(self):
        base, final = self.pair()
        final["Config"]["Env"].append("PRIVATE_SENTINEL=NEVER_EXPORT")
        final["Config"]["PrivateUnrelatedConfig"] = "PRIVATE_SENTINEL"
        receipt = IMAGE.record(base, final, "a" * 40)
        self.assertEqual(set(receipt["baseRuntime"]), set(IMAGE.SAFE_RUNTIME_FIELDS))
        self.assertEqual(receipt["baseRuntime"], receipt["finalRuntime"])
        self.assertEqual(receipt["baseRuntime"]["Cmd"], ["node", "scripts/launch-next.mjs"])
        self.assertNotIn("PRIVATE_SENTINEL", str(receipt))

    def test_relabelled_old_dependency_layer_is_rejected(self):
        base, final = self.pair()
        final["RootFS"]["Layers"][1] = "old-worker-dependencies"
        with self.assertRaisesRegex(ValueError, "every exact full base layer"):
            IMAGE.record(base, final, "a" * 40)

    def test_version_env_and_labels_must_agree(self):
        base, final = self.pair()
        final["Config"]["Env"] = ["FLUJO_BUILD_REVISION=" + "b" * 40]
        with self.assertRaisesRegex(ValueError, "env mismatch"):
            IMAGE.record(base, final, "a" * 40)

    def test_runtime_launcher_and_healthcheck_are_retained(self):
        for key in ["Cmd", "Healthcheck", "User", "Entrypoint", "WorkingDir"]:
            with self.subTest(key=key):
                base, final = self.pair()
                final["Config"][key] = "changed"
                with self.assertRaises(ValueError):
                    IMAGE.record(base, final, "a" * 40)

    def test_daemon_observations_keep_exact_public_values_per_image(self):
        base, final = self.pair()
        base["Config"].update(ArgsEscaped=True, StopSignal="SIGTERM", Volumes=None)
        final["Config"].update(ArgsEscaped=False, StopSignal="15", Volumes={})
        receipt = IMAGE.record(base, final, "a" * 40)
        self.assertEqual(receipt["baseDaemonCompatibility"], {
            "ArgsEscaped": {"type": "bool", "value": True},
            "StopSignal": {"type": "str", "value": "SIGTERM"},
            "Volumes": {"type": "NoneType", "state": "null"}})
        self.assertEqual(receipt["finalDaemonCompatibility"], {
            "ArgsEscaped": {"type": "bool", "value": False},
            "StopSignal": {"type": "str", "value": "15"},
            "Volumes": {"type": "dict", "state": "empty", "count": 0}})
        self.assertEqual(json.dumps(receipt), json.dumps(IMAGE.record(base, final, "a" * 40)))

    def test_missing_observations_are_distinct_from_explicit_null(self):
        base, final = self.pair()
        final["Config"].update(ArgsEscaped=None, StopSignal=None, Volumes=None)
        receipt = IMAGE.record(base, final, "a" * 40)
        self.assertEqual(receipt["baseDaemonCompatibility"], {
            key: {"type": "missing"} for key in ("ArgsEscaped", "StopSignal", "Volumes")})
        self.assertEqual(receipt["finalDaemonCompatibility"]["ArgsEscaped"],
            {"type": "NoneType", "value": None})
        self.assertEqual(receipt["finalDaemonCompatibility"]["StopSignal"],
            {"type": "NoneType", "value": None})

    def test_empty_stop_signal_is_retained(self):
        base, final = self.pair()
        final["Config"]["StopSignal"] = ""
        self.assertEqual(IMAGE.record(base, final, "a" * 40)["finalDaemonCompatibility"]["StopSignal"],
            {"type": "str", "value": ""})

    def test_unknown_values_and_volume_paths_are_never_exported(self):
        base, final = self.pair()
        final["Config"].update(ArgsEscaped="PRIVATE_FLAG_SENTINEL", StopSignal="PRIVATE_SIGNAL_SENTINEL",
            Volumes={"/private/volume-sentinel": {"secret": "PRIVATE_VOLUME_SENTINEL"}})
        final["Config"]["Env"].append("PRIVATE_ENV_SENTINEL=secret")
        receipt = IMAGE.record(base, final, "a" * 40)
        self.assertEqual(receipt["finalDaemonCompatibility"], {
            "ArgsEscaped": {"type": "str"},
            "StopSignal": {"type": "str", "review": "unreviewed"},
            "Volumes": {"type": "dict", "state": "nonempty", "count": 1}})
        serialized = json.dumps(receipt)
        for secret in ("PRIVATE_FLAG_SENTINEL", "PRIVATE_SIGNAL_SENTINEL", "volume-sentinel",
                "PRIVATE_VOLUME_SENTINEL", "PRIVATE_ENV_SENTINEL"):
            self.assertNotIn(secret, serialized)

    def test_non_boolean_args_escaped_is_not_coerced(self):
        for value, name in ((0, "int"), (1, "int"), ([], "list"), ({}, "dict")):
            with self.subTest(value=value):
                base, final = self.pair()
                final["Config"]["ArgsEscaped"] = value
                observation = IMAGE.record(base, final, "a" * 40)["finalDaemonCompatibility"]["ArgsEscaped"]
                self.assertEqual(observation, {"type": name})

    def test_unreviewed_stop_signal_types_do_not_leak_values(self):
        for value, name in ((15, "int"), (True, "bool"), (["PRIVATE_SIGNAL_SENTINEL"], "list"),
                ({"secret": "PRIVATE_SIGNAL_SENTINEL"}, "dict")):
            with self.subTest(type=name):
                base, final = self.pair()
                final["Config"]["StopSignal"] = value
                receipt = IMAGE.record(base, final, "a" * 40)
                self.assertEqual(receipt["finalDaemonCompatibility"]["StopSignal"],
                    {"type": name, "review": "unreviewed"})
                self.assertNotIn("PRIVATE_SIGNAL_SENTINEL", json.dumps(receipt))

    def test_volume_container_summary_and_unreviewed_type_are_safe(self):
        for value, expected in (([], {"type": "list", "state": "empty", "count": 0}),
                (["/private/volume-sentinel"], {"type": "list", "state": "nonempty", "count": 1}),
                ("/private/volume-sentinel", {"type": "str", "state": "unreviewed"})):
            with self.subTest(type=expected["type"], state=expected["state"]):
                base, final = self.pair()
                final["Config"]["Volumes"] = value
                receipt = IMAGE.record(base, final, "a" * 40)
                self.assertEqual(receipt["finalDaemonCompatibility"]["Volumes"], expected)
                self.assertNotIn("volume-sentinel", json.dumps(receipt))


if __name__ == "__main__":
    unittest.main()
