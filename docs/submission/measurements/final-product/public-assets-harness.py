from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import argparse, hashlib, json, httpx
parser = argparse.ArgumentParser()
parser.add_argument('revision')
parser.add_argument('image')
args = parser.parse_args()
context = Path('C:/Users/Moe/.codex/tmp') / ('savia-final-runtime-' + args.revision[:12])
manifest = json.loads((context / 'application/web/submission/portal-manifest.json').read_text())
base = 'https://savia-rc-2026.fly.dev'
assert len(manifest['files']) == 27
with httpx.Client(timeout=40, follow_redirects=False, headers={'Cache-Control':'no-cache'}) as client:
    def get_asset(pair):
        name, wanted = pair
        url = base + '/submission/' + name
        response = client.get(url)
        digest = hashlib.sha256(response.content).hexdigest()
        assert response.status_code == 200, (name, response.status_code)
        assert digest == wanted, name
        return {'path': name, 'url':url, 'status':response.status_code,
                'sha256':digest, 'bytes':len(response.content),
                'content_type':response.headers.get('content-type')}
    with ThreadPoolExecutor(max_workers=8) as pool:
        assets = list(pool.map(get_asset, manifest['files'].items()))
    health = client.get(base + '/healthz')
    assert health.status_code == 200
    gate = client.get(base + '/')
    assert gate.status_code == 200 and 'Demo code' in gate.text and 'Enter demo' in gate.text
    denied = client.get(base + '/api/overview')
    assert denied.status_code == 401
    private_manifest = client.get(base + '/submission/portal-manifest.json')
    assert private_manifest.status_code == 404
report = {'schema':'savia-final-public-assets/v1', 'at_utc':datetime.now(timezone.utc).isoformat(),
          'application_source':args.revision, 'portal_source':args.revision, 'image':args.image,
          'verified_public_assets':len(assets), 'assets':assets,
          'health':{'status':health.status_code},
          'anonymous_gateway':{'status':gate.status_code,'actual_code_form_present':True},
          'anonymous_customer_api_denied':{'status':denied.status_code},
          'internal_portal_manifest_not_public':{'status':private_manifest.status_code},
          'provider_calls':0, 'bank_writes':0,
          'scope':'Read-only public HTTP byte verification and entry guard checks; not a new customer voice or card action acceptance.'}
(context / 'public-assets-verification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'public_assets':len(assets),'health':200,'entry_gate':200,'anonymous_api':401,'internal_manifest':404,'receipt':str(context / 'public-assets-verification.json')}))
