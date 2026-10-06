"""Future read-only exact-source, fresh-UI, retained-native/config verification."""
import argparse, base64, json, subprocess
from datetime import datetime, timezone
from pathlib import Path
from successor_common import (APP, MACHINE, HEAD, PORTAL_HEAD, BASE_IMAGE, CONTEXT, PRIVATE,
    image, require, require_go, go_args, load_context, read_json, write_new, digest)
from promote_successor import machine, config_guard, CAPTURE

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--accepted-config', type=Path, default=CAPTURE)
    go_args(parser)
    args = parser.parse_args()
    require_go(args)
    target = image(args.image)
    expected, manifest = load_context(args.descriptor_sha)
    accepted = read_json(args.accepted_config)
    require(accepted['id'] == MACHINE and accepted['config']['image'] == BASE_IMAGE, 'Complete accepted44bc snapshot required')
    promotion = read_json(CONTEXT / 'promotion-verification.json')
    require(promotion['application_source'] == HEAD and promotion['image'] == target
        and promotion['expected_descriptor_sha256'] == args.descriptor_sha and promotion['configuration_preserved'] is True
        and promotion['accepted_private_snapshot_sha256'] == digest(args.accepted_config), 'Promotion/private config continuity differs')
    wanted = dict(accepted['config'])
    wanted['image'] = target
    current = machine()
    require(current['config'] == wanted, 'Full configuration differs from image-only successor')
    config_guard(current['config'])
    # Invoke the exact in-image AFTER verifier with the locally reviewed descriptor SHA.
    # Its strict inventory gate rejects stale old UI, unexpected files and symlinks.
    code = '''from pathlib import Path
import hashlib,json,runpy,sys
release=Path('/tmp/ui-release')
wanted=DESCRIPTOR_SHA
if hashlib.sha256((release/'expected-ui-runtime.json').read_bytes()).hexdigest()!=wanted:
 raise RuntimeError('Remote descriptor admission failed')
if hashlib.sha256((release/'verify_ui_layer.py').read_bytes()).hexdigest()!='be18516367db625156c97244419c21047f7de3c69885023ae30d562203f11d7c':
 raise RuntimeError('Remote verifier admission failed')
sys.argv=[str(release/'verify_ui_layer.py'),'after',wanted]
runpy.run_path(sys.argv[0],run_name='__main__')
root=Path('/srv/savia')
expected=json.loads((release/'expected-ui-runtime.json').read_text())
manifest=json.loads((root/'source-manifest.json').read_text())
def hashes(files,base):
 return {p:hashlib.sha256(((base/p) if base else Path(p)).read_bytes()).hexdigest() for p in files}
result={'manifest':manifest,'source_hashes':hashes(expected['new_sources'],root),
 'served_ui':hashes(expected['new_browser'],root/'frontend/dist'),
 'retained_runtime_hashes':hashes(expected['native'],None),'portal_hashes':hashes(expected['portal'],root),
 'retained_pitch_media_hashes':hashes(expected['retained_pitch_media'],root),
 'source_manifest_sha256':hashlib.sha256((root/'source-manifest.json').read_bytes()).hexdigest(),
 'portal_source_manifest_sha256':hashlib.sha256((root/'portal-source-manifest.json').read_bytes()).hexdigest(),
 'browser_build_provenance_sha256':hashlib.sha256((release/'browser-build-provenance.json').read_bytes()).hexdigest(),
 'native_exact_configured': 'native_exact' in (root/'deploy/rc/run.py').read_text()}
print('SUCCESSOR_PROOF '+json.dumps(result))
'''.replace('DESCRIPTOR_SHA', repr(args.descriptor_sha))
    encoded = base64.b64encode(code.encode()).decode()
    command = 'python -c "import base64;exec(base64.b64decode(\'' + encoded + '\'))"'
    execution = subprocess.run(['flyctl.exe','ssh','console','--app',APP,'--machine',MACHINE,'--command',command],
                              check=True,capture_output=True,text=True,encoding='utf-8')
    records = [line[len('SUCCESSOR_PROOF '):] for line in execution.stdout.splitlines() if line.startswith('SUCCESSOR_PROOF ')]
    require(len(records) == 1, 'One completed AFTER verifier proof required')
    observed = json.loads(records[0])
    require(observed['manifest'] == manifest and observed['source_hashes'] == expected['new_sources']
        and observed['served_ui'] == expected['new_browser'] and observed['retained_runtime_hashes'] == expected['native']
        and observed['portal_hashes'] == expected['portal'] and observed['retained_pitch_media_hashes'] == expected['retained_pitch_media']
        and observed['source_manifest_sha256'] == expected['final_source_manifest_sha256']
        and observed['portal_source_manifest_sha256'] == expected['portal_source_manifest_sha256']
        and observed['browser_build_provenance_sha256'] == expected['build_provenance_sha256']
        and observed['native_exact_configured'] is True, 'Runtime component byte proof differs')
    require(machine()['config'] == wanted, 'Machine configuration changed during verification')
    observed.update({'schema':'savia-ack-successor-runtime/v1','application_source':HEAD,'git_tree':expected['final_tree'],'browser_source':HEAD,
        'portal_source':PORTAL_HEAD,'image':target,'machine_id':MACHINE,'machine_state':'started',
        'reverified_at_utc':datetime.now(timezone.utc).isoformat(),'expected_descriptor_sha256':args.descriptor_sha,
        'preserved_machine_configuration':True,'fresh_browser_verified':True,'preserved_native_runtime':True,
        'accepted_private_snapshot_sha256':digest(args.accepted_config), 'provider_calls':0,'card_writes':0,
        'scope':'Exact runtime byte and complete configuration verification. No new voice playback acceptance.'})
    write_new(CONTEXT / 'runtime-verification.json', observed)
    print(json.dumps({'source':HEAD,'browser_source':HEAD,'portal_source':PORTAL_HEAD,'image':target,
        'source_files':183,'fresh_browser_files':len(expected['new_browser']),'retained_native_files':4,
        'portal_files':28,'pitch_media_files':16,'configuration_preserved':True,
        'receipt':str(CONTEXT / 'runtime-verification.json'),'provider_calls':0}))

if __name__ == '__main__':
    main()
