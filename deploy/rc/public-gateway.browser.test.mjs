import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import http from 'node:http';
import https from 'node:https';
import { createRequire } from 'node:module';
import test from 'node:test';
import { createGateway, readConfig } from './public-gateway.mjs';

const require = createRequire(new URL('../../frontend/package.json', import.meta.url));
const { chromium } = require('@playwright/test');

// Public test-only key/certificate. They serve only the isolated loopback fixture.
const tls = {
  key: readFileSync(new URL('./fixtures/loopback-test.key', import.meta.url)),
  cert: readFileSync(new URL('./fixtures/loopback-test.crt', import.meta.url)),
};

test('a real browser form preserves same-origin Origin and follows its secure visitor cookie into Savia', async () => {
  const forwarded = [];
  const app = http.createServer((req, res) => {
    forwarded.push({ path: req.url, host: req.headers.host, cookie: req.headers.cookie });
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end('<!doctype html><h1>Authenticated Savia</h1>');
  });
  await new Promise(resolve => app.listen(0, '127.0.0.1', resolve));
  // A route.fulfill(303) redirect bypasses interception in Chromium. Use real
  // HTTPS so the redirect and browser-managed Secure cookie traverse the gateway.
  const publicServer = https.createServer(tls);
  await new Promise(resolve => publicServer.listen(0, '127.0.0.1', resolve));
  const origin = 'https://127.0.0.1:' + publicServer.address().port;
  const gateway = createGateway(readConfig({ RC_PUBLIC_ORIGIN: origin, RC_DEMO_CODE: 'SAVIA-2026',
    RC_COOKIE_SECRET: 'c'.repeat(48) }), { appPort: app.address().port });
  const visits = [];
  publicServer.on('request', (req, res) => {
    visits.push({ method: req.method, path: req.url, origin: req.headers.origin,
      visitor: /(?:^|;\s*)__Host-rc-visitor=/.test(req.headers.cookie || '') });
    gateway.emit('request', req, res);
  });
  let browser;
  try {
    const channel = process.env.RC_BROWSER_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
    browser = await chromium.launch({ headless: true, ...(channel ? { channel } : {}) });
    // The certificate is deliberately self-signed; no HTTPS interception or
    // cookie injection is used. Browser cookie and same-origin rules stay active.
    const page = await browser.newPage({ ignoreHTTPSErrors: true });
    await page.goto(origin);
    await page.getByLabel('Demo code').fill('SAVIA-2026');
    await page.getByRole('button', { name: 'Enter demo' }).click();
    await page.getByRole('heading', { name: 'Authenticated Savia' }).waitFor();
    assert.equal(page.url(), origin + '/');
    assert.deepEqual(visits.filter(visit => visit.method === 'POST').map(visit => visit.origin), [origin]);
    assert.deepEqual(visits.filter(visit => visit.method === 'GET' && visit.path === '/')
      .map(visit => visit.visitor), [false, true]);
    assert.deepEqual(forwarded.filter(request => request.path === '/'), [
      { path: '/', host: new URL(origin).host, cookie: undefined },
    ]);
    const cookies = await page.context().cookies();
    const visitor = cookies.find(cookie => cookie.name === '__Host-rc-visitor');
    assert.ok(visitor?.secure && visitor.httpOnly && visitor.sameSite === 'Strict');
  } finally {
    await browser?.close();
    await new Promise(resolve => {
      publicServer.close(resolve);
      publicServer.closeAllConnections();
    });
    await new Promise(resolve => app.close(resolve));
  }
});
