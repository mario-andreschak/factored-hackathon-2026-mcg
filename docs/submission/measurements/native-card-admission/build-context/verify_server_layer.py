"""Before/after verification; no browser deletion/recompile and no runtime mutation."""
from pathlib import Path, PurePosixPath
import hashlib, json, sys

ROOT = Path('/srv/savia')
DIST = ROOT / 'frontend/dist'
RELEASE = Path('/tmp/card-admission-release')
BASE_HEAD = 'c44d416fcf1ab95bcb16c77651418e6570d79782'
BASE_TREE = 'fabf02d622f51302e229137405e3607356d00ab0'
BASE_IMAGE = 'registry.fly.io/savia-rc-2026@sha256:d6be33f27d777e9e9adf9f86ef1fb381c24e02aaf6579d5947c6482ee67dc05c'
BASE_MANIFEST_SHA = '6ad47268b2d09dac11fdb74b9f73bff436b8aeed16ae183b15cf824f3828f806'
BUILD_SHA = '666544efb1bf6afa6a4b0f053982fc70be2c776c1123fe237a17c2703bfd061e'
PORTAL_HEAD = '634aa5244374b3e105ef7864fa100530bab45ec2'
PORTAL_SHA = '652268ee73698b9f73219da6b2a5482bcfbab4efb02fcee7776f7ab9d16b57b7'
NATIVE_PATHS = {'/opt/runtime-ops/start.mjs', '/opt/runtime-ops/controller.mjs', '/app/package-lock.json', '/app/.next/BUILD_ID'}
FINAL_HEAD = 'f2fa597a481a87b5301531cf180f8f61d1f3ba70'
FINAL_TREE = '1638e0be90b1046bbada1972b6ace1ee62a8e4fa'
CONVERSATION_SHA = 'c978b41c6e2c9078a4659c9104a6fa60587a277417b1b926ff5ecc9d7813ec6d'
GRAPH_SHA = '43fd857863961f4d87d62b85c9a25ae261b59aa2e74d14c8b3e7cf8406a41d03'

def require(ok, message):
    if not ok:
        raise RuntimeError(message)

def read_json(file):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate JSON key denied')
            result[key] = value
        return result
    return json.loads(Path(file).read_text(), object_pairs_hook=unique)

def digest(file):
    require(file.is_file() and not file.is_symlink(), 'Regular file required')
    cursor = file
    while cursor != cursor.parent:
        require(not cursor.is_symlink(), 'Symlink denied')
        cursor = cursor.parent
    return hashlib.sha256(file.read_bytes()).hexdigest()

def safe_file(base, name):
    p = PurePosixPath(name)
    require(name and p.as_posix() == name and not p.is_absolute() and '..' not in p.parts and '\\' not in name and ':' not in name, 'Unsafe relative path')
    target = base / name
    require(base.resolve() == base and base in target.resolve().parents, 'Path escaped validated absolute base')
    return target

def verify(files, base):
    for name, wanted in files.items():
        require(digest(safe_file(base, name)) == wanted, 'Hash mismatch: ' + name)

def inventory(base):
    require(base.is_dir() and base.resolve() == base and not base.is_symlink(), 'Validated absolute UI root required')
    files = set()
    for item in base.rglob('*'):
        require(not item.is_symlink() and (item.is_file() or item.is_dir()), 'Nonregular UI entry denied')
        if item.is_file():
            files.add(item.relative_to(base).as_posix())
    return files

