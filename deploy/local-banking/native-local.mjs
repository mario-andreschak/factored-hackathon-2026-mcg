#!/usr/bin/env node
// Companion deployment code. Engine and installed joined source stay unchanged.
import fs from 'node:fs/promises';
import { createReadStream } from 'node:fs';
import path from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

const DATA = '/run/local-bank/data';
const BANK = '/data/banking-state';
const CONTROL = '/data/native-authority/control';
const PRIVATE = '/data/private/local-native';
const EVIDENCE = '/data/native-transition-evidence';
const HOST = '/run/local-owner/host';
const REVISION = '676466111e7013136488b0aa7a0cf1ecbee45a86';
const ORIGIN = 'http://localhost:43800';
const BASE = { PATH: '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
  NODE_ENV: 'production', PYTHONDONTWRITEBYTECODE: '1', PYTHONUNBUFFERED: '1', TMPDIR: '/tmp' };
const sha = value => createHash('sha256').update(value).digest('hex');
const fail = () => { throw Error('Local retained native startup refused.'); };
const hashValue = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);

async function protectedFile(filename, { uid = 0, gid, mode, max = 16 * 1024 * 1024 } = {}) {
  const before = await fs.lstat(filename);
  if (!before.isFile() || before.isSymbolicLink() || before.nlink !== 1 || before.uid !== uid
    || before.size > max || (before.mode & 0o022) || gid !== undefined && before.gid !== gid
    || mode !== undefined && (before.mode & 0o7777) !== mode
    || await fs.realpath(filename) !== filename) fail();
  return before;
}
async function bytes(filename, options) {
  const before = await protectedFile(filename, options);
  const raw = await fs.readFile(filename), after = await fs.lstat(filename);
  if (before.dev !== after.dev || before.ino !== after.ino || before.size !== raw.length
    || before.mtimeMs !== after.mtimeMs || before.ctimeMs !== after.ctimeMs) fail();
  return raw;
}
async function readOnlyBytes(filename, mountedRoot, max = 2 * 1024 * 1024) {
  // Windows bind ownership/mode is not Linux private-file authority. Its RO
  // mount, private Linux ancestor (for host controls), and pinned bytes are.
  if (!filename.startsWith(mountedRoot + '/') || path.posix.normalize(filename) !== filename) fail();
  await mount(mountedRoot, true);
  const before = await fs.lstat(filename);
  if (!before.isFile() || before.isSymbolicLink() || before.nlink !== 1
    || before.size > max || await fs.realpath(filename) !== filename) fail();
  const raw = await fs.readFile(filename), after = await fs.lstat(filename);
  if (before.dev !== after.dev || before.ino !== after.ino || before.size !== raw.length
    || before.mtimeMs !== after.mtimeMs || before.ctimeMs !== after.ctimeMs) fail();
  return raw;
}
async function directory(filename, uid, gid, mode) {
  const stat = await fs.lstat(filename);
  if (!stat.isDirectory() || stat.isSymbolicLink() || stat.uid !== uid || stat.gid !== gid
    || (stat.mode & 0o7777) !== mode || await fs.realpath(filename) !== filename) fail();
}
async function mount(filename, readOnly) {
  const lines = (await fs.readFile('/proc/self/mountinfo', 'utf8')).trim().split('\n');
  const matches = lines.map(line => line.split(' ')).filter(parts => parts[4] === filename);
  if (matches.length !== 1 || !matches[0][5].split(',').includes(readOnly ? 'ro' : 'rw')) fail();
}
async function hashed(filename, expected) {
  if (!hashValue(expected) || sha(await bytes(filename)) !== expected) fail();
}
async function datasetBytes(approval) {
  const raw = await bytes(EVIDENCE + '/real-data-inventory.json');
  if (!hashValue(approval.dataset?.inventorySha256) || sha(raw) !== approval.dataset.inventorySha256) fail();
  const inventory = JSON.parse(raw);
  if (inventory.schema !== 'recovered-real-dataset-closure/v1'
    || inventory.build_id !== approval.dataset.buildId
    || inventory.source_fingerprint !== approval.dataset.sourceFingerprint
    || inventory.file_count !== 150 || inventory.total_source_bytes !== 932297878
    || !Array.isArray(inventory.files) || inventory.files.length !== 150) fail();
  const seen = new Set(), stamps = []; let total = 0;
  for (const item of inventory.files) {
    const name = item.path;
    if (typeof name !== 'string' || name.includes('\\') || path.posix.normalize(name) !== name
      || path.posix.isAbsolute(name) || name.split('/').includes('..') || seen.has(name)
      || !(name === 'CURRENT' || name.startsWith('bronze/') || name.startsWith('builds/' + inventory.build_id + '/'))
      || !Number.isSafeInteger(item.bytes) || item.bytes < 0 || !hashValue(item.sha256)) fail();
    seen.add(name); total += item.bytes;
    const filename = DATA + '/' + name, before = await fs.lstat(filename);
    if (!before.isFile() || before.isSymbolicLink() || before.nlink !== 1 || before.size !== item.bytes
      || await fs.realpath(filename) !== filename) fail();
    const digest = createHash('sha256');
    for await (const chunk of createReadStream(filename, { highWaterMark: 1024 * 1024 })) digest.update(chunk);
    if (digest.digest('hex') !== item.sha256) fail();
    stamps.push([filename, before]);
    await lease(approval);
  }
  if (total !== inventory.total_source_bytes) fail();
  for (const [filename, before] of stamps) {
    const after = await fs.lstat(filename);
    if (before.dev !== after.dev || before.ino !== after.ino || before.size !== after.size
      || before.mtimeMs !== after.mtimeMs || before.ctimeMs !== after.ctimeMs) fail();
  }
}
async function lease(approval) {
  await directory('/run/local-owner', 0, 0, 0o700);
  const held = JSON.parse(await readOnlyBytes(HOST + '/repository-ci.lock.json', HOST, 8192));
  const pulse = JSON.parse(await readOnlyBytes(HOST + '/local-runtime-heartbeat.json', HOST, 8192));
  const owner = approval.runtimeLease;
  if (!owner || !/^[a-f0-9]{32}$/.test(owner.ownerToken || '')
    || held.owner_token !== owner.ownerToken || held.head !== approval.companionRevision
    || held.controller_pid !== owner.controllerPid || pulse.owner_token !== owner.ownerToken
    || pulse.controller_pid !== owner.controllerPid || pulse.head !== approval.companionRevision
    || pulse.status !== 'active' || pulse.canonical_bank_volume !== 'hackathon-banking-mcp-state'
    || !Number.isInteger(owner.controllerPid) || owner.controllerPid < 1) fail();
  const age = Date.now() - Date.parse(pulse.heartbeat_at);
  if (!Number.isFinite(age) || age < -5000 || age > 30000) fail();
}

