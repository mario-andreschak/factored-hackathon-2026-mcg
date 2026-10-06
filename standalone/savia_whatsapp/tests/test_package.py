import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import zipfile

import pytest

from standalone.savia_whatsapp import package


PRIVATE_MARKER = b"private-session-cookie-must-not-export"
OLD_BROWSERS = b"Browsers.windows('Desktop') : Browsers.macOS('Desktop')"
NEW_BROWSERS = b"Browsers.windows('Chrome') : Browsers.macOS('Chrome')"
BAILEYS_SOURCE = "src/services/baileys.ts"


@pytest.fixture
def source_tree(tmp_path, monkeypatch):
    root = tmp_path / "source"
    feature = root / "standalone/savia_whatsapp"
    public_feature = {
        "standalone/__init__.py": b"",
        "standalone/tests/test_whatsapp.py": b"def test_placeholder(): pass\n",
        "standalone/savia_whatsapp/__init__.py": b"# public feature\n",
        "standalone/savia_whatsapp/package.py": b"# public package source\n",
        "standalone/savia_whatsapp/runtime.py": b"# public supervisor source\n",
        "standalone/savia_whatsapp/README.md": b"# Local test setup\n",
        "standalone/savia_whatsapp/Dockerfile": b"FROM python:3.13\n",
        "standalone/savia_whatsapp/.dockerignore": b"private\n**/*session*\n",
        "standalone/savia_whatsapp/control.html": b"<title>Local test</title>\n",
        "standalone/savia_whatsapp/docs/video-notes.md": b"# Public video notes\n",
        "standalone/savia_whatsapp/docs/validation.json": b'{"offline":true}\n',
    }
    for name, payload in public_feature.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    # Simulate mistakenly putting personal --state below the feature directory.
    # These extensions were all accepted by the old recursive export approach.
    private_names = (
        "local-config.json", "whatsapp-session/credentials.json",
        "whatsapp-session/Default/Local Storage/session.json", "baileys-session/creds.json",
        "private/rc/fixture.json", "private/session-notes.md", "mcp.stderr.log", ".env",
    )
    for name in private_names:
        path = feature / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(PRIVATE_MARKER + b"\n" + str(path).encode())

    mcp = tmp_path / "whatsapp-mcp-checkout"
    mcp.mkdir()
    mcp_files = {
        "package.json": b'{"name":"tiny-mcp"}\n',
        "package-lock.json": b'{"lockfileVersion":3}\n',
        "tsconfig.json": b"{}\n",
        "LICENSE": b"Public license\n",
        "src/index.ts": b"export {};\n",
        BAILEYS_SOURCE: b"const browser = isWindows ? " + OLD_BROWSERS + b";\n",
        "public/index.html": b"<title>Pairing</title>\n",
        ".env": PRIVATE_MARKER,
        "whatsapp-session/credentials.json": PRIVATE_MARKER,
        "private/local-config.json": PRIVATE_MARKER,
    }
    for name, payload in mcp_files.items():
        path = mcp / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    modes = {name: b"100644" for name in mcp_files}
    calls = []

    def fake_git(repo, *args):
        if repo == root:
            assert args == ("rev-parse", "HEAD")
            return b"b" * 40 + b"\n"
        assert repo == mcp
        calls.append(args)
        if args == ("rev-parse", package.MCP_REVISION):
            return package.MCP_REVISION.encode() + b"\n"
        if args == ("ls-tree", "-r", "-z", package.MCP_REVISION):
            return b"".join(modes[name] + b" blob " + b"a" * 40 + b"\t" + name.encode() + b"\0"
                            for name in mcp_files)
        assert args[0] == "show"
        revision, name = args[1].split(":", 1)
        assert revision == package.MCP_REVISION
        return mcp_files[name]

    def export_rc(destination, revision):
        assert revision == package.RC_REVISION
        destination.mkdir(parents=True)
        (destination / "deploy/rc").mkdir(parents=True)
        (destination / "deploy/rc/run.py").write_bytes(b"# immutable public RC\n")
        (destination / "source-manifest.json").write_text(json.dumps({"git_head": revision}))

    class Loader:
        def create_module(self, spec):
            return None

        def exec_module(self, module):
            module.export = export_rc

    exporter_spec = importlib.util.spec_from_loader("rc_export", Loader())

    def fake_spec(name, location):
        assert name == "rc_export" and location == root / "deploy/rc/build_public_context.py"
        return exporter_spec

    monkeypatch.setattr(package, "ROOT", root)
    monkeypatch.setattr(package, "__file__", str(feature / "package.py"))
    monkeypatch.setattr(package, "git", fake_git)
    monkeypatch.setattr(package.importlib.util, "spec_from_file_location", fake_spec)
    return dict(root=root, feature=feature, mcp=mcp, mcp_files=mcp_files,
                modes=modes, calls=calls, public_feature=public_feature,
                private_names=private_names, destination=tmp_path / "output/bundle")


