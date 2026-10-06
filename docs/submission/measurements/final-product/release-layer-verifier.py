"""Verify the accepted base before copying, then the final immutable source."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import sys

root = Path('/srv/savia')
expected = json.loads(Path('/tmp/release/retained-runtime.json').read_text())

def digest(path):
    assert path.is_file() and not path.is_symlink(), str(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()

def verify(files, prefix):
    for name, wanted in files.items():
        parsed = PurePosixPath(name)
        assert '..' not in parsed.parts and chr(92) not in name, name
        if prefix is None:
            assert parsed.is_absolute(), name
            path = Path(name)
        else:
            assert not parsed.is_absolute(), name
            path = prefix / name
        assert digest(path) == wanted, name

assert sys.argv[1:] in (['before'], ['after'])
phase = sys.argv[1]
assert len(expected['sources']) == 183 and len(expected['browser']) == 22 and len(expected['native']) == 4
if phase == 'before':
    assert digest(root / 'source-manifest.json') == expected['accepted_source_manifest_sha256']
    manifest = json.loads((root / 'source-manifest.json').read_text())
    assert manifest['git_head'] == expected['accepted_head']
    assert manifest['files'] == expected['sources']
    verify(expected['sources'], root)
else:
    assert digest(root / 'source-manifest.json') == expected['final_source_manifest_sha256']
    assert digest(root / 'portal-source-manifest.json') == expected['final_portal_manifest_sha256']
    manifest = json.loads((root / 'source-manifest.json').read_text())
    portal = json.loads((root / 'portal-source-manifest.json').read_text())
    assert manifest['git_head'] == expected['final_head'] and manifest['git_tree'] == expected['final_tree']
    assert len(manifest['files']) == 183
    verify(manifest['files'], root)
    assert portal['git_head'] == expected['final_head'] and portal['git_tree'] == expected['final_tree']
    assert portal['files'] == {name: value for name, value in manifest['files'].items()
                               if name.startswith('web/submission/')}
    assert portal['original_portal_build'] == expected['original_portal_build']
    assert manifest['components']['portal']['git_head'] == expected['final_head']
    assert manifest['components']['portal']['git_tree'] == expected['final_tree']
    verify(expected['retained_public_assets'], root)
    verify(expected['critical_voice_sources'], root)
verify(expected['browser'], root / 'frontend/dist')
verify(expected['native'], None)
print(json.dumps({'phase': phase, 'verified_sources': 183, 'retained_browser_files': 22,
                  'retained_native_files': 4, 'retained_public_assets': len(expected['retained_public_assets']),
                  'source_integrity': True}))
