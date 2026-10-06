"""Future read-only exact one-source delta, retained UI/native and full-config proof."""
import argparse, base64, json, subprocess
from datetime import datetime, timezone
from pathlib import Path
from release_common import *
from promote_successor import machine, config_guard, preserved_config

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--accepted-config', required=True, type=Path)
    go_args(parser)
    args = parser.parse_args()
    require_go(args)
    target = target_image(args.image)
    expected, build = load_descriptor(args.descriptor, args.descriptor_sha)
    snapshot = private_child(args.accepted_config)
    captured = read_json(snapshot)
    require(captured['id'] == MACHINE and captured['config']['image'] == BASE_IMAGE, 'Current d6be capture required')
    promotion = read_json(build / 'promotion-verification.json')
    require(promotion['application_source'] == expected['final_head'] and promotion['image'] == target and promotion['expected_descriptor_sha256'] == args.descriptor_sha and promotion['configuration_preserved'] is True and promotion['accepted_private_snapshot_sha256'] == digest(snapshot), 'Promotion/config binding differs')
    wanted = preserved_config(captured['config'], target)
    require(machine()['config'] == wanted, 'Complete machine configuration differs')
    verifier_sha = digest(ROOT / 'verify_server_layer.py')
    code = '''from pathlib import Path
import hashlib,json,runpy,sys
release=Path('/tmp/card-admission-release')
if hashlib.sha256((release/'expected-server-runtime.json').read_bytes()).hexdigest()!=DESCRIPTOR_SHA:
 raise RuntimeError('Descriptor admission failed')
if hashlib.sha256((release/'verify_server_layer.py').read_bytes()).hexdigest()!=VERIFIER_SHA:
 raise RuntimeError('Verifier admission failed')
sys.argv=[str(release/'verify_server_layer.py'),'after',DESCRIPTOR_SHA]
runpy.run_path(sys.argv[0],run_name='__main__')
expected=json.loads((release/'expected-server-runtime.json').read_text())
root=Path('/srv/savia')
def hashes(files,base):
 return {p:hashlib.sha256(((base/p) if base else Path(p)).read_bytes()).hexdigest() for p in files}
result={'manifest':json.loads((root/'source-manifest.json').read_text()),'source_hashes':hashes(expected['new_sources'],root),
 'served_ui':hashes(expected['new_browser'],root/'frontend/dist'),'retained_runtime_hashes':hashes(expected['native'],None),
 'portal_hashes':hashes(expected['portal'],root),'retained_pitch_media_hashes':hashes(expected['retained_pitch_media'],root),
 'source_manifest_sha256':hashlib.sha256((root/'source-manifest.json').read_bytes()).hexdigest(),
 'portal_source_manifest_sha256':hashlib.sha256((root/'portal-source-manifest.json').read_bytes()).hexdigest(),
 'browser_build_provenance_sha256':hashlib.sha256(Path('/tmp/ui-release/browser-build-provenance.json').read_bytes()).hexdigest(),
 'native_exact_configured':'native_exact' in (root/'deploy/rc/run.py').read_text()}
print('CARD_ADMISSION_PROOF '+json.dumps(result))
'''.replace('DESCRIPTOR_SHA', repr(args.descriptor_sha)).replace('VERIFIER_SHA', repr(verifier_sha))
    encoded = base64.b64encode(code.encode()).decode()
    command = 'python -c "import base64;exec(base64.b64decode(\'' + encoded + '\'))"'
    execution = subprocess.run(['flyctl.exe', 'ssh', 'console', '--app', APP, '--machine', MACHINE, '--command', command], check=True, capture_output=True, text=True, encoding='utf-8')
    records = [line[len('CARD_ADMISSION_PROOF '):] for line in execution.stdout.splitlines() if line.startswith('CARD_ADMISSION_PROOF ')]
    require(len(records) == 1, 'Exactly one completed AFTER proof required')
    observed = json.loads(records[0])
    require(observed['manifest']['git_head'] == expected['final_head'] and observed['manifest']['git_tree'] == expected['final_tree'] and observed['manifest']['files'] == expected['new_sources'] and observed['source_hashes'] == expected['new_sources'] and observed['served_ui'] == expected['new_browser'] and observed['retained_runtime_hashes'] == expected['native'] and observed['portal_hashes'] == expected['portal'] and observed['retained_pitch_media_hashes'] == expected['retained_pitch_media'] and observed['source_manifest_sha256'] == expected['final_source_manifest_sha256'] and observed['portal_source_manifest_sha256'] == PORTAL_MANIFEST_SHA and observed['browser_build_provenance_sha256'] == BUILD_PROVENANCE_SHA and observed['native_exact_configured'] is True, 'Runtime source/component proof differs')
    require(machine()['config'] == wanted, 'Machine configuration changed during verification')
    observed.update({'schema': 'savia-card-admission-runtime/v1', 'application_source': expected['final_head'], 'git_tree': expected['final_tree'],
        'browser_source': BASE_HEAD, 'portal_source': PORTAL_HEAD, 'image': target, 'machine_id': MACHINE, 'machine_state': 'started',
        'reverified_at_utc': datetime.now(timezone.utc).isoformat(), 'expected_descriptor_sha256': args.descriptor_sha,
        'preserved_machine_configuration': True, 'retained_browser_verified': True, 'preserved_native_runtime': True,
        'accepted_private_snapshot_sha256': digest(snapshot), 'provider_calls': 0, 'card_writes': 0,
        'scope': 'Exact runtime bytes/config only. Retained c44 canonical UI playback proof remains dated.'})
    write_new(build / 'runtime-verification.json', observed)
    print(json.dumps({'source': expected['final_head'], 'browser_source': BASE_HEAD, 'portal_source': PORTAL_HEAD, 'image': target,
        'source_files': 183, 'retained_browser_files': 21, 'retained_native_files': 4, 'portal_files': 28,
        'configuration_preserved': True, 'provider_calls': 0, 'receipt_sha256': digest(build / 'runtime-verification.json')}))

if __name__ == '__main__':
    main()
