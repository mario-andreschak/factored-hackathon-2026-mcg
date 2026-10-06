"""Future read-only public HTTP hashes. No provider/card requests."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import argparse, hashlib, json, httpx
from successor_common import (HEAD, PORTAL_HEAD, CONTEXT, BASE_URL, require_go, go_args,
    load_context, proof, read_json, require, write_new)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    go_args(parser)
    args = parser.parse_args()
    require_go(args)
    expected, _ = load_context(args.descriptor_sha)
    runtime, runtime_file = proof(expected, args.image)
    manifest = read_json(CONTEXT / 'application/web/submission/portal-manifest.json')
    require(len(manifest['files']) == 27, 'Expected27 public portal assets')
    with httpx.Client(timeout=40, follow_redirects=False, headers={'Cache-Control':'no-cache'}) as client:
        def get_asset(pair):
            name, wanted = pair
            require(expected['portal']['web/submission/' + name] == wanted, 'Public portal map differs from retained634')
            response = client.get(BASE_URL + '/submission/' + name)
            actual = hashlib.sha256(response.content).hexdigest()
            require(response.status_code == 200 and actual == wanted, 'Public portal byte mismatch: ' + name)
            return {'path':name,'status':response.status_code,'sha256':actual,'bytes':len(response.content)}
        with ThreadPoolExecutor(max_workers=8) as pool:
            assets = list(pool.map(get_asset, manifest['files'].items()))
        health = client.get(BASE_URL + '/healthz')
        require(health.status_code == 200, 'Health check failed')
        gate = client.get(BASE_URL + '/')
        require(gate.status_code == 200 and 'Demo code' in gate.text and 'Enter demo' in gate.text, 'Actual entry gateway absent')
        denied = client.get(BASE_URL + '/api/overview')
        require(denied.status_code == 401, 'Anonymous customer API must deny')
        private_manifest = client.get(BASE_URL + '/submission/portal-manifest.json')
        require(private_manifest.status_code == 404, 'Internal portal manifest must not be public')
    # Fresh browser_dist bytes were independently checked by the remote AFTER gate.
    proof(expected, args.image)
    report = {'schema':'savia-ack-successor-public-assets/v1','at_utc':datetime.now(timezone.utc).isoformat(),
        'application_source':HEAD,'browser_source':HEAD,'portal_source':PORTAL_HEAD,'image':args.image,
        'expected_descriptor_sha256':args.descriptor_sha,'verified_public_assets':27,'assets':assets,
        'health':200,'entry_gateway':200,'anonymous_api':401,'internal_manifest':404,
        'provider_calls':0,'card_writes':0,
        'scope':'Read-only unchanged portal HTTP bytes and entry guards; no new voice/card acceptance.'}
    write_new(CONTEXT / 'public-assets-verification.json', report)
    print(json.dumps({'passed':True,'public_assets':27,'provider_calls':0,'card_writes':0,
        'receipt':str(CONTEXT / 'public-assets-verification.json')}))

if __name__ == '__main__':
    main()
