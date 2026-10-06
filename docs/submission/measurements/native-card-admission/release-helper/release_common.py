"""Private preparation support. Imports and descriptor reads never use the network."""
from pathlib import Path, PurePosixPath
from datetime import datetime, timezone
import hashlib, json, re

ROOT = Path(__file__).resolve().parent
BASE_CONTEXT = Path('[private-local-path]')
BASE_HEAD = 'c44d416fcf1ab95bcb16c77651418e6570d79782'
BASE_TREE = 'fabf02d622f51302e229137405e3607356d00ab0'
BASE_IMAGE = 'registry.fly.io/savia-rc-2026@sha256:d6be33f27d777e9e9adf9f86ef1fb381c24e02aaf6579d5947c6482ee67dc05c'
BASE_DESCRIPTOR_SHA = '3d200c1f58957b3b3a032dbde642633e6c34eee70c7bee26734cdf0e1d137dd9'
BASE_MANIFEST_SHA = '6ad47268b2d09dac11fdb74b9f73bff436b8aeed16ae183b15cf824f3828f806'
BUILD_PROVENANCE_SHA = '666544efb1bf6afa6a4b0f053982fc70be2c776c1123fe237a17c2703bfd061e'
PORTAL_HEAD = '634aa5244374b3e105ef7864fa100530bab45ec2'
PORTAL_MANIFEST_SHA = '652268ee73698b9f73219da6b2a5482bcfbab4efb02fcee7776f7ab9d16b57b7'
CHANGED_SOURCE = 'frontend/server/conversation.py'
GRAPH_SOURCE = 'resources/dispute_workflow.flow.json'
CHANGED_SOURCES = {CHANGED_SOURCE, GRAPH_SOURCE}
FINAL_HEAD = 'f2fa597a481a87b5301531cf180f8f61d1f3ba70'
FINAL_TREE = '1638e0be90b1046bbada1972b6ace1ee62a8e4fa'
CONVERSATION_SHA = 'c978b41c6e2c9078a4659c9104a6fa60587a277417b1b926ff5ecc9d7813ec6d'
GRAPH_SHA = '43fd857863961f4d87d62b85c9a25ae261b59aa2e74d14c8b3e7cf8406a41d03'
APP = 'savia-rc-2026'
MACHINE = '[private-machine-id]'
ORIGIN = 'https://savia-rc-2026.fly.dev'
NATIVE_PATHS = {'/opt/runtime-ops/start.mjs', '/opt/runtime-ops/controller.mjs', '/app/package-lock.json', '/app/.next/BUILD_ID'}

def require(ok, message):
    if not ok:
        raise RuntimeError(message)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def digest(file):
    file = Path(file)
    require(file.is_file() and not file.is_symlink(), 'Regular file required')
    return sha(file.read_bytes())

def read_json(file):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate JSON key denied')
            result[key] = value
        return result
    return json.loads(Path(file).read_text(encoding='utf-8'), object_pairs_hook=unique)

def write_new(file, value):
    file = Path(file)
    file.parent.mkdir(parents=True, exist_ok=True)
    with file.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    return digest(file)

def private_child(file):
    file = Path(file).resolve()
    require(ROOT in file.parents and not file.is_symlink(), 'Only a private helper descendant is permitted')
    return file

def safe_file(base, name):
    p = PurePosixPath(name)
    require(name and p.as_posix() == name and not p.is_absolute() and '..' not in p.parts and '\\' not in name and ':' not in name, 'Unsafe relative path')
    target = base / name
    require(base.resolve() in target.resolve().parents, 'Path escaped base')
    cursor = target
    while cursor != base:
        require(not cursor.is_symlink(), 'Symlink denied')
        cursor = cursor.parent
    return target

def verify(files, base):
    for name, wanted in files.items():
        require(re.fullmatch('[0-9a-f]{64}', wanted) and digest(safe_file(base, name)) == wanted, 'File hash differs: ' + name)

def target_image(value):
    require(re.fullmatch(r'registry\.fly\.io/savia-rc-2026@sha256:[0-9a-f]{64}', value) and value != BASE_IMAGE, 'New immutable successor RC image required')
    return value