def test_export_allowlist_excludes_local_state_and_zip_hashes_match(source_tree, capsys):
    source = source_tree
    destination = source["destination"]
    package.build_package(destination, source["mcp"])
    receipt = json.loads(capsys.readouterr().out)
    archive = destination.with_suffix(".zip")
    assert Path(receipt["package"]) == archive
    assert receipt["sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()

    expected = set(source["public_feature"]) | {".dockerignore", "deploy/rc/run.py", "source-manifest.json"}
    expected |= {"whatsapp-mcp/" + name for name in source["mcp_files"]
                 if name in {"package.json", "package-lock.json", "tsconfig.json", "LICENSE"}
                 or name.startswith(("src/", "public/"))}
    with zipfile.ZipFile(archive) as zipped:
        manifest = json.loads(zipped.read("standalone-package.json"))
        assert manifest["schema"] == "savia-whatsapp-local-package/v1"
        assert manifest["rc_revision"] == package.RC_REVISION
        assert manifest["whatsapp_mcp_revision"] == package.MCP_REVISION
        assert manifest["feature_revision"] == "b" * 40
        original_baileys = source["mcp_files"][BAILEYS_SOURCE]
        exported_baileys = zipped.read("whatsapp-mcp/" + BAILEYS_SOURCE)
        assert exported_baileys == original_baileys.replace(OLD_BROWSERS, NEW_BROWSERS)
        assert OLD_BROWSERS not in exported_baileys and exported_baileys.count(NEW_BROWSERS) == 1
        assert manifest["mcp_overlays"] == [{
            "file": "whatsapp-mcp/" + BAILEYS_SOURCE,
            "kind": "browser-descriptor",
            "before_sha256": hashlib.sha256(original_baileys).hexdigest(),
            "after_sha256": hashlib.sha256(exported_baileys).hexdigest(),
            "reference": "https://github.com/WhiskeySockets/Baileys/issues/2671",
        }]
        assert manifest["state_included"] is manifest["secrets_included"] is manifest["real_bank_actions"] is False
        assert set(manifest["files"]) == expected
        assert set(zipped.namelist()) == expected | {"standalone-package.json"}
        for name in zipped.namelist():
            assert not Path(name).is_absolute() and ".." not in Path(name).parts
            data = zipped.read(name)
            assert PRIVATE_MARKER not in data and str(source["root"]).encode() not in data
            if name != "standalone-package.json":
                assert manifest["files"][name] == hashlib.sha256(data).hexdigest()
                assert data == (destination / name).read_bytes()
    assert receipt["files"] == len(expected)
    assert (source["mcp"] / BAILEYS_SOURCE).read_bytes() == source["mcp_files"][BAILEYS_SOURCE]
    assert not any((destination / "standalone/savia_whatsapp" / name).exists()
                   for name in source["private_names"])
    shown = {args[1].split(":", 1)[1] for args in source["calls"] if args[0] == "show"}
    assert not shown & {".env", "whatsapp-session/credentials.json", "private/local-config.json"}


@pytest.mark.parametrize("unreviewed_source", [NEW_BROWSERS + b";\n", (OLD_BROWSERS + b";\n") * 2],
                         ids=["already-modified", "ambiguous-preimage"])
def test_browser_overlay_requires_one_reviewed_preimage(source_tree, unreviewed_source):
    source = source_tree
    source["mcp_files"][BAILEYS_SOURCE] = unreviewed_source
    original = source["mcp"] / BAILEYS_SOURCE
    original.write_bytes(unreviewed_source)
    with pytest.raises(ValueError, match="browser descriptor no longer matches"):
        package.build_package(source["destination"], source["mcp"])
    assert not source["destination"].with_suffix(".zip").exists()
    assert not (source["destination"] / "standalone-package.json").exists()
    assert original.read_bytes() == unreviewed_source


@pytest.mark.parametrize("mode", [b"120000", b"160000"], ids=["symlink", "submodule"])
def test_nonregular_allowlisted_mcp_source_is_rejected(source_tree, mode):
    source = source_tree
    source["modes"]["src/index.ts"] = mode
    with pytest.raises(ValueError, match="Nonregular MCP source"):
        package.build_package(source["destination"], source["mcp"])
    assert not source["destination"].with_suffix(".zip").exists()
    assert not any(args == ("show", package.MCP_REVISION + ":src/index.ts") for args in source["calls"])


def make_symlink(link, target, *, directory=False):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"This test host cannot create symlinks: {error}")


def test_allowlisted_feature_file_cannot_copy_symlink_target(source_tree):
    source = source_tree
    target = source["root"].parent / "private-readme.md"
    target.write_bytes(PRIVATE_MARKER)
    link = source["feature"] / "README.md"
    link.unlink()
    make_symlink(link, target)
    with pytest.raises(ValueError, match="Symlink"):
        package.build_package(source["destination"], source["mcp"])
    assert not source["destination"].with_suffix(".zip").exists()
    assert not (source["destination"] / "standalone/savia_whatsapp/README.md").exists()


def test_allowlisted_feature_path_cannot_follow_symlinked_directory(source_tree):
    source = source_tree
    target = source["root"].parent / "private-docs"
    target.mkdir()
    (target / "video-notes.md").write_bytes(PRIVATE_MARKER)
    link = source["feature"] / "docs"
    shutil.rmtree(link)
    make_symlink(link, target, directory=True)
    with pytest.raises(ValueError, match="Symlink"):
        package.build_package(source["destination"], source["mcp"])
    assert not source["destination"].with_suffix(".zip").exists()
    assert not (source["destination"] / "standalone/savia_whatsapp/docs/video-notes.md").exists()
