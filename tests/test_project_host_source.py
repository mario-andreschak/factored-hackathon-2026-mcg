"""Pure fake Git inputs: no source exporter, app, database or process starts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.package_project_host import flujo_source


class FakeGit:
    def __init__(self):
        self.head, self.tree = flujo_source.PIN, flujo_source.TREE
        self.entries = {name: ("100644", "blob", b"reviewed source bytes\n")
                        for name in flujo_source.ROOT_FILES}
        self.entries["package.json"] = ("100644", "blob", json.dumps({"version": flujo_source.VERSION}).encode())
        self.entries["src/example.ts"] = ("100644", "blob", b"source only; never executed")
        self.entries["docs/customer.csv"] = ("100644", "blob", b"EXCLUDED PRIVATE SENTINEL")
        self.calls = []

    def read(self, repo, *args):
        self.calls.append(args)
        if args == ("rev-parse", "HEAD"):
            return self.head.encode()
        if args == ("rev-parse", f"{flujo_source.PIN}^{{tree}}"):
            return self.tree.encode()
        if args == ("ls-tree", "-r", flujo_source.PIN):
            return "\n".join(f"{mode} {kind} {index:040x}\t{name}"
                             for index, (name, (mode, kind, _)) in enumerate(self.entries.items())).encode()
        if len(args) == 3 and args[:2] == ("cat-file", "blob"):
            return list(self.entries.values())[int(args[2], 16)][2]
        raise AssertionError(f"Unexpected operation: {args}")


class StockSourceTests(unittest.TestCase):
    def collect(self, fake=None):
        return flujo_source.collect(Path("not-a-real-checkout"), read=(fake or FakeGit()).read)

    def test_exact_source_closure_excludes_unrelated_private_files(self):
        files, manifest = self.collect()
        self.assertEqual(set(files), flujo_source.ROOT_FILES | {"src/example.ts"})
        self.assertNotIn(b"EXCLUDED PRIVATE SENTINEL", b"".join(files.values()))
        for record in manifest["files"]:
            self.assertEqual(record["sha256"], hashlib.sha256(files[record["path"]]).hexdigest())
        self.assertTrue(manifest["preparationOnly"])
        self.assertFalse(manifest["nativeIsolationProven"])
        self.assertFalse(manifest["runtimeExecution"])
        self.assertFalse(manifest["imageBuilt"])

    def test_wrong_commit_or_tree_does_not_read_blobs(self):
        for attr in ("head", "tree"):
            fake = FakeGit()
            setattr(fake, attr, "f" * 40)
            with self.subTest(attr=attr), self.assertRaises(ValueError):
                self.collect(fake)
            self.assertFalse(any(call[0] == "cat-file" for call in fake.calls))

    def test_domain_route_adapter_or_reexports_cannot_enter_stock_context(self):
        for prefix in flujo_source.DOMAIN_PREFIXES:
            fake = FakeGit()
            fake.entries[prefix + "example.ts"] = ("100644", "blob", b"export {}")
            with self.subTest(prefix=prefix), self.assertRaisesRegex(ValueError, "domain code"):
                self.collect(fake)

    def test_credentials_data_and_traversal_in_source_prefixes_are_denied(self):
        for name in ("src/.env.secret", "scripts/private/key.txt", "public/customer.parquet",
                     "bin/key.pem", "src/../private.json", "src//duplicate.ts", "src/with\\backslash.ts"):
            fake = FakeGit()
            fake.entries[name] = ("100644", "blob", b"PRIVATE SENTINEL")
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "Forbidden"):
                self.collect(fake)

    def test_symlinks_submodules_and_missing_build_inputs_are_denied(self):
        for mode, kind in (("120000", "blob"), ("160000", "commit")):
            fake = FakeGit()
            fake.entries["src/escape"] = (mode, kind, b"/private")
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "non-file"):
                self.collect(fake)
        fake = FakeGit()
        del fake.entries["Dockerfile"]
        with self.assertRaisesRegex(ValueError, "build inputs missing"):
            self.collect(fake)

    def test_manifest_cannot_overwrite_source_or_be_a_directory_ancestor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            out = root / "new-source"
            for manifest in (out / "Dockerfile", out / "nested" / "manifest.json", out, root):
                with self.subTest(manifest=manifest), patch.object(flujo_source, "collect") as reader:
                    with self.assertRaisesRegex(ValueError, "must not overlap"):
                        flujo_source.prepare(root, out, manifest)
                    reader.assert_not_called()
                    self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
