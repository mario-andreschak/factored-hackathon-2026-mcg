import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { once } from 'node:events';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { createGateway, readConfig } from './public-gateway.mjs';

test('public portal serves manifest-only files before the demo gate and preserves auth boundaries', async t => {
  const directory = mkdtempSync(path.join(tmpdir(), 'savia-public-portal-'));
  const bytes = '<!doctype html><title>Savia submission</title>';
  writeFileSync(path.join(directory, 'index.html'), bytes);
  writeFileSync(path.join(directory, 'private.env'), 'never public');
  writeFileSync(path.join(directory, 'portal-manifest.json'), JSON.stringify({schema:'savia-public-portal/v1',
    files:{'index.html':createHash('sha256').update(bytes).digest('hex'), '../private.env':'a'.repeat(64)}}));
  const server = createGateway(readConfig({RC_PUBLIC_ORIGIN:'https://savia.example', RC_DEMO_CODE:'SAVIA-2026',
    RC_COOKIE_SECRET:'a-long-test-only-cookie-signing-secret'}), {portalDirectory:directory});
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  t.after(() => {server.closeAllConnections(); server.close(); rmSync(directory, {recursive:true,force:true});});
  const request = (url, method='GET', host='savia.example') => new Promise((resolve,reject) => {
    const req=http.request({host:'127.0.0.1', port:server.address().port, path:url, method, headers:{Host:host}}, res=> {
      const parts=[];res.on('data', x=>parts.push(x));res.on('end',()=>resolve({status:res.statusCode, headers:res.headers,body:Buffer.concat(parts).toString()}));
    });req.on('error',reject);req.end();
  });
  const landing=await request('/submission/'); assert.equal(landing.status,200);assert.equal(landing.body,bytes);
  assert.equal(landing.headers['set-cookie'],undefined);assert.match(landing.headers['content-security-policy'],/frame-ancestors 'none'/);
  assert.equal((await request('/submission')).headers.location,'/submission/');
  assert.equal((await request('/submission/','HEAD')).body,'');
  assert.equal((await request('/submission/','POST')).status,405);
  assert.equal((await request('/submission/private.env')).status,404);
  assert.equal((await request('/submission/%2e%2e%2fprivate.env')).status,404);
  assert.equal((await request('/submission/','GET','evil.example')).status,421);
  assert.equal((await request('/api/bank')).status,401);
  writeFileSync(path.join(directory,'index.html'),'modified');
  assert.equal((await request('/submission/')).status,503);
});
