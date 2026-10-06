import argparse
import concurrent.futures
import hashlib
import json
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

args = argparse.ArgumentParser()
args.add_argument('--portal-source', required=True)
args.add_argument('--runtime-source', required=True)
args.add_argument('--image', required=True)
opts = args.parse_args()
PIN = opts.portal_source
assert re.fullmatch(r'[0-9a-f]{40}', PIN)
assert re.fullmatch(r'[0-9a-f]{40}', opts.runtime_source)
assert re.fullmatch(r'(registry\.fly\.io/savia-rc-2026@)?sha256:[0-9a-f]{64}', opts.image)
BASE = 'https://savia-rc-2026.fly.dev/submission/'
manifest = json.loads(subprocess.check_output(['git', 'show', PIN + ':web/submission/portal-manifest.json']))
tree = set(subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', PIN], text=True).splitlines())

def fetch(entry):
    name, expected = entry
    request = urllib.request.Request(BASE + urllib.parse.quote(name), headers={'User-Agent':'Savia-submission-verifier/1'})
    with urllib.request.urlopen(request, timeout=40) as response:
        raw = response.read()
        result = {'path':name, 'status':response.status, 'bytes':len(raw), 'sha256':hashlib.sha256(raw).hexdigest()}
    assert result['status'] == 200 and result['sha256'] == expected, result
    urls = []
    if name.startswith('evidence/') and name.endswith('.md'):
        for url in re.findall(r'\]\(([^)]+)\)', raw.decode('utf-8')):
            parsed = urllib.parse.urlsplit(url)
            assert parsed.scheme in ('https', 'http') or url.startswith('#'), (name,url)
            if parsed.netloc == 'github.com' and parsed.path.startswith('/mario-andreschak/factored-hackathon-2026-mcg/blob/main/'):
                path = urllib.parse.unquote(parsed.path.split('/blob/main/',1)[1])
                assert path in tree or any(item.startswith(path.rstrip('/')+'/') for item in tree), (name,path)
            urls.append(url)
        result['markdown_links_checked'] = len(urls)
    return result

with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
    results = list(pool.map(fetch, manifest['files'].items()))

boundary = []
for path, allowed in [('submission/portal-manifest.json',(404,)),('submission/.env',(404,)),('submission/%2e%2e/.env',(401,404)),('api/bank/accounts',(401,))]:
    request = urllib.request.Request('https://savia-rc-2026.fly.dev/'+path)
    try:
        response = urllib.request.urlopen(request,timeout=20)
        actual = response.status
        response.close()
    except urllib.error.HTTPError as error:
        actual = error.code
    assert actual in allowed, (path,actual,allowed)
    boundary.append({'path':path,'status':actual})
with urllib.request.urlopen(urllib.request.Request(BASE,method='HEAD'),timeout=20) as response:
    assert response.status == 200 and response.read() == b''
    boundary.append({'path':'submission/','method':'HEAD','status':200,'body_bytes':0})
receipt = {'schema':'savia-live-public-portal-verification/v1','verified_at_utc':datetime.now(timezone.utc).isoformat(),'portal_source':PIN,'runtime_source':opts.runtime_source,'image':opts.image,'runtime_metadata_scope':'supplied from coordinator release receipt; this harness verifies public portal bytes and ingress, not runtime source','files':results,'boundary':boundary,'markdown_links_checked':sum(r.get('markdown_links_checked',0) for r in results)}
Path('.tmp/portal-release-'+PIN[:8]+'-verification.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'files_match':len(results),'markdown_links_checked':receipt['markdown_links_checked'],'boundary_checks':len(boundary),'portal_source':PIN}))
