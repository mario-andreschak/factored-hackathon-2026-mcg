import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { writePrivateJson } from '../../../flujo-cloud/lib/private-files.mjs';

const privateDirectory = path.join(process.env.USERPROFILE, '.flujo-fly', 'flujo-factored-2026');
const access = JSON.parse(await fs.readFile(path.join(privateDirectory, 'access.json'), 'utf8'));
const origin = access.url;
const GATEWAY_COOKIE = '__Host-savia-fly-session';
const BANKING_COOKIE = 'flujo_bank_session';
const cookies = new Map();
const report = {};
const chatRequested = process.argv.includes('--chat');
const bankReadRequested = process.argv.includes('--bank-read');
const bankListRequested = process.argv.includes('--bank-list');
const waitForLedger = process.argv.includes('--wait-ledger');
const sessionReceiptFile = path.join(privateDirectory, 'verification-session.json');
const sessionReceipt = { version: 1, runId: randomUUID(), startedAt: new Date().toISOString() };
let phase = 'readiness';
let initialConfirmed = 0;
let bankSessionCreated = false;
let chatPostAttempted = false;
const publicErrorCodes = new Set(['chat_busy', 'chat_authorization_failed', 'chat_upstream_failed',
  'chat_timeout', 'chat_unreachable', 'chat_invalid_response', 'chat_invalid_state',
  'chat_invalid_configuration', 'session_expired', 'session_mismatch', 'revoke_session_expired',
  'revoke_configuration_unavailable', 'revoke_interrupted', 'revoke_internal_error', 'chat_revocation_failed']);
const fixedPublicDetails = new Map([
  ['La conexión segura del asistente no está disponible.', 'chat_authorization_failed'],
  ['FLUJO no pudo completar esta consulta. Puedes volver a intentarlo.', 'chat_upstream_failed'],
  ['El asistente está ocupado. Inténtalo en un momento.', 'chat_busy'],
  ['No se pudo verificar la respuesta de FLUJO.', 'chat_invalid_response'],
  ['La sesión del asistente no está disponible.', 'session_mismatch'],
  ['Tu sesión expiró. Vuelve a ingresar.', 'session_expired'],
  ['No se pudo confirmar el cierre completo de la sesión.', 'logout_persist_failed'],
  ['Se requiere una solicitud JSON.', 'json_required'],
  ['Origen de solicitud no permitido.', 'origin_denied'],
  ['FLUJO no pudo responder. Intenta nuevamente.', 'frontend_chat_failed'],
]);

async function privateReceipt() {
  // Private correlation evidence for an independent SQLite audit; no token,
  // customer identity or response text is stored here.
  await writePrivateJson(sessionReceiptFile, sessionReceipt);
}

function rememberCookies(response) {
  const values = response.headers.getSetCookie();
  for (const raw of values) {
    const pair = raw.split(';')[0];
    const separator = pair.indexOf('=');
    if (separator < 1) continue;
    const name = pair.slice(0, separator);
    if (name === GATEWAY_COOKIE || name === BANKING_COOKIE) cookies.set(name, pair.slice(separator + 1));
  }
  return values;
}

function assertPrivateCookie(values, name) {
  const matches = values.filter(value => value.startsWith(`${name}=`));
  assert.equal(matches.length, 1, `Expected exactly one ${name} cookie`);
  const attributes = new Map(matches[0].split(';').slice(1).map(value => {
    const [key, ...parts] = value.trim().split('=');
    return [key.toLowerCase(), parts.join('=')];
  }));
  assert(attributes.has('secure'), `${name} cookie must be Secure`);
  assert(attributes.has('httponly'), `${name} cookie must be HttpOnly`);
  assert.equal(attributes.get('samesite')?.toLowerCase(), 'strict', `${name} cookie must use SameSite=Strict`);
  assert.equal(attributes.get('path'), '/', `${name} cookie must use Path=/`);
  assert.equal(attributes.has('domain'), false, `${name} cookie must be host-only`);
}