export function localCommands(snapshotControlToken) {
  if (typeof snapshotControlToken !== 'string' || snapshotControlToken.length < 32 || /\s/.test(snapshotControlToken)) fail();
  const worker = { ...BASE, HOME: '/home/node', CODEX_HOME: '/run/native-login',
    FLUJO_CONTAINER: '1', FLUJO_APP_ROOT: '/app', FLUJO_DATA_DIR: '/data/native-flujo',
    FLUJO_EXPOSURE_MODE: 'localhost', FLUJO_BASE_URL: 'http://127.0.0.1:4200',
    FLUJO_MCP_APP_SANDBOX_HOST: '127.0.0.1', FLUJO_MCP_APP_SANDBOX_PORT: '4201',
    FLUJO_MCP_APP_SANDBOX_ALLOW_ALL: '0', FLUJO_EXECUTION_ADAPTER_MODULE: '/app/fly-native-execution.ts',
    FLUJO_SNAPSHOT_CONTROL_TOKEN: snapshotControlToken };
  const application = { ...BASE, HOME: '/nonexistent', BANKING_DATA_DIR: DATA,
    BANKING_CONFIG_FILE: '/run/dispute/frontend.json', BANKING_STATE_DIR: '/data/native-frontend-state',
    BANKING_STATIC_DIR: '/opt/savia/dist', BANKING_PUBLIC_ORIGIN: ORIGIN, BANKING_COOKIE_SECURE: '0' };
  return [
    { name: 'local native worker', command: '/usr/sbin/gosu', args: ['node', 'node',
      'scripts/launch-next.mjs', 'start', '-p', '4200', '-H', '127.0.0.1'], cwd: '/app', env: worker },
    { name: 'local retained bank application', command: '/usr/sbin/gosu', args: ['banking',
      '/opt/joined/.venv/bin/python', '/opt/joined/scripts/run_dispute.py', '--state-dir', BANK,
      '--bank-config-file', '/run/dispute/bank-config.json', '--native-url', 'http://127.0.0.1:4200',
      '--native-authority-dir', CONTROL, '--transition-receipt', '/run/dispute/transition-receipt.json',
      '--application-source-root', '/opt/joined', '--native-reader-group', '10002', '--port', '8082',
      '--enable-simulated-intake'], cwd: '/opt/joined', env: application },
    { name: 'local application proxy', command: '/usr/sbin/gosu', args: ['node', 'node',
      '/run/local-native/local-proxy.mjs'], cwd: '/app', env: { ...BASE, HOME: '/home/node' } },
  ];
}

