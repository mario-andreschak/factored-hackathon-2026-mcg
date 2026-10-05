import assert from 'node:assert/strict';
import http from 'node:http';
import { createRequire } from 'node:module';
import test from 'node:test';
import { createGateway, readConfig } from './public-gateway.mjs';

const require = createRequire(new URL('../../frontend/package.json', import.meta.url));
const { chromium } = require('@playwright/test');

test('a real browser form preserves same-origin Origin and follows its secure visitor cookie into Savia', async () => {
  const origin = 'https://savia-fictional.example';
  const app = http.createServer((_req, res) => res.end('<!doctype html><h1>Authenticated Savia</h1>'));
  await new Promise(resolve => app.listen(0, '127.0.0.1', resolve));
  const gateway = createGateway(readConfig({ RC_PUBLIC_ORIGIN: origin, RC_DEMO_CODE: 'SAVIA-2026',
    RC_COOKIE_SECRET: 'c'.repeat(48) }), { appPort: app.address().port });
  await new Promise(resolve => gateway.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    const channel = process.env.RC_BROWSER_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
    browser = await chromium.launch({ headless: true, ...(channel ? { channel } : {}) });
    const page = await browser.newPage();
    const submissions = [];
    await page.route(origin + '/**', async route => {
      const request = route.request();
      const headers = await request.allHeaders();
      if (request.method() === 'POST') submissions.push(headers.origin);
      const response = await new Promise((resolve, reject) => {
        const upstream = http.request({ hostname: '127.0.0.1', port: gateway.address().port,
          path: new URL(request.url()).pathname, method: request.method(),
          headers: { ...headers, host: new URL(origin).host } }, incoming => {
          const chunks = []; incoming.on('data', chunk => chunks.push(chunk));
          incoming.on('end', () => resolve({ status: incoming.statusCode,
            headers: Object.fromEntries(Object.entries(incoming.headers).filter(([key]) => !['transfer-encoding', 'connection'].includes(key))
              .map(([key, value]) => [key, Array.isArray(value) ? value.join('\n') : String(value)])), body: Buffer.concat(chunks) }));
        });
        upstream.on('error', reject); upstream.end(request.postDataBuffer());
      });
      await route.fulfill(response);
    });
    await page.goto(origin);
    await page.getByLabel('Demo code').fill('SAVIA-2026');
    await page.getByRole('button', { name: 'Enter demo' }).click();
    await page.getByRole('heading', { name: 'Authenticated Savia' }).waitFor();
    assert.deepEqual(submissions, [origin]);
    const cookies = await page.context().cookies();
    const visitor = cookies.find(cookie => cookie.name === '__Host-rc-visitor');
    assert.ok(visitor?.secure && visitor.httpOnly && visitor.sameSite === 'Strict');
  } finally {
    await browser?.close();
    await new Promise(resolve => gateway.close(resolve));
    await new Promise(resolve => app.close(resolve));
  }
});
