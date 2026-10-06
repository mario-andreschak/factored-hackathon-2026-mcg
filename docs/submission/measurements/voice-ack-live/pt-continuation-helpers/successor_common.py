"""Offline descriptor validation. Importing this module performs no network action."""
from pathlib import Path, PurePosixPath
from datetime import datetime, timezone
import hashlib, json, re

HEAD = 'c44d416fcf1ab95bcb16c77651418e6570d79782'
TREE = 'fabf02d622f51302e229137405e3607356d00ab0'
DESCRIPTOR_SHA = '3d200c1f58957b3b3a032dbde642633e6c34eee70c7bee26734cdf0e1d137dd9'
PORTAL_HEAD = '634aa5244374b3e105ef7864fa100530bab45ec2'
BASE_IMAGE = 'registry.fly.io/savia-rc-2026@sha256:44bc554cd82ad62db51d536d580df248cbb188d24732e7ec1ed8133617c632a0'
APP = 'savia-rc-2026'
MACHINE = '851d7dc4460048'
BASE_URL = 'https://savia-rc-2026.fly.dev'
TMP = Path('C:/Users/Moe/.codex/tmp')
CONTEXT = TMP / ('savia-ui-runtime-' + HEAD[:12])
PRIVATE = TMP / ('savia-ack-successor-private-' + HEAD[:12])
CRITICAL = {
    'frontend/server/conversation.py': '6032e3ae6ba78a70f26d8ead44629450d0c5270ee614339c9a80e4a0b4bea795',
    'frontend/server/voice.py': 'eb5c758ad232e43eed522f14b518e8eb9272d31cb92cb61b753e4dce55c75616',
    'deploy/rc/run.py': '4e245c0c35556b39d25196276b216edeb53084b8f410e09c7790b94219ba3075',
}

def require(ok, message):
    if not ok:
        raise RuntimeError(message)

def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()

def digest(file):
    file = Path(file)
    require(file.is_file() and not file.is_symlink(), 'Regular file required: ' + str(file))
    return sha_bytes(file.read_bytes())

def read_json(file):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate JSON key')
            result[key] = value
        return result
    return json.loads(Path(file).read_text(encoding='utf-8'), object_pairs_hook=unique)

def image(value):
    require(bool(re.fullmatch(r'registry\.fly\.io/savia-rc-2026@sha256:[0-9a-f]{64}', value)), 'Exact RC image digest required')
    require(value != BASE_IMAGE, 'Successor image must differ from accepted 44bc')
    return value

def safe_file(base, name):
    value = PurePosixPath(name)
    require(name and value.as_posix() == name and not value.is_absolute() and '..' not in value.parts
            and '\\' not in name and ':' not in name, 'Unsafe relative path')
    target = base / name
    require(base.resolve() in target.resolve().parents, 'Path escaped context')
    current = target
    while current != base:
        require(not current.is_symlink(), 'Symlink denied')
        current = current.parent
    return target

def verify(files, base):
    for name, wanted in files.items():
        require(bool(re.fullmatch('[0-9a-f]{64}', wanted)), 'Invalid file digest')
        require(digest(safe_file(base, name)) == wanted, 'Hash mismatch: ' + name)