async function publish(filename, raw, gid, mode) {
  const temporary = path.join(path.dirname(filename), '.local-' + randomUUID());
  let file;
  try {
    file = await fs.open(temporary, 'wx', mode); await file.writeFile(raw);
    await file.chown(0, gid); await file.chmod(mode); await file.sync(); await file.close(); file = undefined;
    await fs.rename(temporary, filename);
  } finally { await file?.close(); await fs.unlink(temporary).catch(() => {}); }
}
async function run() {
  if (process.platform !== 'linux' || process.getuid?.() !== 0) fail();
  await mount('/opt/local-native', true); await mount(HOST, true); await mount(DATA, true); await mount(BANK, false);
  await directory('/run', 0, 0, 0o755);
  await fs.mkdir('/run/local-owner', { mode: 0o700 }).catch(error => { if (error.code !== 'EEXIST') throw error; });
  const ownerParent = await fs.lstat('/run/local-owner');
  if (!ownerParent.isDirectory() || ownerParent.isSymbolicLink() || ownerParent.uid !== 0
    || await fs.realpath('/run/local-owner') !== '/run/local-owner') fail();
  await fs.chown('/run/local-owner', 0, 0); await fs.chmod('/run/local-owner', 0o700);
  const approval = JSON.parse(await bytes(PRIVATE + '/approval.json'));
  if (approval.schema !== 'savia-local-retained-release/v1' || approval.applicationRevision !== REVISION
    || !/^[a-f0-9]{40}$/.test(approval.companionRevision || '')
    || !/^registry\.fly\.io\/flujo-factored-2026@sha256:[a-f0-9]{64}$/.test(approval.approvedImage || '')
    || approval.approvedImage !== process.env.SAVIA_LOCAL_JOINED_IMAGE
    || approval.canonicalBankVolume !== 'hackathon-banking-mcp-state'
    || approval.nativeStateVolume !== process.env.SAVIA_LOCAL_NATIVE_VOLUME
    || approval.enableSimulatedIntake !== true || approval.originalBankAuthorityRetired !== true) fail();
  await lease(approval);
  const installed = JSON.parse(await bytes('/opt/joined/build-receipt.json'));
  if (installed.applicationRevision !== REVISION || installed.sourceManifestSha256 !== approval.sourceManifestSha256
    || installed.flujoRevision !== '0ba62296520a505e6d71eddf5aa650691f3dc311' || installed.sourceInputsVerified !== true) fail();
  await fs.mkdir('/run/local-native', { mode: 0o755 }).catch(error => { if (error.code !== 'EEXIST') throw error; });
  await directory('/run/local-native', 0, 0, 0o755);
  for (const name of ['native-local.mjs', 'local-proxy.mjs']) {
    const raw = await readOnlyBytes('/opt/local-native/' + name, '/opt/local-native');
    if (!hashValue(approval.companionFiles?.[name]) || sha(raw) !== approval.companionFiles[name]) fail();
    await publish('/run/local-native/' + name, raw, 0, 0o444);
  }
  await mount('/data', false); await directory('/data', 0, 0, 0o755);
  await directory('/data/private', 0, 0, 0o700); await directory(PRIVATE, 0, 0, 0o700);
  await directory(BANK, 10001, 10001, 0o700);
  await directory('/data/native-authority', 0, 10002, 0o751);
  await directory(CONTROL, 10001, 10002, 0o2750);
  await directory(CONTROL + '/revocations', 10001, 10002, 0o2750);
  await bytes(CONTROL + '/admissions.json', { uid: 10001, gid: 10002, mode: 0o640, max: 2 * 1024 * 1024 });
  await directory('/data/native-authority/worker', 1000, 1000, 0o700);
  await directory('/data/native-flujo', 1000, 1000, 0o700);
  await directory('/data/native-frontend-state', 10001, 10001, 0o700);
  await directory(EVIDENCE, 0, 10001, 0o550);
  const receiptRaw = await bytes(PRIVATE + '/transition-receipt.json');
  if (sha(receiptRaw) !== approval.transitionReceiptSha256) fail();
  const receipt = JSON.parse(receiptRaw);
  if (receipt.schema !== 'dispute-retained-transition/v1' || receipt.native_state_dir !== BANK
    || receipt.bank_path !== BANK + '/banking.db' || receipt.native_authority_dir !== CONTROL
    || receipt.new_frontend_state_dir !== '/data/native-frontend-state' || receipt.native_reader_group !== 10002
    || receipt.source?.root !== '/opt/joined' || receipt.archive_path !== BANK + '/legacy-bank-before-native.sqlite3'
    || receipt.operator_proof?.coverage_start > Math.floor(Date.now() / 1000) - 86400) fail();
  const proof = receipt.operator_proof;
  if (!Number.isInteger(proof?.coverage_start) || proof.coverage_start <= 0
    || proof.coverage_start > Math.floor(Date.now() / 1000) - 86400) fail();
  const artifacts = [proof?.path, proof?.coverage_proof_path, proof?.lease_artifact?.path,
    proof?.authority_artifact?.path, ...(proof?.obligation_artifacts || []).map(item => item?.path),
    ...Object.values(proof?.archives || {}).map(item => item?.path)];
  if (artifacts.length < 7 || artifacts.some(name => typeof name !== 'string'
    || !name.startsWith(EVIDENCE + '/') || path.posix.normalize(name) !== name)) fail();
  // Large sealed archives are streamed by the installed Python verifier.
  for (const name of artifacts) await protectedFile(name, { gid: 10001, mode: 0o440, max: Number.MAX_SAFE_INTEGER });
  await protectedFile(receipt.archive_path, { gid: 10001, mode: 0o440, max: Number.MAX_SAFE_INTEGER });
  await hashed(EVIDENCE + '/local-kernel-qualification.json', approval.kernelQualificationSha256);
  const kernel = JSON.parse(await bytes(EVIDENCE + '/local-kernel-qualification.json'));
  if (kernel.schema !== 'savia-local-native-kernel-qualification/v1' || kernel.status !== 'pass'
    || kernel.image !== approval.approvedImage || kernel.applicationRevision !== REVISION
    || kernel.nativeWrapperSha256 !== installed.nativeWrapperSha256
    || kernel.nativeBinarySha256 !== installed.nativeBinarySha256
    || ['actualDockerKernel', 'uidAndGroups', 'userPidNamespace', 'wrappedRawCliHelp',
      'privateSentinelsDenied', 'controlsMutationDenied', 'freshInvocationHomeOnly', 'immutableProfileReadback',
      'readOnlyHostBindBoundary', 'readOnlyDataBindBoundary', 'crossUidSupervisorSignals']
      .some(key => kernel[key] !== true)) fail();
  // A read-only host DATA bind is protected by a Linux-only private ancestor.
  await fs.chown('/run/local-bank', 0, 10001); await fs.chmod('/run/local-bank', 0o750);
  for (const name of ['QUALIFICATION_SYNTHETIC.json', 'SYNTHETIC_BANKING_DEMO.json']) {
    try { await fs.lstat(DATA + '/' + name); fail(); } catch (error) { if (error.code !== 'ENOENT') throw error; }
  }
  const current = (await fs.readFile(DATA + '/CURRENT', 'utf8')).trim();
  if (current !== approval.dataset?.buildId || !/^[A-Za-z0-9_-]{1,96}$/.test(current)) fail();
  const snapshot = JSON.parse(await fs.readFile(DATA + '/builds/' + current + '/snapshot.json', 'utf8'));
  if (snapshot.source_fingerprint !== approval.dataset?.sourceFingerprint) fail();
  for (const [name, expected] of [['snapshot.json', approval.dataset.snapshotSha256],
    ['manifest.json', approval.dataset.manifestSha256], ['source_objects.json', approval.dataset.sourceObjectsSha256]]) {
    const filename = DATA + '/builds/' + current + '/' + name, stat = await fs.lstat(filename);
    if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 4 * 1024 * 1024
      || !hashValue(expected) || sha(await fs.readFile(filename)) !== expected) fail();
  }
  await datasetBytes(approval);
  const bank = await bytes(PRIVATE + '/bank-config.json');
  const bankConfig = JSON.parse(bank);
  if (bankConfig.mode !== 'delegated' || bankConfig.data_dir !== DATA || bankConfig.state_db !== BANK + '/banking.db'
    || bankConfig.source_env !== '/run/dispute/source.env' || bankConfig.ledger_continuity_approved !== true
    || bankConfig.sandbox_report_coverage_start !== proof.coverage_start) fail();
  const directories = [['/run/dispute', 10001], ['/run/native-login', 1000]];
  for (const [name, gid] of directories) {
    await fs.mkdir(name, { mode: 0o750 }).catch(error => { if (error.code !== 'EEXIST') throw error; });
    const stat = await fs.lstat(name);
    if (!stat.isDirectory() || stat.isSymbolicLink() || stat.uid !== 0 || await fs.realpath(name) !== name) fail();
    await fs.chown(name, 0, gid); await fs.chmod(name, 0o750);
  }
  for (const [name, raw] of [['bank-config.json', bank], ['frontend.json', await bytes(PRIVATE + '/frontend.json')],
    ['transition-receipt.json', receiptRaw], ['frontend-signer.pem', await bytes(PRIVATE + '/frontend-signer.pem')],
    ['source.env', await bytes(PRIVATE + '/source.env')]]) await publish('/run/dispute/' + name, raw, 10001, 0o440);
  await publish('/run/native-login/auth.json', await bytes(PRIVATE + '/provider-auth.json'), 1000, 0o440);
  await publish('/run/native-login/config.toml', Buffer.from('cli_auth_credentials_store = "file"\n'), 1000, 0o440);
  if (sha(await bytes(CONTROL + '/native-profile.json', { gid: 10002, mode: 0o440 }))
    !== sha(await bytes('/opt/native/native-profile.json'))) fail();
  // Call the installed transition verifier, not an alternative adoption path.
  const code = 'from pathlib import Path; from frontend.server.deployment_transition import verify; verify(receipt=Path("/run/dispute/transition-receipt.json"),bank_config_file=Path("/run/dispute/bank-config.json"),source_root=Path("/opt/joined"),native_state_dir=Path("/data/banking-state"))';
  const verified = spawnSync('/usr/sbin/gosu', ['banking', '/opt/joined/.venv/bin/python', '-c', code],
    { cwd: '/opt/joined', env: BASE, encoding: 'utf8', timeout: 60000, maxBuffer: 8192 });
  if (verified.status !== 0) fail();
  await lease(approval);
  const workerSecret = JSON.parse(await bytes(PRIVATE + '/worker.json'));
  const { supervise, initializeNativeModel } = await import('/opt/savia/fly/runtime.mjs');
  let timer, checking = false, failed = false;
  timer = setInterval(async () => {
    if (checking) return; checking = true;
    try { await lease(approval); }
    catch { if (!failed) { failed = true; console.error('Local runtime lease unavailable; stopping.'); process.kill(process.pid, 'SIGTERM'); } }
    finally { checking = false; }
  }, 5000);
  let result;
  try {
    console.log('Local retained native admission passed; starting existing frontend service.');
    result = await supervise({ commands: localCommands(workerSecret.snapshot_control_token), onStarted: initializeNativeModel });
  } finally { clearInterval(timer); }
  process.exit(result);
}

if (import.meta.url === pathToFileURL(process.argv[1] || '').href)
  run().catch(() => { console.error('Local retained native startup refused.'); process.exitCode = 1; });
