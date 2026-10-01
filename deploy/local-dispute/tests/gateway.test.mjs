import assert from 'node:assert/strict';
import http from 'node:http';
import { once } from 'node:events';
import test from 'node:test';
import { createGateway, localOrigin } from '../runtime.mjs';

test('the local origin cannot become a public, credential-bearing or alternative host', () => {
  for (const origin of ['http://example.com:43900', 'https://127.0.0.1:43900',
    'http://localhost:43900', 'http://127.0.0.1:43900/path', 'http://a:b@127.0.0.1:43900',
    'http://127.0.0.1:43901', 'http://127.0.0.1:43900?x=1'])
    assert.throws(() => localOrigin(origin));
});

test('gateway refuses foreign hosts and origins and strips spoofed forwarding authority', async () => {
  const observed = [];
  const upstream = http.createServer((request, response) => {
    observed.push(request.headers); response.writeHead(200); response.end('owned application');
  });
  upstream.listen(0, '127.0.0.1'); await once(upstream, 'listening');
  const gateway = createGateway('http://127.0.0.1:43900', upstream.address().port);
  gateway.listen(0, '127.0.0.1'); await once(gateway, 'listening');
  const request = headers => new Promise((resolve, reject) => {
    const outgoing = http.request({ host: '127.0.0.1', port: gateway.address().port,
      path: '/api/auth/login', method: 'POST', headers }, incoming => {
      incoming.resume(); incoming.on('end', () => resolve(incoming.statusCode));
    }); outgoing.on('error', reject); outgoing.end();
  });
  try {
    assert.equal(await request({ host: 'evil.example' }), 421);
    assert.equal(await request({ host: '127.0.0.1:43900', origin: 'https://evil.example' }), 403);
    assert.equal(observed.length, 0);
    assert.equal(await request({ host: '127.0.0.1:43900', origin: 'http://127.0.0.1:43900',
      forwarded: 'host=evil.example', 'x-forwarded-host': 'evil.example', 'x-forwarded-proto': 'https',
      cookie: 'owned-session=retained' }), 200);
    assert.equal(observed.length, 1);
    assert.equal(observed[0].origin, 'http://127.0.0.1:43900');
    assert.equal(observed[0].cookie, 'owned-session=retained');
    for (const name of ['forwarded', 'x-forwarded-host', 'x-forwarded-proto', 'x-forwarded-for'])
      assert.equal(observed[0][name], undefined);
  } finally { gateway.close(); upstream.close(); }
});
