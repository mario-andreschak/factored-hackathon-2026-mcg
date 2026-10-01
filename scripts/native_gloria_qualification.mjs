#!/usr/bin/env node
/** Run a disposable installed FLUJO graph + native CLI + admitted MCP workflow. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createHash, randomBytes, randomUUID } from 'node:crypto';
import { execFileSync, spawnSync } from 'node:child_process';
import { build, assertBridge, REPO_ROOT } from './build_gloria_graph.mjs';

const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const docker = args => execFileSync('docker', args, { encoding: 'utf8', maxBuffer: 8 * 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'] });
const opts = Object.fromEntries(process.argv.slice(2).reduce((rows, value, index, all) => {
  if (index % 2 === 0) { assert(value.startsWith('--') && all[index + 1], 'Expected option/value pairs'); rows.push([value, all[index + 1]]); }
  return rows;
}, []));
for (const key of Object.keys(opts)) assert(['--flujo-root', '--context', '--image', '--output', '--port', '--auth-home', '--model-name', '--retain-runtime', '--serve-only'].includes(key), `Unknown option: ${key}`);
assert(opts['--flujo-root'] && opts['--context'] && opts['--output'], 'Required: --flujo-root --context --output');
const context = path.resolve(opts['--context']);
const sourceContext = JSON.parse(fs.readFileSync(path.join(context, 'source-manifest.json')));
assert.equal(sha(fs.readFileSync(path.join(context, 'catalog.json'))), sourceContext.catalog_sha256, 'context_catalog_pin_drift');
for (const [relative, checksum] of Object.entries(sourceContext.application_files)) {
  const source = path.resolve(REPO_ROOT, relative), stat = fs.lstatSync(source);
  assert(source.startsWith(REPO_ROOT + path.sep) && stat.isFile() && !stat.isSymbolicLink(), 'application_source_not_regular');
  assert.equal(sha(fs.readFileSync(source)), checksum, `application_context_source_drift:${relative}`);
}
const binary = sourceContext.native_binary;
assert(binary && ['0.153.3', '0.157.1'].includes(binary.version), 'Qualified context must pin a native binary');
const image = opts['--image'] ?? 'codex-gloria-native-qualification:0ba622-v1';
const modelName = opts['--model-name'] ?? 'gpt-6-sol';
assert(!opts['--retain-runtime'] || ['true', 'diagnostic'].includes(opts['--retain-runtime']), 'Use --retain-runtime true or diagnostic only for joined local tests');
assert(!opts['--serve-only'] || opts['--serve-only'] === 'true' && opts['--retain-runtime'] === 'diagnostic', 'Serve-only requires explicit diagnostic retention');
assert(['gpt-6-sol', 'gpt-6-luna'].includes(modelName), 'Restricted profile model required');
const port = Number(opts['--port'] ?? 43921);
assert(Number.isInteger(port) && port > 1024 && port < 65536, 'Expected private loopback port');
const runtime = path.join(REPO_ROOT, 'private', `native-gloria-run-${randomUUID()}`);
const state = path.join(runtime, 'data'), auth = path.join(runtime, 'auth'), admitted = path.join(runtime, 'admitted');
for (const directory of [state, auth, admitted, path.join(admitted, 'turns'), path.join(admitted, 'captured'), path.join(admitted, 'observed'), path.join(admitted, 'revocations')]) fs.mkdirSync(directory, { recursive: true });
const authHome = path.resolve(opts['--auth-home'] ?? process.env.CODEX_HOME ?? path.join(os.homedir(), '.codex'));
const config = fs.existsSync(path.join(authHome, 'config.toml')) ? fs.readFileSync(path.join(authHome, 'config.toml'), 'utf8') : '';
const store = /^\s*cli_auth_credentials_store\s*=\s*"([^"]+)"/m.exec(config)?.[1];
assert(!store || store === 'file', 'Active login must use file credential storage');
fs.copyFileSync(path.join(authHome, 'auth.json'), path.join(auth, 'auth.json'));
fs.writeFileSync(path.join(auth, 'config.toml'), 'cli_auth_credentials_store = "file"\n', { mode: 0o600 });
fs.copyFileSync(path.join(context, 'catalog.json'), path.join(admitted, 'model-catalog.json'));
fs.writeFileSync(path.join(admitted, 'native-profile.json'), JSON.stringify({
  verifiedCliVersion: binary.version, verifiedCliSha256: binary.sha256,
  verifiedCliPath: binary.installed_path,
  verifiedModelCatalogPath: '/qualification/runtime/model-catalog.json',
  verifiedModelCatalogSha256: sha(fs.readFileSync(path.join(admitted, 'model-catalog.json'))),
}));
fs.writeFileSync(path.join(admitted, 'admissions.json'), '[]');
const name = `codex-gloria-native-${randomBytes(4).toString('hex')}`;
const endpoint = `http://127.0.0.1:${port}`;
const admissions = [], cases = [];
const request = async (route, body, token, method = 'POST') => {
  const result = await fetch(endpoint + route, { method, headers: { 'content-type': 'application/json', ...(token ? { authorization: 'Bearer ' + token } : {}) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }), signal: AbortSignal.timeout(420000) });
  const text = await result.text();
  let data; try { data = JSON.parse(text); } catch { data = { error: 'invalid_json' }; }
  return { status: result.status, data };
};
const report = { schema: 'gloria-installed-native-qualification/v1', sourceOnly: false,
  flujoRevision: '0ba62296520a505e6d71eddf5aa650691f3dc311', image, installed: false,
  externalManifestSha256: sha(fs.readFileSync(path.join(context, 'source-manifest.json'))),
  innerStages: 'protected ephemeral native language graphs; real provider',
  bankData: 'public synthetic development fixture; bridge exposes no banking actions', model: modelName,
  nativeProfile: JSON.parse(fs.readFileSync(path.join(admitted, 'native-profile.json'))), cases,
  modelRelayAuthoritative: false, sharedWorkersChanged: false, sourceContext };
let started = false;
try {
  report.imageIdentity = JSON.parse(docker(['image', 'inspect', image, '--format', '{{json .Id}}']));
  report.imageCredentialAudit = JSON.parse(docker(['run', '--rm', '--entrypoint', '/usr/bin/python3', image, '-c',
    'import json,pathlib; paths=["/app/.env","/app/.env.local","/qualification/.env","/root/.codex/auth.json","/app/.codex/auth.json"]; print(json.dumps({"checked":len(paths),"credential_files_present":sum(pathlib.Path(p).exists() for p in paths)}))']));
  assert.equal(report.imageCredentialAudit.credential_files_present, 0, 'image_contains_credential_file');
  docker(['run', '-d', '--name', name, '--label', 'io.flujo.gloria.scope=isolated-qualification',
    '-p', `127.0.0.1:${port}:4200`, '--mount', `type=bind,source=${state},target=/runtime/data`,
    '--mount', `type=bind,source=${admitted},target=/qualification/runtime`,
    '--mount', `type=bind,source=${auth},target=/auth,readonly`, '-e', 'CODEX_HOME=/auth', image]);
  started = true;
  report.installedSourceHashes = JSON.parse(docker(['exec', name, '/usr/bin/python3', '/qualification/native_gloria_qualification.py', '--verify-image', '/qualification/source-manifest.json']));
  assert(report.installedSourceHashes.pass, 'installed_source_hash_drift');
  assert.equal(report.installedSourceHashes.manifest_sha256, sha(fs.readFileSync(path.join(context, 'source-manifest.json'))), 'installed_manifest_differs_from_context');
  assert.equal(docker(['exec', name, binary.installed_path, '--version']).trim(), 'codex-cli ' + binary.version, 'installed_native_version_drift');
  report.revocationFenceProbes = JSON.parse(docker(['exec', name, 'node', '/qualification/native_gloria_revocation_probe.mjs',
    '/app/gloria-qualification-adapter.ts', '/app']));
  assert(report.revocationFenceProbes.pass, 'installed_revocation_fences_failed');
  assert.equal(report.revocationFenceProbes.adapterSourceSha256, sourceContext.application_files['scripts/native_gloria_qualification.ts']);
  assert.equal(report.revocationFenceProbes.fixtureSha256, sourceContext.application_files['scripts/native_gloria_revocation_probe.mjs']);
  const forcedOutput = docker(['exec', name, 'node', '/qualification/native_gloria_capability_probe.mjs', binary.installed_path,
    '/qualification/runtime/model-catalog.json', '-', '/app']);
  fs.writeFileSync(path.join(runtime, 'native-forced-probes-private.jsonl'), forcedOutput);
  const forced = forcedOutput.trim().split('\n').map(line => JSON.parse(line));
  const inventory = forced.filter(item => item.tool);
  assert.equal(forced[0].sha256, binary.sha256, 'forced_probe_native_binary_drift');
  assert.equal(forced[0].catalogSha256, report.nativeProfile.verifiedModelCatalogSha256, 'forced_probe_catalog_drift');
  assert.equal(forced[0].fixtureSha256, sourceContext.application_files['scripts/native_gloria_capability_probe.mjs'], 'forced_probe_source_drift');
  assert.equal(inventory.length, 14, 'forced_probe_cases_missing');
  const expectedProbes = new Set(['gpt-6-sol', 'gpt-6-luna'].flatMap(model =>
    ['inventory', 'approved_mcp', 'read_mcp_resource', 'rogue_namespace', 'mcp__rogue__rogue_access',
      'apply_patch_foreign', 'functions_exec'].map(tool => `${model}:${tool}`)));
  const actualProbes = new Set(inventory.map(item => `${item.model}:${item.tool}`));
  assert.equal(actualProbes.size, expectedProbes.size, 'forced_probe_duplicate_cases');
  assert([...actualProbes].every(item => expectedProbes.has(item)), 'forced_probe_matrix_mismatch');
  assert(inventory.every(item => item.passed) && forced.at(-1).failures.length === 0, 'forced_native_capability_denial_failed');
  report.nativeCapabilityProbes = { scope: 'installed native binary and production tool bridge; synthetic upstream responses',
    bridgeSourceSha256: forced[0].bridgeSourceSha256, fixtureSha256: forced[0].fixtureSha256,
    cases: inventory.map(item => Object.fromEntries(['model', 'tool', 'passed', 'names', 'bridgeSafe', 'markerExists', 'foreignChanged', 'foreignLeaked', 'rogueCalled'].map(key => [key, item[key]]))) };
  for (let attempt = 0; attempt < 60; attempt++) {
    const result = await request('/api/model', undefined, undefined, 'GET').catch(() => undefined);
    if (result?.status === 200) break;
    if (attempt === 59) throw new Error('isolated_runtime_not_ready');
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  const model = { id: 'gloria-native-model', name: modelName, displayName: 'Gloria native qualified model',
    provider: 'codex', adapter: 'codex-cli', ApiKey: '', reasoningEffort: 'low', contextWindow: 100000, supportsTools: true, maxTurns: 4 };
  const installedModel = await request('/api/model', model);
  assert.equal(installedModel.status, 201, 'configured_model_installation_failed');
  report.installedModel = (await request('/api/model', undefined, undefined, 'GET')).data.find(item => item.id === model.id);
  assert.equal(report.installedModel?.adapter, model.adapter);
  const revocationCases = [];
  const eventsBytes = () => fs.existsSync(path.join(admitted, 'events.jsonl')) ? fs.readFileSync(path.join(admitted, 'events.jsonl')) : Buffer.alloc(0);
  const revoke = stageToken => {
    const descriptor = fs.openSync(path.join(admitted, 'revocations', sha(stageToken) + '.revoked'), 'wx', 0o600);
    try { fs.writeFileSync(descriptor, 'revoked\n'); fs.fsyncSync(descriptor); } finally { fs.closeSync(descriptor); }
  };
  const revocationAdmission = () => ({ mode: 'language_only', token: randomBytes(24).toString('hex'),
    stageToken: randomBytes(24).toString('hex'), owner: 'synthetic-revocation-owner', conversation: randomUUID(),
    turnId: randomUUID(), runId: randomUUID(), message: 'Original synthetic callback', expires: Date.now() + 60000,
    server: 'gloria-language-only', graphHash: '', flowId: '', bindingFingerprint: sha(randomBytes(32)) });
  const marked = revocationAdmission(), duringBody = revocationAdmission(), sibling = revocationAdmission();
  admissions.push(marked, duringBody, sibling);
  fs.writeFileSync(path.join(admitted, 'admissions.json'), JSON.stringify(admissions), { mode: 0o600 });
  revoke(marked.stageToken);
  let before = eventsBytes();
  const initiallyDenied = await request('/v1/chat/completions', {}, marked.stageToken);
  let unchanged = before.equals(eventsBytes());
  revocationCases.push({ case: 'initial_stage_revocation', httpStatus: initiallyDenied.status,
    noProviderOrMcpBeforeDenial: unchanged, pass: initiallyDenied.status === 403 && initiallyDenied.data.error === 'gloria_stage_revoked' && unchanged });
  const stageBody = JSON.stringify({ model: 'model-gloria-native-model', messages: [{ role: 'system', content: 'Return JSON only.' },
    { role: 'user', content: 'Original synthetic callback' }], stream: false });
  let finishBody;
  const slowBody = new ReadableStream({ start(controller) {
    controller.enqueue(new TextEncoder().encode(stageBody.slice(0, 10)));
    finishBody = () => { controller.enqueue(new TextEncoder().encode(stageBody.slice(10))); controller.close(); };
  } });
  before = eventsBytes();
  const pendingBody = fetch(endpoint + '/v1/chat/completions', { method: 'POST', headers: {
    'content-type': 'application/json', authorization: 'Bearer ' + duringBody.stageToken }, body: slowBody, duplex: 'half' });
  await new Promise(resolve => setTimeout(resolve, 200)); revoke(duringBody.stageToken); finishBody();
  const bodyDenied = await pendingBody; const bodyDeniedData = await bodyDenied.json(); unchanged = before.equals(eventsBytes());
  revocationCases.push({ case: 'revocation_during_body_await', httpStatus: bodyDenied.status,
    noProviderOrMcpBeforeDenial: unchanged, pass: bodyDenied.status === 403 && bodyDeniedData.error === 'gloria_stage_revoked' && unchanged });
  before = eventsBytes();
  const siblingMalformed = await request('/v1/chat/completions', {}, sibling.stageToken); unchanged = before.equals(eventsBytes());
  revocationCases.push({ case: 'foreign_marker_preserves_sibling', httpStatus: siblingMalformed.status,
    noProviderOrMcpBeforeDenial: unchanged, pass: siblingMalformed.status === 403 && siblingMalformed.data.error === 'gloria_stage_request_denied' && unchanged });
  const cancelledCleanup = JSON.parse(execFileSync('python', [path.join(REPO_ROOT, 'scripts/native_gloria_qualification.py'),
    '--probe-cancel-cleanup', '--base-url', endpoint, '--authority-dir', admitted], { encoding: 'utf8', timeout: 20000 }));
  revocationCases.push(cancelledCleanup);
  report.revocationProbes = { cases: revocationCases };
  assert(revocationCases.every(item => item.pass), 'installed_revocation_denial_failed');
  const owner = 'synthetic-owner-A', conversation = randomUUID();
  const definitions = opts['--serve-only'] === 'true' ? [] : [
    { name: 'normal_es', message: 'No reconozco una compra de 27.25 USD en Loja Teste ayer.', expectedLanguage: 'es', expectedRule: 'R17', owner, conversation, turnId: randomUUID() },
    { name: 'normal_pt', message: 'Não reconheço uma compra de 27.25 USD na Loja Teste ontem.', expectedLanguage: 'pt', expectedRule: 'R17', owner: 'synthetic-owner-B', conversation: randomUUID(), turnId: randomUUID() },
    { name: 'timeout', message: 'No reconozco una compra de 27.25 USD en Loja Teste ayer.', scenario: 'timeout', owner: 'synthetic-owner-C', conversation: randomUUID(), turnId: randomUUID() },
    { name: 'concurrent_replay', message: 'No reconozco una compra de 27.25 USD en Loja Teste ayer.', scenario: 'concurrent_replay', expectedLanguage: 'es', expectedRule: 'R17', owner: 'synthetic-owner-race', conversation: randomUUID(), turnId: randomUUID() },
    { name: 'poison_state', message: 'No reconozco una compra de 27.25 USD en Loja Teste ayer.', scenario: 'poison_state', owner: 'synthetic-owner-D', conversation: randomUUID(), turnId: randomUUID() },
  ];
  let installedGraph;
  for (const definition of definitions) {
    const server = `gloria-admitted-${randomBytes(4).toString('hex')}`;
    const result = build(opts['--flujo-root'], { modelId: model.id, workflowServer: server });
    const graph = structuredClone(result.flow);
    const serverInstall = await request('/api/mcp/servers', { name: server, transport: 'stdio', command: '/usr/bin/python3', cwd: '/qualification', rootPath: '/qualification',
      args: ['/qualification/native_gloria_qualification.py', '--stdio', '--admission', `/qualification/runtime/turns/${server}.json`], disabled: false });
    assert.equal(serverInstall.status, 201, 'mcp_registration_failed');
    const saved = await request(installedGraph ? `/api/flow/${graph.id}` : '/api/flow', graph, undefined, installedGraph ? 'PUT' : 'POST');
    assert([200, 201].includes(saved.status), 'saved_graph_installation_failed');
    installedGraph = (await request('/api/flow', undefined, undefined, 'GET')).data.find(item => item.id === graph.id);
    const parsed = result.flujo.FlowSnapshotSchema.parse(installedGraph);
    // FLUJO adds undefined personaOwnership in the in-memory POST value only.
    delete parsed.personaOwnership;
    const { graphHash } = assertBridge(parsed, result.inputs?.bindings ?? { modelId: model.id, workflowServer: server }, result.manifest, result.flujo);
    const record = { ...definition, token: randomBytes(24).toString('hex'), stageToken: randomBytes(24).toString('hex'),
      runId: randomUUID(), flowId: graph.id, graphHash, server, expires: Date.now() + 600000,
      binding: { owner: definition.owner, customer_id: `synthetic-${definition.name}`, session_id: randomUUID(),
        conversation_id: definition.conversation, expires_at: Date.now() / 1000 + 600 } };
    record.bindingFingerprint = sha(JSON.stringify([record.binding.owner, record.binding.customer_id, record.binding.session_id,
      record.binding.conversation_id, record.binding.expires_at]));
    admissions.push(record);
    fs.writeFileSync(path.join(admitted, 'turns', `${server}.json`), JSON.stringify(record), { mode: 0o600 });
    fs.writeFileSync(path.join(admitted, 'admissions.json'), JSON.stringify(admissions), { mode: 0o600 });
    const began = Date.now();
    const body = { model: 'flow-gloria_workflow_bridge', messages: [{ role: 'user', content: definition.message }], stream: false };
    let slowReplay;
    if (definition.scenario === 'concurrent_replay') {
      const serialized = JSON.stringify(body);
      const stream = new ReadableStream({ start(controller) { controller.enqueue(new TextEncoder().encode(serialized.slice(0, 10))); setTimeout(() => { controller.enqueue(new TextEncoder().encode(serialized.slice(10))); controller.close(); }, 500); } });
      slowReplay = fetch(endpoint + '/v1/chat/completions', { method: 'POST', headers: { 'content-type': 'application/json', authorization: 'Bearer ' + record.token }, body: stream, duplex: 'half' });
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    const completion = await request('/v1/chat/completions', body, record.token);
    if (slowReplay) { const denied = await slowReplay; await denied.text(); cases.push({ case: 'slow_body_concurrent_replay', httpStatus: denied.status, pass: denied.status === 403 }); }
    const capturedPath = path.join(admitted, 'captured', `${record.turnId}.json`);
    const captured = fs.existsSync(capturedPath) ? JSON.parse(fs.readFileSync(capturedPath)) : undefined;
    const observedPath = path.join(admitted, 'observed', `${record.turnId}.json`);
    const observed = fs.existsSync(observedPath) ? JSON.parse(fs.readFileSync(observedPath)) : undefined;
    const events = fs.existsSync(path.join(admitted, 'events.jsonl')) ? fs.readFileSync(path.join(admitted, 'events.jsonl'), 'utf8').trim().split('\n').map(line => JSON.parse(line)).filter(item => item.turn === record.turnId) : [];
    const timeoutVerified = observed?.safe_fallback_used === true && observed?.bank_calls?.length === 0 && observed?.model_observations?.some(item => ['timeout', 'cancelled'].includes(item.status));
    const poisonVerified = [403, 500].includes(completion.status) && completion.data?.error?.message === 'gloria_transient_state_required' && !captured && events.length === 0;
    cases.push({ case: definition.name, httpStatus: completion.status, seconds: (Date.now() - began) / 1000,
      graphHash, modelId: model.id, registeredServer: server, exactValidatedProjectionCaptured: Boolean(captured),
      language: captured?.language, rule_ids: captured?.rule_ids,
      model_observations: observed?.model_observations, bank_calls: observed?.bank_calls,
      safe_fallback_used: observed?.safe_fallback_used, response_mode: observed?.response_mode,
      noProviderOrMcpBeforeDenial: definition.scenario === 'poison_state' ? events.length === 0 : undefined,
      pass: definition.scenario === 'poison_state' ? poisonVerified : completion.status === 200 && Boolean(captured) && (!definition.expectedLanguage || captured.language === definition.expectedLanguage)
        && (!definition.expectedRule || captured.rule_ids.includes(definition.expectedRule)) && (definition.scenario !== 'timeout' || timeoutVerified) });
    fs.writeFileSync(path.join(runtime, `${definition.name}-private-response.json`), JSON.stringify(completion.data));
    console.log(JSON.stringify(cases.at(-1)));
    const replay = await request('/v1/chat/completions', { model: 'flow-gloria_workflow_bridge', messages: [{ role: 'user', content: definition.message }], stream: false }, record.token);
    cases.push({ case: `${definition.name}_transport_replay`, httpStatus: replay.status, pass: replay.status === 403 });
    if (definition.name === 'normal_es') {
      docker(['restart', name]);
      for (let attempt = 0; attempt < 60; attempt++) {
        const ready = await request('/api/model', undefined, undefined, 'GET').catch(() => undefined);
        if (ready?.status === 200) break;
        await new Promise(resolve => setTimeout(resolve, 1000));
      }
      const priorEvents = fs.existsSync(path.join(admitted, 'events.jsonl')) ? fs.readFileSync(path.join(admitted, 'events.jsonl')) : Buffer.alloc(0);
      const durableReplay = await request('/v1/chat/completions', { model: 'flow-gloria_workflow_bridge', messages: [{ role: 'user', content: record.message }], stream: false }, record.token);
      cases.push({ case: 'restart_transport_replay', httpStatus: durableReplay.status, pass: durableReplay.status === 403 });
      const foreign = { ...record, token: randomBytes(24).toString('hex'), owner: 'synthetic-foreign-owner', runId: randomUUID(), turnId: randomUUID() };
      admissions.push(foreign); fs.writeFileSync(path.join(admitted, 'admissions.json'), JSON.stringify(admissions));
      const denied = await request('/v1/chat/completions', { model: 'flow-gloria_workflow_bridge', messages: [{ role: 'user', content: foreign.message }], stream: false }, foreign.token);
      const afterEvents = fs.existsSync(path.join(admitted, 'events.jsonl')) ? fs.readFileSync(path.join(admitted, 'events.jsonl')) : Buffer.alloc(0);
      cases.push({ case: 'restart_foreign_conversation', httpStatus: denied.status, noProviderOrMcpBeforeDenial: priorEvents.equals(afterEvents), pass: denied.status === 403 && priorEvents.equals(afterEvents) });
      const otherSession = { ...record, token: randomBytes(24).toString('hex'), bindingFingerprint: sha(randomBytes(32)), runId: randomUUID(), turnId: randomUUID() };
      admissions.push(otherSession); fs.writeFileSync(path.join(admitted, 'admissions.json'), JSON.stringify(admissions));
      const sessionDenied = await request('/v1/chat/completions', body, otherSession.token);
      const sessionEvents = fs.existsSync(path.join(admitted, 'events.jsonl')) ? fs.readFileSync(path.join(admitted, 'events.jsonl')) : Buffer.alloc(0);
      cases.push({ case: 'restart_foreign_session_same_owner', httpStatus: sessionDenied.status, noProviderOrMcpBeforeDenial: priorEvents.equals(sessionEvents), pass: sessionDenied.status === 403 && priorEvents.equals(sessionEvents) });
    }
  }
  report.installed = true;
  report.pass = cases.length > 0 && cases.every(item => item.pass) && revocationCases.every(item => item.pass);
  report.readyForHostQualification = Boolean(opts['--serve-only'] === 'true');
} catch (error) {
  report.pass = false; report.failure = error instanceof Error ? error.message : 'qualification_failed';
} finally {
  const retained = started && (opts['--retain-runtime'] === 'diagnostic' || opts['--retain-runtime'] === 'true' && report.pass === true);
  if (started) {
    const logs = spawnSync('docker', ['logs', name], { encoding: 'utf8', maxBuffer: 8 * 1024 * 1024 });
    fs.writeFileSync(path.join(runtime, 'private-runtime.log'), (logs.stdout ?? '') + (logs.stderr ?? ''));
    if (!retained) docker(['rm', '-f', name]);
  }
  // Credential transfer belongs only to this disposable qualification. Verify
  // the absolute target before removing the task-specific private auth copy.
  assert.equal(path.dirname(path.resolve(auth)), path.resolve(runtime));
  assert(path.basename(runtime).startsWith('native-gloria-run-'));
  if (!retained) fs.rmSync(auth, { recursive: true, force: true });
  if (retained) {
    const controller = path.join(runtime, 'host-integration.json');
    fs.writeFileSync(controller, JSON.stringify({ endpoint, authority_dir: admitted, container: name, auth_dir: auth, runtime_dir: runtime, image: report.imageIdentity, qualification_pass: report.pass }), { mode: 0o600 });
    console.log(JSON.stringify({ isolatedHostIntegration: controller }));
    report.isolatedRuntimeAvailable = true;
  }
  const output = path.resolve(opts['--output']); fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.writeFileSync(output, JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify({ pass: report.pass, installed: report.installed, cases: cases.length, failure: report.failure, output }));
}
process.exitCode = report.pass ? 0 : 1;