def descriptor_guard(e):
    require(e['schema'] == 'savia-card-admission-source-guards/v1' and e['base_image'] == BASE_IMAGE and e['accepted_head'] == BASE_HEAD and e['accepted_tree'] == BASE_TREE, 'Current d6be/c44 predecessor required')
    require(e['accepted_source_manifest_sha256'] == BASE_MANIFEST_SHA and e['portal_source_manifest_sha256'] == PORTAL_MANIFEST_SHA and e['build_provenance_sha256'] == BUILD_PROVENANCE_SHA, 'Retained metadata pins differ')
    require(re.fullmatch('[0-9a-f]{40}', e['final_head']) and re.fullmatch('[0-9a-f]{40}', e['final_tree']) and e['final_head'] != BASE_HEAD, 'Exact new committed source/tree required')
    require(e['final_head'] == FINAL_HEAD and e['final_tree'] == FINAL_TREE, 'Final replacement source/tree required')
    require(set(e['old_sources']) == set(e['new_sources']) and len(e['new_sources']) == 183 and {p for p in e['old_sources'] if e['old_sources'][p] != e['new_sources'][p]} == CHANGED_SOURCES and e['new_sources'][CHANGED_SOURCE] == CONVERSATION_SHA and e['new_sources'][GRAPH_SOURCE] == GRAPH_SHA, 'Only reviewed conversation.py + graph may differ in the 183 exported sources')
    require(len(e['old_browser']) == len(e['new_browser']) == 21 and e['old_browser'] == e['new_browser'], 'All 21 current UI bytes must be retained exactly')
    require(set(e['native']) == NATIVE_PATHS and len(e['portal']) == 28 and len(e['retained_pitch_media']) == 16 and e['portal_head'] == PORTAL_HEAD, 'Retained native/portal inventory differs')
    require(e['browser_component']['source'] == BASE_HEAD and e['browser_component']['git_tree'] == BASE_TREE and e['browser_component']['public_files'] == 21, 'Browser provenance must remain c44')
    require(all(e['old_sources'][p] == e['new_sources'][p] == h for p, h in e['portal'].items()), 'Portal files changed')
    require(all(e['portal'][p] == h for p, h in e['retained_pitch_media'].items()), 'Pitch/media map differs')
    require(e['critical_unchanged'] == {p: e['old_sources'][p] for p in ['frontend/server/voice.py', 'deploy/rc/run.py']}, 'Unchanged voice/run sources required')
    return e

def load_descriptor(file, wanted):
    file = private_child(file)
    require(re.fullmatch('[0-9a-f]{64}', wanted) and digest(file) == wanted, 'Reviewed exact descriptor SHA required')
    return descriptor_guard(read_json(file)), file.parent

def require_go(args):
    require(args.root_go and args.frozen_cohort_complete, 'Explicit root GO and completed frozen reviews required')

def go_args(parser):
    parser.add_argument('--root-go', action='store_true')
    parser.add_argument('--frozen-cohort-complete', action='store_true')
    parser.add_argument('--descriptor', required=True, type=Path)
    parser.add_argument('--descriptor-sha', required=True)

def fresh(at):
    dt = datetime.fromisoformat(at.replace('Z', '+00:00'))
    require(dt.tzinfo is not None and -30 <= (datetime.now(timezone.utc) - dt).total_seconds() <= 900, 'Runtime proof must be within 15 minutes')

def runtime_proof(expected, image, file):
    file = private_child(file)
    value = read_json(file)
    require(value['schema'] == 'savia-card-admission-runtime/v1' and value['application_source'] == expected['final_head'] and value['git_tree'] == expected['final_tree'] and value['image'] == target_image(image), 'Exact successor runtime pin differs')
    require(value['source_manifest_sha256'] == expected['final_source_manifest_sha256'] and value['source_hashes'] == expected['new_sources'] and value['served_ui'] == expected['new_browser'] and value['retained_runtime_hashes'] == expected['native'] and value['portal_hashes'] == expected['portal'] and value['retained_pitch_media_hashes'] == expected['retained_pitch_media'], 'Runtime byte proof differs')
    require(value['machine_state'] == 'started' and value['preserved_machine_configuration'] is True and value['retained_browser_verified'] is True and value['preserved_native_runtime'] is True and value['browser_source'] == BASE_HEAD and value['portal_source'] == PORTAL_HEAD, 'Runtime checks incomplete')
    fresh(value['reverified_at_utc'])
    return value
