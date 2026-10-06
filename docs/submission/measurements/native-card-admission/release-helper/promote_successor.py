"""Future-only fresh d6be full-config capture or image-only promotion; never at import."""
import argparse, copy, json, subprocess
from datetime import datetime, timezone
from pathlib import Path
from release_common import *

def machine():
    values = json.loads(subprocess.check_output(['flyctl.exe', 'machine', 'list', '--app', APP, '--json']))
    found = [x for x in values if x['id'] == MACHINE]
    require(len(found) == 1 and found[0]['state'] == 'started', 'Exact current started machine required')
    return found[0]

def config_guard(config):
    require({'image', 'env', 'init', 'services', 'guest', 'mounts'} <= set(config), 'Complete config with env/init/services/guest/mounts required')
    require(config['guest']['cpu_kind'] == 'shared' and config['guest']['cpus'] == 2 and config['guest']['memory_mb'] == 4096, 'Current shared 2 CPU / 4096 MB guest required')
    require(len(config['mounts']) == 1 and config['mounts'][0]['path'] == '/data' and config['mounts'][0].get('volume'), 'Exact persistent /data volume binding required')

def preserved_config(config, target):
    config_guard(config)
    wanted = copy.deepcopy(config)
    wanted['image'] = target_image(target)
    require({k:v for k,v in wanted.items() if k != 'image'} == {k:v for k,v in config.items() if k != 'image'}, 'Image-only configuration preservation failed')
    return wanted

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['capture', 'promote'])
    parser.add_argument('--image')
    parser.add_argument('--accepted-config', required=True, type=Path)
    go_args(parser)
    args = parser.parse_args()
    require_go(args)
    expected, build = load_descriptor(args.descriptor, args.descriptor_sha)
    snapshot = private_child(args.accepted_config)
    require(snapshot.name.endswith('.private.json'), 'Full config snapshot must be explicitly private')
    if args.mode == 'capture':
        require(args.image is None and not snapshot.exists(), 'Capture must use a fresh file and no target image')
        current = machine()
        require(current['config']['image'] == BASE_IMAGE, 'Capture must observe current d6be; old 44bc capture is invalid')
        config_guard(current['config'])
        write_new(snapshot, current)
        print(json.dumps({'operation': 'private complete CURRENT d6be config capture', 'machine_id': MACHINE, 'image': BASE_IMAGE, 'snapshot_sha256': digest(snapshot), 'provider_calls': 0, 'machine_writes': 0}))
        return
    target = target_image(args.image or '')
    captured = read_json(snapshot)
    require(captured['id'] == MACHINE and captured['state'] == 'started' and captured['config']['image'] == BASE_IMAGE, 'Fresh complete captured d6be machine required')
    config_guard(captured['config'])
    current = machine()
    require(current['config'] == captured['config'], 'Complete current machine config differs from captured d6be; stop')
    wanted = preserved_config(current['config'], target)
    operation_dir = private_child(snapshot.parent / 'promotion')
    require(not operation_dir.exists(), 'Fresh promotion directory required; never repeat automatically')
    operation_dir.mkdir()
    write_new(operation_dir / 'before-machine.private.json', current)
    config_file = operation_dir / 'successor-config.private.json'
    write_new(config_file, wanted)
    operation = subprocess.run(['flyctl.exe', 'machine', 'update', MACHINE, '--app', APP, '--image', target,
        '--machine-config', str(config_file), '--yes', '--wait-timeout', '120'], capture_output=True, text=True, encoding='utf-8')
    with (operation_dir / 'operation.private.txt').open('x', encoding='utf-8') as stream:
        stream.write(operation.stdout + '\n' + operation.stderr)
    require(operation.returncode == 0, 'Promotion failed; private output preserved; no automatic retry')
    after = machine()
    write_new(operation_dir / 'after-machine.private.json', after)
    require(after['config'] == wanted, 'Post-update full configuration differs; stop without claiming preservation')
    report = {'schema': 'savia-card-admission-promotion/v1', 'at_utc': datetime.now(timezone.utc).isoformat(),
        'application_source': expected['final_head'], 'previous_image': BASE_IMAGE, 'image': target, 'machine_id': MACHINE,
        'expected_descriptor_sha256': args.descriptor_sha, 'accepted_private_snapshot_sha256': digest(snapshot),
        'configuration_preserved': True, 'provider_calls': 0, 'scope': 'Image-only promotion; no runtime/customer/native acceptance claim.'}
    write_new(build / 'promotion-verification.json', report)
    print(json.dumps(report))

if __name__ == '__main__':
    main()
