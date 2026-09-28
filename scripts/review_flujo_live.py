"""Synthetic review of a local FLUJO instance; no LLM, MCP tools or dataset.

Creates its own Start -> Static -> Finish flow and two conversations, verifies
their route behavior, then deletes only those exact created resources.
Run: python scripts/review_flujo_live.py --base http://localhost:4200
"""
import argparse
import concurrent.futures
import json
import time
import uuid
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--base', default='http://localhost:4200')
    args = p.parse_args()
    base = args.base.rstrip('/')
    assert urlparse(base).hostname in {'localhost', '127.0.0.1', '::1'}, 'Local instances only'
    suffix = str(uuid.uuid4())
    flow_id, name = suffix, f'codex-bank-review-{suffix[:8]}'
    conversations = [str(uuid.uuid4()), str(uuid.uuid4())]
    created = False
    evidence = {'base': base, 'workspace': 'default-workspace', 'flow_id': flow_id,
                'conversation_ids': conversations, 'provider_calls': 'No Process nodes or MCP nodes in fixture',
                'checks': [], 'cleanup': []}

    def request(method, path, data=None, headers=None):
        req = Request(base + path + ('&' if '?' in path else '?') + 'workspace=default-workspace',
                      data=json.dumps(data).encode() if data is not None else None,
                      headers={'Content-Type': 'application/json', **(headers or {})}, method=method)
        try:
            with urlopen(req, timeout=60) as r:
                raw = r.read()
                return r.status, json.loads(raw) if raw else None
        except HTTPError as e:
            raw = e.read()
            return e.code, json.loads(raw) if raw and e.headers.get('Content-Type', '').startswith('application/json') else {'error': 'non-JSON error'}

    nodes = []
    for i, kind in enumerate(['start', 'static', 'finish']):
        props = {'entries': [{'kind': 'message', 'role': 'assistant',
                              'content': 'synthetic-response @conversation.id'}]} if kind == 'static' else {}
        nodes.append({'id': f'n{i}', 'type': kind, 'position': {'x': i * 200, 'y': 0},
                      'data': {'type': kind, 'label': kind, 'properties': props}})
    flow = {'id': flow_id, 'name': name, 'nodes': nodes,
            'edges': [{'id': 'e0', 'source': 'n0', 'target': 'n1'}, {'id': 'e1', 'source': 'n1', 'target': 'n2'}]}
    try:
        status, data = request('POST', '/api/flow', flow)
        assert status == 201, (status, data)
        created = True

        def run(slot):
            cid = conversations[slot]
            status, data = request('POST', '/v1/chat/completions', {
                'model': f'flow-{name}', 'messages': [{'role': 'user', 'content': f'synthetic-customer-{slot}'}],
                'metadata': {'flujo': 'true', 'conversationId': cid, 'customerId': f'synthetic-{slot}'},
            }, {'Authorization': f'Bearer synthetic-caller-{slot}'})
            assert status == 200, (status, data)
            assert data['conversation_id'] == cid
            text = data['choices'][0]['message']['content']
            assert text == 'synthetic-response @conversation.id', text
            return {'check': 'interleaved-static-run', 'slot': slot, 'status': status,
                    'conversation_id_matches': True, 'static_at_reference_expanded': False}

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            evidence['checks'].extend(pool.map(run, range(2)))
        # These are deliberately bogus claimed identities, not real customer credentials.
        status, data = request('GET', f'/v1/chat/conversations/{conversations[1]}',
                               headers={'Authorization': 'Bearer synthetic-caller-0', 'X-Customer-Id': 'synthetic-0'})
        assert status == 200
        assert any(m.get('content') == 'synthetic-customer-1' for m in data['messages'])
        evidence['checks'].append({'check': 'B-history-readable-with-A-claimed-identity', 'status': status,
                                   'observation': 'Generic local API has no verified customer identity or owner binding.'})
        status, _ = request('GET', f'/v1/chat/conversations/{conversations[1]}')
        assert status == 200
        evidence['checks'].append({'check': 'synthetic-history-readable-without-bearer', 'status': status})
        evidence['limits'] = 'Local single-user posture and two static runs only; not banking isolation, live MCP propagation, SSE routing or 500-user performance proof.'
    finally:
        if created:
            for cid in conversations:
                status, _ = request('DELETE', f'/v1/chat/conversations/{cid}')
                evidence['cleanup'].append({'kind': 'conversation', 'id': cid, 'status': status})
                assert status in (200, 204, 404), (cid, status)
                status, _ = request('GET', f'/v1/chat/conversations/{cid}')
                assert status == 404, (cid, status)
            status, _ = request('DELETE', f'/api/flow/{flow_id}')
            evidence['cleanup'].append({'kind': 'flow', 'id': flow_id, 'status': status})
            assert status == 204, status
            status, _ = request('GET', f'/api/flow/{flow_id}')
            assert status == 404, status
            evidence['cleanup_verified_absent'] = True
        evidence['observed_at_unix'] = int(time.time())
        print(json.dumps(evidence, indent=2))


if __name__ == '__main__':
    main()
