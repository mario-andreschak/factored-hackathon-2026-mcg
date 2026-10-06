"""Future-only config capture or image-only promotion; no action at import time."""
import argparse, copy, json, subprocess
from datetime import datetime, timezone
from pathlib import Path
from successor_common import (APP, MACHINE, HEAD, BASE_IMAGE, PRIVATE, CONTEXT, read_json,
    load_context, require, require_go, go_args, image, write_new, digest)

CAPTURE = PRIVATE / 'accepted-44bc-machine.private.json'

def machine():
    data = json.loads(subprocess.check_output(['flyctl.exe', 'machine', 'list', '--app', APP, '--json']))
    found = [m for m in data if m['id'] == MACHINE]
    require(len(found) == 1 and found[0]['state'] == 'started', 'Exact started machine required')
    return found[0]

def config_guard(config):
    require(config['guest']['cpus'] == 2 and config['guest']['memory_mb'] == 4096, 'Accepted guest differs')
    require(len(config['mounts']) == 1 and config['mounts'][0]['path'] == '/data', 'Accepted persistent mount differs')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['capture', 'promote'])
    parser.add_argument('--image')
    parser.add_argument('--accepted-config', type=Path, default=CAPTURE)
    parser.add_argument('--preserved-config', type=Path, default=Path('C:/Users/Moe/.codex/tmp/savia-pitch-preserved-config.private.json'))
    go_args(parser)
    args = parser.parse_args()
    require_go(args)
    require(PRIVATE.resolve() in args.accepted_config.resolve().parents and args.accepted_config.name.endswith('.private.json'),
            'Complete config must remain in the fresh successor private directory, outside public build context')
    expected, _ = load_context(args.descriptor_sha)
    if args.mode == 'capture':
        require(args.image is None, 'Capture does not accept a target image')
        require(not args.accepted_config.exists(), 'Capture path must be new; do not replace predecessor evidence')
        current = machine()
        require(current['config']['image'] == BASE_IMAGE, 'Public machine is no longer the accepted 44bc image')
        config_guard(current['config'])
        baseline = read_json(args.preserved_config)
        baseline = baseline.get('config', baseline)
        require({k:v for k,v in current['config'].items() if k != 'image'} ==
                {k:v for k,v in baseline.items() if k != 'image'}, 'Full accepted machine configuration changed')
        write_new(args.accepted_config, current)  # Private: includes complete config; never copied into build context.
        print(json.dumps({'operation':'private complete 44bc config capture', 'machine_id':MACHINE,
              'image':BASE_IMAGE, 'source':HEAD, 'private_snapshot':str(args.accepted_config),
              'snapshot_sha256':digest(args.accepted_config), 'provider_calls':0, 'machine_writes':0}))
        return
    target = image(args.image or '')
    captured = read_json(args.accepted_config)
    require(captured['id'] == MACHINE and captured['state'] == 'started' and captured['config']['image'] == BASE_IMAGE,
            'A complete captured accepted44bc machine object is required')
    config_guard(captured['config'])
    current = machine()
    require(current['config'] == captured['config'], 'Complete live configuration differs from captured accepted44bc')
    config_guard(current['config'])
    wanted = copy.deepcopy(current['config'])
    wanted['image'] = target
    PRIVATE.mkdir(parents=True, exist_ok=True)
    config_file = PRIVATE / 'successor-promote-config.private.json'
    before_file = PRIVATE / 'successor-before-machine.private.json'
    operation_file = PRIVATE / 'successor-promote-output.private.txt'
    after_file = PRIVATE / 'successor-after-machine.private.json'
    require(all(not p.exists() for p in [config_file,before_file,operation_file,after_file]), 'Fresh private promotion filenames required')
    write_new(before_file, current)
    write_new(config_file, wanted)
    operation = subprocess.run(['flyctl.exe','machine','update',MACHINE,'--app',APP,'--image',target,
        '--machine-config',str(config_file),'--yes','--wait-timeout','120'],capture_output=True,text=True,encoding='utf-8')
    with operation_file.open('x',encoding='utf-8') as stream:
        stream.write(operation.stdout + '\n' + operation.stderr)
    require(operation.returncode == 0, 'Machine update failed; review private output, do not retry automatically')
    after = machine()
    write_new(after_file, after)
    require(after['config'] == wanted, 'Post-update full configuration differs; do not claim preservation')
    report = {'schema':'savia-ack-successor-promotion/v1','at_utc':datetime.now(timezone.utc).isoformat(),
        'application_source':HEAD,'previous_image':BASE_IMAGE,'image':target,'machine_id':MACHINE,
        'expected_descriptor_sha256':args.descriptor_sha,'accepted_private_snapshot_sha256':digest(args.accepted_config),
        'configuration_preserved':True,'provider_calls':0,
        'scope':'Image-only machine update. Runtime bytes, HTTP assets and native playback still require independent future qualification.'}
    write_new(CONTEXT / 'promotion-verification.json', report)
    print(json.dumps(report))

if __name__ == '__main__':
    main()
