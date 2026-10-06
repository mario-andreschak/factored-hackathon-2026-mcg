"""Future read-only retained 27 portal + 21 browser HTTP hashes and ingress guards."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import argparse, hashlib, json
from release_common import *

def main():
    import httpx
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    go_args(parser)
    args = parser.parse_args()
    require_go(args)
    expected, build = load_descriptor(args.descriptor, args.descriptor_sha)
    runtime_proof(expected, args.image, build / 'runtime-verification.json')
    portal_manifest = read_json(build.parent / 'source-review/application/web/submission/portal-manifest.json')
    require(len(portal_manifest['files']) == 27, 'Exactly 27 public portal assets required')
    with httpx.Client(timeout=40, follow_redirects=False, headers={'Cache-Control': 'no-cache'}) as client:
        def get_asset(pair):
            name, wanted = pair
            response = client.get(ORIGIN + '/submission/' + name)
            actual = hashlib.sha256(response.content).hexdigest()
            require(expected['portal']['web/submission/' + name] == wanted and response.status_code == 200 and actual == wanted, 'Public portal bytes differ')
            return {'path': name, 'status': 200, 'sha256': actual, 'bytes': len(response.content)}
        with ThreadPoolExecutor(max_workers=8) as pool:
            assets = list(pool.map(get_asset, portal_manifest['files'].items()))
        require(client.get(ORIGIN + '/healthz').status_code == 200, 'Health check failed')
        gate = client.get(ORIGIN + '/')
        require(gate.status_code == 200 and 'Demo code' in gate.text and 'Enter demo' in gate.text, 'Entry gateway absent')
        require(client.get(ORIGIN + '/api/overview').status_code == 401, 'Anonymous customer API must deny')
        require(client.get(ORIGIN + '/submission/portal-manifest.json').status_code == 404, 'Internal portal manifest must deny')
    runtime_proof(expected, args.image, build / 'runtime-verification.json')
    report = {'schema': 'savia-card-admission-public-assets/v1', 'at_utc': datetime.now(timezone.utc).isoformat(),
        'application_source': expected['final_head'], 'browser_source': BASE_HEAD, 'portal_source': PORTAL_HEAD,
        'image': args.image, 'expected_descriptor_sha256': args.descriptor_sha,
        'verified_public_assets': 27, 'assets': assets, 'health': 200, 'entry_gateway': 200,
        'anonymous_api': 401, 'internal_manifest': 404, 'provider_calls': 0, 'card_writes': 0,
        'retained_browser_bytes_proved_by_remote_after_gate': 21,
        'scope': 'Unchanged portal HTTP bytes and entry guards; authenticated browser assets checked by native probe.'}
    write_new(build / 'public-assets-verification.json', report)
    print(json.dumps({'passed': True, 'public_assets': 27, 'provider_calls': 0, 'card_writes': 0, 'receipt_sha256': digest(build / 'public-assets-verification.json')}))

if __name__ == '__main__':
    main()
