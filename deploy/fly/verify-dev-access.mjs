import https from 'node:https';
import os from 'node:os';
import path from 'node:path';
import { readPrivateJson, writePrivateJson } from '../../../flujo-cloud/lib/private-files.mjs';

const directory = path.join(os.homedir(), '.flujo-fly', 'flujo-factored-2026');
const access = await readPrivateJson(path.join(directory, 'development-access.json'));
const mainAccess = await readPrivateJson(path.join(directory, 'access.json'));
const secrets = await readPrivateJson(path.join(directory, 'fly-secrets.json'));
const credentialValues = Object.entries(secrets).filter(([name]) => name !== 'FLUJO_WORKER_SNAPSHOT_SHA256')
  .map(([, value]) => value).concat(access.accounts.map(value => value.password));
const main = 'https://flujo-factored-2026.fly.dev';
if (access.url !== 'https://flujo-factored-dev-2026.fly.dev') throw new Error('Expected the separate development hostname.');
const receipt = { version: 2, url: access.url, mainUrl: main, ipv4: true, checkedAt: new Date().toISOString(), checks: {} };
const sessions = [];

function request(base, pathname, { method = 'GET', headers = {}, body } = {}) {
  return new Promise((resolve, reject) => {
    const outgoing = https.request(new URL(pathname, base), { method, headers, family: 4, timeout: 25_000 }, incoming => {
      const chunks = []; let size = 0;
      incoming.on('data', chunk => { size += chunk.length; if (size > 8 * 1024 * 1024) outgoing.destroy(new Error('Unexpected large verification response.')); else chunks.push(chunk); });
      incoming.once('end', () => resolve({ status: incoming.statusCode, headers: incoming.headers, text: Buffer.concat(chunks).toString('utf8') }));
      incoming.once('error', reject);
    });
    outgoing.once('timeout', () => outgoing.destroy(new Error('Verification request timed out.')));
    outgoing.once('error', reject);
    outgoing.end(body);
  });
}
function check(name, condition) { receipt.checks[name] = Boolean(condition); if (!condition) throw new Error(`Development check failed: ${name}`); }
function sessionCookie(response) { return response.headers['set-cookie']?.[0]?.split(';', 1)[0]; }
const formHeaders = origin => ({ origin, 'content-type': 'application/x-www-form-urlencoded' });
try {
  check('anonymousWorkerDenied', (await request(access.url, '/api/worker/status')).status === 401);
  const loginPage = await request(access.url, '/_dev/login');
  check('loginPageReady', loginPage.status === 200 && loginPage.text.includes('Live Fly development'));
  check('nativeFormOriginPreserved', loginPage.headers['referrer-policy'] === 'same-origin');
  check('loginPageContainsNoCredentials', !credentialValues.some(value => loginPage.text.includes(value)));
  check('anonymousTracesDenied', (await request(access.url, '/v1/chat/conversations')).status === 401);
  for (const origin of [undefined, 'null', main, 'https://untrusted.invalid']) {
    const headers = formHeaders(origin); if (!origin) delete headers.origin;
    check(`loginRejectsOrigin_${origin || 'missing'}`, (await request(access.url, '/_dev/login', { method: 'POST', headers, body: 'username=mario&password=invalid' })).status === 403);
  }
  for (const account of access.accounts) {
    const response = await request(access.url, '/_dev/login', { method: 'POST', headers: formHeaders(access.url),
      body: new URLSearchParams({ username: account.username, password: account.password }).toString() });
    const cookie = sessionCookie(response);
    check(`${account.username}Login`, response.status === 303 && cookie?.startsWith('__Host-flujo-live-dev-session='));
    sessions.push({ base: access.url, cookie, developer: account.username });
    check(`${account.username}SecureSession`, ['Secure', 'HttpOnly', 'SameSite=Strict', 'Path=/'].every(value => response.headers['set-cookie'][0].includes(value)));
    for (const endpoint of ['/api/workspaces', '/api/flow', '/api/model', '/api/worker/status']) {
      const inventory = await request(access.url, endpoint, { headers: { cookie } });
      check(`${account.username}_${endpoint}_ready`, inventory.status === 200);
      check(`${account.username}_${endpoint}_noGateCredentials`, !credentialValues.some(value => inventory.text.includes(value)));
      if (endpoint === '/api/worker/status') {
        const status = JSON.parse(inventory.text);
        check(`${account.username}_workerReady`, status.mode === 'worker' && status.state === 'ready');
        check(`${account.username}_allMcpReady`, status.servers?.length === 8 && status.servers.every(value => value.status === 'ready'));
      }
    }
    const inventory = await request(access.url, '/v1/chat/conversations?workspace=default-workspace', { headers: { cookie } });
    const conversations = JSON.parse(inventory.text);
    check(`${account.username}_storedConversationInventory`, inventory.status === 200 && Array.isArray(conversations) && conversations.length >= 4);
    const paged = await request(access.url, '/v1/chat/conversations?workspace=default-workspace&paged=1&limit=50', { headers: { cookie } });
    check(`${account.username}_pagedConversationInventory`, paged.status === 200 && JSON.parse(paged.text).items?.length >= 4);
    let messageCount = 0, toolTraceCount = 0, archivedInputCount = 0;
    for (const [index, conversation] of conversations.entries()) {
      const encodedId = encodeURIComponent(conversation.id);
      const detail = await request(access.url, `/v1/chat/conversations/${encodedId}?workspace=default-workspace`, { headers: { cookie } });
      const data = JSON.parse(detail.text);
      check(`${account.username}_conversation_${index}_detail`, detail.status === 200 && data.id === conversation.id && Array.isArray(data.messages));
      check(`${account.username}_conversation_${index}_noCredentials`, !credentialValues.some(value => detail.text.includes(value)));
      messageCount += data.messages.length;
      toolTraceCount += data.messages.reduce((count, message) => count + (Array.isArray(message.tool_calls) ? message.tool_calls.length : 0)
        + (['tool', 'function'].includes(message.role) ? 1 : 0), 0);
      const debug = await request(access.url, `/v1/chat/conversations/${encodedId}/debug/state?workspace=default-workspace`, { headers: { cookie } });
      check(`${account.username}_conversation_${index}_debug`, debug.status === 200 && Object.hasOwn(JSON.parse(debug.text), 'debugState'));
      check(`${account.username}_conversation_${index}_debugNoCredentials`, !credentialValues.some(value => debug.text.includes(value)));
      const turnResponse = await request(access.url, `/v1/chat/conversations/${encodedId}/model-turns?workspace=default-workspace`, { headers: { cookie } });
      const turnData = JSON.parse(turnResponse.text);
      check(`${account.username}_conversation_${index}_modelTurnIndex`, turnResponse.status === 200 && Array.isArray(turnData.turns)
        && !credentialValues.some(value => turnResponse.text.includes(value)));
      for (const turn of turnData.turns.slice(0, 10)) {
        const archived = await request(access.url, `/v1/chat/conversations/${encodedId}/model-turns/${encodeURIComponent(turn.id)}?workspace=default-workspace`, { headers: { cookie } });
        check(`${account.username}_conversation_${index}_archiveStatus`, [200, 404].includes(archived.status));
        if (archived.status === 200) {
          check(`${account.username}_conversation_${index}_archivedModelInput`, JSON.parse(archived.text).entry?.id === turn.id
            && !credentialValues.some(value => archived.text.includes(value)));
          archivedInputCount++; break;
        }
      }
    }
    check(`${account.username}_persistedMessagesPresent`, messageCount > 0);
    check(`${account.username}_persistedToolTracesPresent`, toolTraceCount > 0);
    check(`${account.username}_archivedModelInputPresent`, archivedInputCount > 0);
    for (const authorization of ['Bearer invalid-development-test-token', 'Basic invalid', '']) {
      check(`${account.username}_traceAuthorization_${authorization || 'empty'}`, (await request(access.url, '/v1/chat/conversations', { headers: { cookie, authorization } })).status === 401);
    }
    check(`${account.username}_explicitBadAuthorizationDenied`, (await request(access.url, '/api/worker/status', { headers: { cookie, authorization: 'Bearer invalid-development-test-token' } })).status === 401);
    check(`${account.username}_mutationMissingOriginDenied`, (await request(access.url, '/api/flow', { method: 'POST', headers: { cookie, 'content-type': 'application/json' }, body: '{}' })).status === 403);
    check(`${account.username}_mutationMainOriginDenied`, (await request(access.url, '/api/flow', { method: 'POST', headers: { cookie, origin: main, 'content-type': 'application/json' }, body: '{}' })).status === 403);
    const editor = await request(access.url, '/', { headers: { cookie } });
    check(`${account.username}_developmentEditorReady`, editor.status === 200 && editor.headers['x-flujo-dev-target'] === 'Live Fly development');
    check(`${account.username}_mainOriginCannotReadTraces`, (await request(access.url, '/v1/chat/conversations', { headers: { cookie, origin: main } })).status === 403);
    check(`${account.username}_devCookieCannotEnterMain`, (await request(main, '/', { headers: { cookie, accept: 'text/html' } })).status === 303);
  }
  const mainLogin = await request(main, '/_fly/login', { method: 'POST', headers: formHeaders(main),
    body: new URLSearchParams({ username: mainAccess.username, password: mainAccess.password }).toString() });
  const mainCookie = sessionCookie(mainLogin);
  check('mainLoginStillReady', mainLogin.status === 303 && Boolean(mainCookie));
  sessions.push({ base: main, cookie: mainCookie });
  for (const session of sessions.filter(value => value.developer)) {
    const savia = await request(main, '/', { headers: { cookie: `${mainCookie}; ${session.cookie}` } });
    check(`mainAlwaysSaviaWith_${session.developer}_Cookie`, savia.status === 200 && /<title>Savia/i.test(savia.text) && !savia.headers['x-flujo-dev-target']);
  }
  check('mainCookieCannotEnterDevelopment', (await request(access.url, '/_dev/status', { headers: { cookie: mainCookie } })).status === 401);
  check('mainWorkerRoutesStayClosed', (await request(main, '/api/worker/status', { headers: { cookie: mainCookie } })).status === 404);
  check('devOriginCannotEnterMain', (await request(main, '/', { headers: { cookie: mainCookie, origin: access.url } })).status === 403);
  check('mainHealthReady', (await request(main, '/_fly/health')).status === 200);
} finally {
  for (const session of sessions) {
    const response = await request(session.base, session.developer ? '/_dev/logout' : '/_fly/logout',
      { method: 'POST', headers: { cookie: session.cookie, origin: session.base } });
    receipt.checks[`${session.developer || 'main'}Logout`] = response.status === 303;
    if (session.developer) receipt.checks[`${session.developer}LogoutRevokesReplay`] =
      (await request(session.base, '/api/worker/status', { headers: { cookie: session.cookie } })).status === 401;
  }
  receipt.ready = Object.values(receipt.checks).every(Boolean);
  await writePrivateJson(path.join(directory, 'verification-development-access.json'), receipt);
  console.log(JSON.stringify(receipt));
}
if (!receipt.ready) process.exitCode = 1;