def load_context(descriptor_sha):
    require(descriptor_sha == DESCRIPTOR_SHA, 'Exact reviewed c44 descriptor digest required')
    require(CONTEXT.is_dir() and not CONTEXT.is_symlink(), 'Expected immutable context missing')
    descriptor = CONTEXT / 'expected-ui-runtime.json'
    require(digest(descriptor) == descriptor_sha, 'Descriptor digest differs')
    expected = read_json(descriptor)
    require(expected['schema'] == 'savia-ui-successor-guards/v1', 'Unexpected descriptor schema')
    require(expected['final_head'] == HEAD and expected['final_tree'] == TREE, 'Successor source pin differs')
    require(expected['accepted_head'] == expected['portal_head'] == PORTAL_HEAD, 'Retained source/portal pin differs')
    require(expected['accepted_source_manifest_sha256'] == '17382e0776ce03e5ec9ee43680f3112768aeba34df9818c7427d83bf70d6eb0a'
            and expected['portal_source_manifest_sha256'] == '652268ee73698b9f73219da6b2a5482bcfbab4efb02fcee7776f7ab9d16b57b7', 'Accepted metadata differs')
    require(len(expected['old_sources']) == len(expected['new_sources']) == 183 and len(expected['old_browser']) == 22
            and len(expected['native']) == 4 and len(expected['portal']) == 28 and len(expected['retained_pitch_media']) == 16,
            'Expected component counts differ')
    allowed = {'frontend/src/avatar/useSaviaVoice.ts', 'frontend/src/avatar/native-voice.test.tsx'}
    require(set(expected['old_sources']) == set(expected['new_sources']) and
            {p for p in expected['old_sources'] if expected['old_sources'][p] != expected['new_sources'][p]} == allowed,
            'Unreviewed exported source delta')
    require(expected['critical_server_sources'] == CRITICAL, 'Native6219 server bytes differ')
    require(len(expected['new_browser']) == 21 and expected['new_browser'] != expected['old_browser'], 'Fresh browser build required')
    require(expected['final_source_manifest_sha256'] == '6ad47268b2d09dac11fdb74b9f73bff436b8aeed16ae183b15cf824f3828f806'
            and expected['build_provenance_sha256'] == '666544efb1bf6afa6a4b0f053982fc70be2c776c1123fe237a17c2703bfd061e', 'Reviewed c44 source/build provenance differs')
    require(set(expected['native']) == {'/opt/runtime-ops/start.mjs', '/opt/runtime-ops/controller.mjs',
            '/app/package-lock.json', '/app/.next/BUILD_ID'}, 'Native runtime path set differs')
    app = CONTEXT / 'application'
    verify(expected['new_sources'], app)
    verify(expected['portal'], app)
    verify(expected['retained_pitch_media'], app)
    verify(CRITICAL, app)
    verify(expected['new_browser'], CONTEXT / 'browser-dist')
    require({p.relative_to(CONTEXT / 'browser-dist').as_posix() for p in (CONTEXT / 'browser-dist').rglob('*') if p.is_file()}
            == set(expected['new_browser']), 'Browser inventory includes missing/stale files')
    require(digest(app / 'source-manifest.json') == expected['final_source_manifest_sha256'], 'Source metadata differs')
    manifest = read_json(app / 'source-manifest.json')
    require(manifest['git_head'] == HEAD and manifest['git_tree'] == TREE and manifest['files'] == expected['new_sources'], 'Source map differs')
    require(manifest['components']['portal'] == expected['retained_portal_component'] and
            manifest['components']['browser_build'] == expected['browser_component'], 'Component provenance differs')
    require(digest(app / 'portal-source-manifest.json') == expected['portal_source_manifest_sha256'], 'Portal metadata differs')
    require(digest(CONTEXT / 'browser-build-provenance.json') == expected['build_provenance_sha256'], 'Browser build provenance differs')
    build = read_json(CONTEXT / 'browser-build-provenance.json')
    require(build['git_head'] == HEAD and build['built_public_files'] == expected['new_browser'], 'Browser source/build differs')
    verify(build['build_inputs'], app)
    require(digest(CONTEXT / 'verify_ui_layer.py') == 'be18516367db625156c97244419c21047f7de3c69885023ae30d562203f11d7c', 'Reviewed AFTER verifier differs')
    return expected, manifest

def require_go(args):
    require(args.root_go and args.frozen_cohort_complete, 'Explicit root GO and completed five frozen5c reviews required')

def proof(expected, target_image, file=None):
    file = Path(file or CONTEXT / 'runtime-verification.json')
    value = read_json(file)
    require(value['schema'] == 'savia-ack-successor-runtime/v1' and value['application_source'] == HEAD and value['git_tree'] == TREE
            and value['image'] == image(target_image) and value['portal_source'] == PORTAL_HEAD, 'Successor runtime binding differs')
    require(value['expected_descriptor_sha256'] == digest(CONTEXT / 'expected-ui-runtime.json') and
            value['source_manifest_sha256'] == expected['final_source_manifest_sha256'] and
            value['source_hashes'] == expected['new_sources'] and value['served_ui'] == expected['new_browser'] and
            value['retained_runtime_hashes'] == expected['native'] and value['portal_hashes'] == expected['portal'], 'Runtime byte proof differs')
    require(value['fresh_browser_verified'] is True and value['preserved_native_runtime'] is True
            and value['preserved_machine_configuration'] is True and value['machine_state'] == 'started', 'Runtime checks incomplete')
    at = datetime.fromisoformat(value['reverified_at_utc'].replace('Z', '+00:00'))
    require(at.tzinfo is not None and -30 <= (datetime.now(timezone.utc) - at).total_seconds() <= 900, 'Runtime proof must be within 15 minutes')
    return value, file

def write_new(file, value):
    file = Path(file)
    file.parent.mkdir(parents=True, exist_ok=True)
    with file.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, indent=2) + '\n')

def go_args(parser):
    parser.add_argument('--root-go', action='store_true')
    parser.add_argument('--frozen-cohort-complete', action='store_true')
    parser.add_argument('--descriptor-sha', required=True)