def guard(e):
    require(e['schema'] == 'savia-card-admission-source-guards/v1' and e['base_image'] == BASE_IMAGE and e['accepted_head'] == BASE_HEAD and e['accepted_tree'] == BASE_TREE and e['accepted_source_manifest_sha256'] == BASE_MANIFEST_SHA, 'Current d6be/c44 predecessor required')
    require(e['final_head'] == FINAL_HEAD and e['final_tree'] == FINAL_TREE, 'Exact final replacement source/tree required')
    require(set(e['old_sources']) == set(e['new_sources']) and len(e['new_sources']) == 183 and {p for p in e['old_sources'] if e['old_sources'][p] != e['new_sources'][p]} == {'frontend/server/conversation.py','resources/dispute_workflow.flow.json'} and e['new_sources']['frontend/server/conversation.py'] == CONVERSATION_SHA and e['new_sources']['resources/dispute_workflow.flow.json'] == GRAPH_SHA, 'Only exact reviewed conversation + graph source delta required')
    require(e['old_browser'] == e['new_browser'] and len(e['new_browser']) == 21 and set(e['native']) == NATIVE_PATHS and len(e['portal']) == 28 and len(e['retained_pitch_media']) == 16, 'Retained 21/4/28/16 inventories differ')
    require(e['portal_head'] == PORTAL_HEAD and e['portal_source_manifest_sha256'] == PORTAL_SHA and e['build_provenance_sha256'] == BUILD_SHA, 'Retained metadata differs')
    require(all(e['old_sources'][p] == e['new_sources'][p] == h for p, h in e['portal'].items()), 'Portal changed')

def verify_phase(expected, phase):
    guard(expected)
    prefix = 'accepted' if phase == 'before' else 'final'
    files = expected['old_sources'] if phase == 'before' else expected['new_sources']
    require(digest(ROOT / 'source-manifest.json') == expected[prefix + '_source_manifest_sha256'], 'Source manifest hash mismatch')
    manifest = read_json(ROOT / 'source-manifest.json')
    require(manifest['git_head'] == expected[prefix + '_head'] and manifest['git_tree'] == expected[prefix + '_tree'] and manifest['files'] == files, 'Source metadata differs')
    verify(files, ROOT)
    verify(expected['portal'], ROOT)
    verify(expected['retained_pitch_media'], ROOT)
    verify(expected['critical_unchanged'], ROOT)
    require(digest(ROOT / 'portal-source-manifest.json') == PORTAL_SHA, 'Portal metadata changed')
    portal = read_json(ROOT / 'portal-source-manifest.json')
    require(portal['git_head'] == PORTAL_HEAD and portal['files'] == expected['portal'], 'Portal provenance differs')
    require(manifest['components']['browser_build'] == expected['browser_component'] and manifest['components']['portal'] == expected['retained_portal_component'], 'Retained component provenance changed')
    require(digest(Path('/tmp/ui-release/browser-build-provenance.json')) == BUILD_SHA, 'Retained c44 browser provenance changed')
    provenance = read_json(Path('/tmp/ui-release/browser-build-provenance.json'))
    require(provenance['git_head'] == BASE_HEAD and provenance['git_tree'] == BASE_TREE and provenance['built_public_files'] == expected['new_browser'], 'Retained c44 browser source differs')
    verify(provenance['build_inputs'], ROOT)
    require(inventory(DIST) == set(expected['new_browser']), 'Retained 21 UI inventory includes missing/stale files')
    verify(expected['new_browser'], DIST)
    for name, wanted in expected['native'].items():
        require(digest(Path(name)) == wanted, 'Native hash differs: ' + name)

def main():
    require(len(sys.argv) == 3 and sys.argv[1] in {'before', 'after'} and len(sys.argv[2]) == 64 and all(c in '0123456789abcdef' for c in sys.argv[2]), 'Explicit phase and pinned descriptor SHA required')
    require(digest(RELEASE / 'expected-server-runtime.json') == sys.argv[2], 'Descriptor bytes changed')
    expected = read_json(RELEASE / 'expected-server-runtime.json')
    verify_phase(expected, sys.argv[1])
    print(json.dumps({'phase': sys.argv[1], 'source_files': 183, 'retained_browser_files': 21, 'retained_native_files': 4, 'retained_portal_files': 28, 'source_integrity': True}))

if __name__ == '__main__':
    main()
