"""Future root GO binding from exact fresh runtime/public proof; no requests."""
import argparse, json
from pathlib import Path
from release_common import *

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--credentials', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    go_args(parser)
    args = parser.parse_args()
    require_go(args)
    expected, build = load_descriptor(args.descriptor, args.descriptor_sha)
    runtime_file = build / 'runtime-verification.json'
    runtime = runtime_proof(expected, args.image, runtime_file)
    public_file = build / 'public-assets-verification.json'
    public = read_json(public_file)
    require(public['schema'] == 'savia-card-admission-public-assets/v1' and public['application_source'] == expected['final_head'] and public['browser_source'] == BASE_HEAD and public['portal_source'] == PORTAL_HEAD and public['image'] == args.image and public['expected_descriptor_sha256'] == args.descriptor_sha and public['verified_public_assets'] == 27 and public['health'] == public['entry_gateway'] == 200 and public['anonymous_api'] == 401 and public['internal_manifest'] == 404, 'Successful exact successor public proof required')
    credentials = read_json(args.credentials)
    gateway = credentials.get('gateway', {})
    require(isinstance(credentials.get('code'), str) and credentials['code'] and all(isinstance(gateway.get(k), str) and gateway[k] for k in ['label','button','code']), 'Existing private fictional login/gateway credentials required')
    output = private_child(args.output)
    require(output.name.endswith('.private.json'), 'Binding must be a new private JSON file')
    binding = {'schema': 'savia-card-admission-native-message-binding/v1', 'root_go': True, 'frozen_cohort_complete': True,
        'generated_only': True, 'frozen_healthy': True, 'native_result_mode': 'native_exact',
        'authorization': {'approved_source_revision': expected['final_head'], 'approved_image_digest': args.image.split('@')[1]},
        'runtime': {'git_head': expected['final_head'], 'git_tree': expected['final_tree'], 'image_digest': args.image.split('@')[1],
            'source_manifest_sha256': runtime['source_manifest_sha256'], 'reverified_at_utc': runtime['reverified_at_utc'],
            'served_ui': expected['new_browser'], 'browser_source': BASE_HEAD, 'portal_source': PORTAL_HEAD},
        'expected_runtime_path': str(args.descriptor), 'expected_runtime_sha256': args.descriptor_sha,
        'runtime_proof_path': str(runtime_file), 'runtime_proof_sha256': digest(runtime_file),
        'public_assets_proof_path': str(public_file), 'public_assets_proof_sha256': digest(public_file),
        'native_harness_sha256': digest(ROOT / 'native_message_live.mjs'),
        'binding_gate_sha256': digest(ROOT / 'binding_gate.mjs'), 'event_gate_sha256': digest(ROOT / 'event_gate.mjs'),
        'base_url': ORIGIN, 'code': credentials['code'], 'gateway': {k: gateway[k] for k in ['label','button','code']},
        'cases': [{'language': 'es', 'profile': 'mexico'}, {'language': 'pt', 'profile': 'colombia'}],
        'scope': 'Exactly two direct native message admissions. No ASR, chat dispatch, card mutation, played ACK, result speech or fresh UI playback claim.'}
    write_new(output, binding)
    print(json.dumps({'binding_sha256': digest(output), 'source': expected['final_head'], 'browser_source': BASE_HEAD,
        'provider_calls_performed': 0, 'maximum_provider_calls': 2, 'card_writes': 0, 'played_acks': 0}))

if __name__ == '__main__':
    main()