async function request(route, { method = 'GET', body, form, anonymous = false, foreign = false } = {}) {
  // Authenticated probes exercise the browser's cookie path without Basic.
  const headers = {};
  if (!anonymous && cookies.size) headers.Cookie = [...cookies].map(([key, value]) => `${key}=${value}`).join('; ');
  if (!anonymous || method !== 'GET') headers.Origin = foreign ? 'https://foreign.invalid' : origin;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (form !== undefined) headers['Content-Type'] = 'application/x-www-form-urlencoded';
  const response = await fetch(`${origin}${route}`, { method, headers, redirect: 'manual',
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    ...(form === undefined ? {} : { body: new URLSearchParams(form).toString() }),
    signal: AbortSignal.timeout(480_000) });
  const content = await response.text();
  let json; try { json = JSON.parse(content); } catch {}
  return { response, json, content };
}

async function diagnosedRequest(key, route, options) {
  try {
    const result = await request(route, options);
    const status = result.response.status;
    const diagnostics = { httpStatus: status };
    if (status >= 400) {
      const candidates = [result.json?.code, result.json?.error?.code,
        typeof result.json?.error === 'string' ? result.json.error : undefined];
      const code = candidates.find(value => typeof value === 'string' && publicErrorCodes.has(value));
      diagnostics.errorCode = code ?? fixedPublicDetails.get(result.json?.detail) ?? 'unrecognized_public_error';
    }
    report[key] = diagnostics;
    return result;
  } catch (error) {
    report[key] = { errorCode: ['TimeoutError', 'AbortError'].includes(error?.name)
      ? 'request_timeout' : error?.name === 'TypeError' ? 'network_failure' : 'request_failed' };
    throw error;
  }
}

