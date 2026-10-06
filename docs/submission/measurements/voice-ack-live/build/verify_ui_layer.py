"""Exact immutable source/browser guards; only enumerated validated UI files are removed."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import sys

ROOT = Path('/srv/savia')
DIST = ROOT / 'frontend/dist'
RELEASE = Path('/tmp/ui-release')


def read_json(text):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, 'Duplicate JSON key denied: ' + key)
            value[key] = item
        return value
    return json.loads(text, object_pairs_hook=unique)


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def safe_path(base, name):
    value = PurePosixPath(name)
    require(name and not value.is_absolute() and value.as_posix() == name and
            '..' not in value.parts and '\\' not in name and ':' not in name,
            'Unsafe relative path: ' + name)
    require(base.resolve() == base and not base.is_symlink(), 'Unvalidated root: ' + str(base))
    target = base / name
    require(base in target.resolve().parents, 'Path escaped root: ' + name)
    current = target
    while current != base:
        require(not current.is_symlink(), 'Symlink denied: ' + str(current))
        current = current.parent
    return target


def digest(path):
    require(path.is_file() and not path.is_symlink(), 'Regular file required: ' + str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(files, base):
    for name, wanted in files.items():
        require(digest(safe_path(base, name)) == wanted, 'Hash mismatch: ' + name)


def inventory(base):
    require(base.is_dir() and base.resolve() == base and not base.is_symlink(), 'Unsafe UI root')
    names = set()
    for item in base.rglob('*'):
        require(not item.is_symlink(), 'UI symlink denied')
        require(item.is_dir() or item.is_file(), 'Nonregular UI entry denied')
        if item.is_file():
            names.add(item.relative_to(base).as_posix())
    return names


def native(expected):
    allowed = {'/opt/runtime-ops/start.mjs', '/opt/runtime-ops/controller.mjs',
               '/app/package-lock.json', '/app/.next/BUILD_ID'}
    require(set(expected['native']) == allowed, 'Native path set changed')
    for name, wanted in expected['native'].items():
        target = Path(name)
        current = target
        while current != current.parent:
            require(not current.is_symlink(), 'Native symlink denied')
            current = current.parent
        require(digest(target) == wanted, 'Native hash mismatch: ' + name)


def source_metadata(expected, phase):
    prefix = 'accepted' if phase == 'before' else 'final'
    require(digest(ROOT / 'source-manifest.json') == expected[prefix + '_source_manifest_sha256'],
            'Source manifest hash mismatch')
    manifest = read_json((ROOT / 'source-manifest.json').read_text())
    require(manifest['git_head'] == expected[prefix + '_head'], 'Source revision mismatch')
    files = expected['old_sources'] if phase == 'before' else expected['new_sources']
    require(manifest['files'] == files and len(files) == 183, 'Source file map mismatch')
    verify(files, ROOT)
    require(digest(ROOT / 'portal-source-manifest.json') == expected['portal_source_manifest_sha256'],
            'Retained portal metadata changed')
    portal = read_json((ROOT / 'portal-source-manifest.json').read_text())
    require(portal['git_head'] == expected['portal_head'] and portal['files'] == expected['portal'],
            'Retained portal source map mismatch')
    verify(expected['portal'], ROOT)
    verify(expected['retained_pitch_media'], ROOT)
    verify(expected['critical_server_sources'], ROOT)
    if phase == 'after':
        require(manifest['git_tree'] == expected['final_tree'], 'Source tree mismatch')
        require(manifest['components']['portal'] == expected['retained_portal_component'],
                'Portal component provenance changed')
        require(manifest['components']['browser_build'] == expected['browser_component'],
                'Browser component provenance mismatch')
        require(digest(RELEASE / 'browser-build-provenance.json') == expected['build_provenance_sha256'],
                'Build provenance hash mismatch')
        provenance = read_json((RELEASE / 'browser-build-provenance.json').read_text())
        require(provenance['git_head'] == expected['final_head'] and
                provenance['built_public_files'] == expected['new_browser'], 'Built UI provenance mismatch')
        verify(provenance['build_inputs'], ROOT)


def before(expected):
    source_metadata(expected, 'before')
    require(inventory(DIST) == set(expected['old_browser']), 'Old UI inventory differs from accepted 22 files')
    verify(expected['old_browser'], DIST)
    native(expected)


def main():
    require(len(sys.argv) == 3 and sys.argv[1] in {'before', 'remove-ui', 'after'} and
            len(sys.argv[2]) == 64 and all(c in '0123456789abcdef' for c in sys.argv[2]),
            'Explicit phase and Docker-pinned expected descriptor hash required')
    require(ROOT.resolve() == ROOT and DIST.resolve() == DIST, 'Validated absolute application/UI roots required')
    require(digest(RELEASE / 'expected-ui-runtime.json') == sys.argv[2], 'Expected descriptor modified')
    expected = read_json((RELEASE / 'expected-ui-runtime.json').read_text())
    require(expected['accepted_head'] == '634aa5244374b3e105ef7864fa100530bab45ec2' and
            expected['accepted_source_manifest_sha256'] == '17382e0776ce03e5ec9ee43680f3112768aeba34df9818c7427d83bf70d6eb0a' and
            expected['portal_source_manifest_sha256'] == '652268ee73698b9f73219da6b2a5482bcfbab4efb02fcee7776f7ab9d16b57b7',
            'Accepted634 source/portal pin mismatch')
    require(len(expected['old_sources']) == len(expected['new_sources']) == 183 and
            len(expected['old_browser']) == 22 and len(expected['native']) == 4 and
            len(expected['portal']) == 28 and len(expected['retained_pitch_media']) == 16,
            'Expected component counts changed')
    allowed = {'frontend/src/avatar/useSaviaVoice.ts', 'frontend/src/avatar/native-voice.test.tsx'}
    changed = {p for p in expected['old_sources'] if expected['old_sources'][p] != expected['new_sources'].get(p)}
    require(set(expected['old_sources']) == set(expected['new_sources']) and changed == allowed,
            'Unreviewed exported source delta')
    phase = sys.argv[1]
    if phase in ('before', 'remove-ui'):
        before(expected)
        if phase == 'remove-ui':
            # Verify every byte and the complete inventory immediately before the first unlink.
            targets = [safe_path(DIST, name) for name in sorted(expected['old_browser'])]
            require(all(digest(p) == expected['old_browser'][p.relative_to(DIST).as_posix()] for p in targets),
                    'UI changed before deletion')
            for target in targets:
                target.unlink()  # File-only deletion of validated paths; no recursive delete or computed shell command.
            require(not inventory(DIST), 'Stale browser files remain')
    else:
        source_metadata(expected, 'after')
        require(inventory(DIST) == set(expected['new_browser']), 'New UI contains missing or stale files')
        verify(expected['new_browser'], DIST)
        native(expected)
    print(json.dumps({'phase': phase, 'source_files': 183, 'browser_files':
        len(expected['old_browser']) if phase == 'before' else 0 if phase == 'remove-ui' else len(expected['new_browser']),
        'removed_old_browser_files': len(expected['old_browser']) if phase == 'remove-ui' else 0,
        'retained_native_files': 4, 'retained_portal_files': 28, 'source_integrity': True}))


if __name__ == '__main__':
    main()
