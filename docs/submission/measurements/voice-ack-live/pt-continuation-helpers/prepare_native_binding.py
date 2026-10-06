"""Future explicit-GO binding creation from fresh runtime proof and private credentials."""
import argparse, json
from pathlib import Path
from successor_common import (HEAD, PORTAL_HEAD, CONTEXT, PRIVATE, BASE_URL, go_args,
    require_go, load_context, proof, read_json, require, write_new, digest)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--prior-es-receipt-sha', required=True)
    parser.add_argument('--credentials', required=True, type=Path,
        help='Private existing binding/template; only code and gateway credentials are reused')
    parser.add_argument('--output', type=Path, default=PRIVATE / 'pt-continuation-binding.private.json')
    go_args(parser)
    args = parser.parse_args()
    require_go(args)
    prior_path = Path('C:/Users/Moe/.codex/tmp/savia-ack-successor-native-private-c44d416fcf1a/2026-10-06T01-48-18-527Z/receipt-private.json')
    prior_sha = '67c436c315c0bb729ff5c68bc3d6919cea9eb5c5076d5a410f044e4960bd5c9e'
    require(args.prior_es_receipt_sha == prior_sha and digest(prior_path) == prior_sha, 'Explicit exact prior ES partial receipt approval required')
    expected, _ = load_context(args.descriptor_sha)
    runtime, runtime_file = proof(expected, args.image)
    public_file = CONTEXT / 'public-assets-verification.json'
    public = read_json(public_file)
    require(public['schema'] == 'savia-ack-successor-public-assets/v1' and public['application_source'] == HEAD
        and public['portal_source'] == PORTAL_HEAD and public['image'] == args.image
        and public['expected_descriptor_sha256'] == args.descriptor_sha and public['verified_public_assets'] == 27
        and public['health'] == 200 and public['entry_gateway'] == 200 and public['anonymous_api'] == 401
        and public['internal_manifest'] == 404, 'Successful successor public/health guards required before healthy binding')
    credentials = read_json(args.credentials)
    gateway = credentials.get('gateway', {})
    require(isinstance(credentials.get('code'), str) and credentials['code'] and
        all(isinstance(gateway.get(k), str) and gateway[k] for k in ['label','button','code']), 'Actual private login/gateway credentials required')
    require(PRIVATE.resolve() in args.output.resolve().parents and args.output.name.endswith('.private.json'), 'Binding must remain in successor private directory')
    here = Path(__file__).parent
    binding = {'schema':'savia-ack-pt-continuation-native-binding/v1','root_go':True,'frozen_cohort_complete':True,
        'generated_only':True,'frozen_healthy':True,'native_result_mode':'native_exact',
        'authorization':{'approved_source_revision':HEAD,'approved_image_digest':args.image.split('@')[1], 'approved_prior_es_attempt_sha256':prior_sha},
        'prior_es_attempt_path':str(prior_path), 'prior_es_attempt_sha256':prior_sha,
        'runtime':{'git_head':HEAD,'git_tree':expected['final_tree'],'image_digest':args.image.split('@')[1],
            'source_manifest_sha256':runtime['source_manifest_sha256'],'reverified_at_utc':runtime['reverified_at_utc'],
            'served_ui':expected['new_browser'],'browser_source':HEAD,'portal_source':PORTAL_HEAD},
        'expected_ui_runtime_path':str(CONTEXT / 'expected-ui-runtime.json'),
        'expected_ui_runtime_sha256':args.descriptor_sha,
        'runtime_proof_path':str(runtime_file),'runtime_proof_sha256':digest(runtime_file),
        'public_assets_proof_path':str(public_file),'public_assets_proof_sha256':digest(public_file),
        'native_harness_sha256':digest(here / 'native_live.mjs'),
        'capture_helper_sha256':digest(here / 'capture_savia_audio.mjs'),
        'binding_gate_sha256':digest(here / 'binding_gate.mjs'),
        'base_url':BASE_URL,'code':credentials['code'],'gateway':{k:gateway[k] for k in ['label','button','code']},
        'cases':[{'language':'pt','profile':'colombia'}],
        'scope':'Future one PT-only product-UI native turn, one negative provider-ineligible rejection; ES already qualified in preserved failed batch, zero card writes. No ACK error is injected live.'}
    write_new(args.output, binding)
    print(json.dumps({'prepared_binding':str(args.output),'source':HEAD,'portal_source':PORTAL_HEAD,
        'browser_files':21,'maximum_provider_calls':1,'provider_calls_performed':0,'card_writes':0,
        'runtime_proof_must_remain_fresh_minutes':15}))

if __name__ == '__main__':
    main()