async function verify() {
  assert(!bankReadRequested || chatRequested, '--bank-read requires --chat');
  assert(!bankListRequested || (bankReadRequested && chatRequested), '--bank-list requires --bank-read and --chat');
  const health = await request('/_fly/health', { anonymous: true });
  assert.equal(health.response.status, 200, 'Live worker and dataset readiness failed');
  assert.equal(health.content.trim(), 'ready');
  report.health = 'ready';

  phase = 'gateway access boundary';
  assert.equal((await request('/api/overview', { anonymous: true })).response.status, 401);
  assert.equal((await request('/v1/models', { anonymous: true })).response.status, 404);
  assert.equal((await request('/mcp', { anonymous: true })).response.status, 404);
  const gatewayPage = await request('/_fly/login', { anonymous: true });
  assert.equal(gatewayPage.response.status, 200);
  assert(gatewayPage.content.includes('Sign in to Savia'), 'Expected the outer sign-in page');
  const gatewayLogin = await request('/_fly/login', { method: 'POST', anonymous: true,
    form: { username: access.username, password: access.password } });
  const gatewayCookies = rememberCookies(gatewayLogin.response);
  assert.equal(gatewayLogin.response.status, 303, 'Gateway browser login failed');
  assertPrivateCookie(gatewayCookies, GATEWAY_COOKIE);
  assert.equal((await request('/')).response.status, 200, 'Cookie-only gateway authentication failed');
  assert.equal((await request('/api/overview')).response.status, 401, 'Banking session must still be required');
  assert.equal((await request('/api/overview', { foreign: true })).response.status, 403,
    'Gateway cookie must reject foreign origins');
  assert.equal((await request('/api/auth/login', { method: 'POST', foreign: true,
    body: { profile: 'colombia', code: access.demo_code } })).response.status, 403);
  report.accessBoundary = 'anonymous data denied; cookie-only gateway login and foreign-origin rejection passed';

  const frontendHealth = await request('/healthz');
  assert.equal(frontendHealth.response.status, 200);
  assert.equal(frontendHealth.json?.dataset_ready, true);
  assert.equal(frontendHealth.json?.chat_revocations?.configured, true);
  assert.equal(frontendHealth.json.chat_revocations.pending, 0, 'Earlier revocations must settle before verification');
  assert.equal(frontendHealth.json.chat_revocations.retrying, 0);
  initialConfirmed = frontendHealth.json.chat_revocations.confirmed;
  assert(Number.isInteger(initialConfirmed) && initialConfirmed >= 0);
  sessionReceipt.initialConfirmedRevocations = initialConfirmed;

  // Cover login and every subsequent assertion with cleanup. Capture the bank
  // cookie before checking status/flags so a malformed success is still revoked.
  try {
    phase = 'banking login';
    const login = await request('/api/auth/login', { method: 'POST', body: { profile: 'colombia', code: access.demo_code } });
    const values = rememberCookies(login.response);
    bankSessionCreated = Boolean(cookies.get(BANKING_COOKIE));
    if (bankSessionCreated) {
      sessionReceipt.bankSessionTokenHash = createHash('sha256').update(cookies.get(BANKING_COOKIE)).digest('hex');
      sessionReceipt.loggedInAt = new Date().toISOString();
      sessionReceipt.phase = 'authenticated';
      await privateReceipt();
    }
    assert.equal(login.response.status, 200, 'Banking login failed');
    assert.equal(login.json?.authenticated, true);
    assertPrivateCookie(values, BANKING_COOKIE);

    phase = 'frontend and fresh history';
    const overview = await request('/api/overview');
    assert.equal(overview.response.status, 200, 'Authenticated banking overview failed');
    const selectedMovement = bankReadRequested && Array.isArray(overview.json?.transactions)
      ? overview.json.transactions.find(value => typeof value?.reference === 'string'
        && /^txn_[a-f0-9]{24}$/.test(value.reference)) : undefined;
    if (bankReadRequested) assert(selectedMovement, 'No owned movement is available for the read-only inquiry');
    const history = await request('/api/chat/history');
    assert.equal(history.response.status, 200);
    assert.equal(history.json?.messages?.length, 0, 'New browser session must have no copied chat history');
    const chatStatus = await request('/api/chat/status');
    assert.equal(chatStatus.response.status, 200);
    assert.equal(chatStatus.json?.available, true, 'Authenticated FLUJO chat is not configured');
    report.frontend = 'banking login, exact Secure cookie, authenticated overview and fresh history passed';

    if (chatRequested && waitForLedger) {
      phase = 'private ledger binding';
      sessionReceipt.phase = 'awaiting-ledger';
      await privateReceipt();
      const deadline = Date.now() + 90_000;
      let bound = false;
      while (Date.now() < deadline) {
        try {
          const binding = JSON.parse(await fs.readFile(path.join(privateDirectory, 'verification-ledger-bound.json'), 'utf8'));
          if (binding?.runId === sessionReceipt.runId) { bound = true; break; }
        } catch (error) {
          // The auditor may not have published yet, or may be mid-write.
          if (error.code !== 'ENOENT' && !(error instanceof SyntaxError)) throw error;
        }
        await new Promise(resolve => setTimeout(resolve, 500));
      }
      assert.equal(bound, true, 'Timed out waiting for the matching private ledger binding');
      sessionReceipt.ledgerBoundAt = new Date().toISOString();
      await privateReceipt();
      report.ledgerAuditGate = 'matching private audit binding received';
    }

    if (chatRequested) {
      phase = 'read-only provider round trip';
      sessionReceipt.phase = 'chat-admitted';
      sessionReceipt.chatStartedAt = new Date().toISOString();
      await privateReceipt();
      const started = Date.now();
      chatPostAttempted = true;
      const chatBody = bankReadRequested ? {
        transaction_reference: selectedMovement.reference,
        message: bankListRequested
          ? 'Ejecuta la herramienta bancaria de solo lectura list_my_transactions para consultar la primera página de mis movimientos. Con el resultado de esa herramienta, indica cuántos movimientos devuelve y si hay más páginas. No realices acciones ni cambios ni abras casos.'
          : 'Consulta el movimiento seleccionado mediante el MCP bancario y resume su fecha, importe, moneda, comercio y estado. Esta consulta es estrictamente de solo lectura: no realices acciones ni cambios, no abras casos y no solicites operaciones.'
      } : {
        message: 'Consulta de verificación de solo lectura: resume brevemente qué consultas puedes atender para mi perfil mediante el MCP bancario. No realices acciones ni cambios.'
      };
      const chat = await diagnosedRequest('chatAttempt', '/api/chat', { method: 'POST', body: chatBody });
      assert.equal(chat.response.status, 200, `Provider round trip failed with HTTP ${chat.response.status}`);
      assert.equal(chat.json?.mode, 'flujo');
      assert.equal(typeof chat.json?.reply, 'string');
      assert(chat.json.reply.trim().length > 0, 'Empty provider reply');
      const updated = await request('/api/chat/history');
      assert.equal(updated.response.status, 200);
      assert.equal(updated.json?.messages?.length, 2, 'Expected exactly this test exchange');
      assert.equal(updated.json.messages[0]?.role, 'user');
      assert.equal(updated.json.messages[1]?.role, 'assistant');
      assert.equal(updated.json.messages[1]?.text, chat.json.reply, 'Persisted reply differs from this response');
      // Only whitelisted booleans/timing reach stdout, never customer text.
      report.chat = { readOnlyProviderRoundTrip: true, elapsedMs: Date.now() - started, persistedExchange: true };
      if (bankReadRequested) report.selectedMovementInquiry = true;
      if (bankListRequested) report.bankListInquiry = true;
      sessionReceipt.chatCompletedAt = new Date().toISOString();
      await privateReceipt();
    }
  } catch (error) {
    report.failedCheck = phase;
    throw error;
  } finally {
    if (bankSessionCreated) {
      try {
        phase = 'banking logout and revocation';
        const logout = await diagnosedRequest('bankLogoutAttempt', '/api/auth/logout', { method: 'POST', body: {} });
        assert.equal(logout.response.status, 204, 'Session revocation/logout failed');
        // Retain the original cookie to prove server-side denial, instead of
        // trusting its browser deletion attribute as revocation evidence.
        assert.equal((await request('/api/overview')).response.status, 401, 'Logged-out session must be denied');
        assert.equal((await request('/api/chat/history')).response.status, 401, 'Logged-out history must be denied');
        sessionReceipt.loggedOutAt = new Date().toISOString();
        sessionReceipt.logoutDisposition = logout.response.headers.get('x-banking-revoke');
        sessionReceipt.phase = 'logged-out';
        await privateReceipt();
        if (chatPostAttempted) {
          let confirmed = false;
          for (let attempt = 0; attempt < 30; attempt++) {
            const diagnostics = await request('/healthz');
            const status = diagnostics.json?.chat_revocations;
            if (diagnostics.response.status === 200 && status?.confirmed === initialConfirmed + 1
                && status.pending === 0 && status.retrying === 0) {
              confirmed = true;
              sessionReceipt.finalConfirmedRevocations = status.confirmed;
              break;
            }
            await new Promise(resolve => setTimeout(resolve, 1000));
          }
          assert.equal(confirmed, true, 'Exactly one additional worker revocation must settle');
          // Aggregate evidence is labeled accurately. Root can join the private
          // token hash to the exact session while admitted for a ledger audit.
          report.workerRevocationAggregate = 'one additional confirmation; none pending or retrying';
          report.logout = 'original browser cookie and history access denied';
          sessionReceipt.phase = 'revocation-settled';
          await privateReceipt();
        } else {
          report.workerRevocationAggregate = 'not required; no chat POST attempted';
          report.logout = 'original browser cookie and history access denied';
        }
      } catch (error) {
        report.cleanupFailure = 'banking logout and revocation';
        if (!report.failedCheck) report.failedCheck = phase;
        throw error;
      }
    }
  }

  phase = 'gateway logout';
  const gatewayLogout = await request('/_fly/logout', { method: 'POST' });
  assert.equal(gatewayLogout.response.status, 303);
  rememberCookies(gatewayLogout.response);
  assert.equal((await request('/api/overview')).response.status, 401, 'Gateway logout must remove access');
  report.gatewayLogout = 'access denied';
  report.status = 'passed';
}

try {
  await verify();
  await writePrivateJson(path.join(privateDirectory, 'verification.json'), report);
  console.log(JSON.stringify(report));
} catch {
  // Avoid assertion diffs containing private response text or cookie material.
  report.status = 'failed';
  report.phase = report.failedCheck ?? phase;
  await writePrivateJson(path.join(privateDirectory, 'verification.json'), report);
  console.error(`Verification failed during ${report.phase}; the private report contains safe HTTP diagnostics.`);
  process.exitCode = 1;
}
