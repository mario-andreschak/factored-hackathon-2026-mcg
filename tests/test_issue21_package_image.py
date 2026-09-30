"""Pure provenance checks. No Docker, banking imports or services."""
import importlib.util
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


if __name__ == "__main__":
    unittest.main()
