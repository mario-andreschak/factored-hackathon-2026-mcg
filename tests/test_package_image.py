"""Pure provenance checks. No Docker, banking imports or services."""
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location("package_image", Path(__file__).parents[1] / "scripts/package_preflight/record_image.py")
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
        self.assertTrue(IMAGE.record(base, final, "a" * 40)["baseLayersRetained"])

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
