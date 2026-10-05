// Preserve exact audit correlation across restart; never change application data.
import { execFile } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { promisify } from 'node:util';
import { assertPrivateDirectory, ensurePrivateDirectory, readPrivateJson, writePrivateJson } from '../../../flujo-cloud/lib/private-files.mjs';

const execute = promisify(execFile);
const cli = 'C:/Users/Moe/.fly/bin/flyctl.exe';
const app = 'flujo-factored-2026';
const [machine, operation] = process.argv.slice(2);
const directory = path.join(process.env.USERPROFILE ?? '', '.flujo-fly', app);
const bundleFile = path.join(directory, 'verification-ledger-persistence.json');
const localScript = path.join(import.meta.dirname, 'verify-ledger.py');
const roles = ['script', 'receipt', 'binding'];
let phase = 'arguments';
const hash = value => createHash('sha256').update(value).digest('hex');
const require = condition => { if (!condition) throw new Error('Private persistence precondition failed'); };

async function fly(args, allowSafeReport = false) {
  try {
    return (await execute(cli, args, { windowsHide: true, timeout: 60_000, maxBuffer: 1024 * 1024 })).stdout;
  } catch (error) {
    if (allowSafeReport && typeof error.stdout === 'string') return error.stdout;
    throw new Error('Private persistence SSH/SFTP operation failed');
  }
}

function safeReport(output) {
  const report = output.split(/\r?\n/).filter(line => /^\{.*\}$/.test(line)).map(line => JSON.parse(line)).at(-1);
  require(report && Object.values(report).every(value => typeof value === 'boolean'
    || (typeof value === 'number' && Number.isFinite(value))));
  return report;
}

async function protectReceipt(filename) {
  await assertPrivateDirectory(path.dirname(filename));
  const metadata = await fs.lstat(filename);
  require(metadata.isFile() && !metadata.isSymbolicLink() && metadata.nlink === 1 && metadata.size < 65536);
  if (process.platform !== 'win32') return;
  // verify.mjs writes into an owner-private directory but may inherit its ACL.
  // Seal only this fixed receipt path; its JSON and correlation remain unchanged.
  const source = String.raw`$ErrorActionPreference='Stop'
$p=[Environment]::GetEnvironmentVariable('FLUJO_PRIVATE_RECEIPT')
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$sid=$identity.User
$acl=[IO.File]::GetAccessControl($p)
$owner=$acl.GetOwner([Security.Principal.SecurityIdentifier])
if ($owner.Value -ne $sid.Value -and $owner.Value -ne $identity.Owner.Value) { throw 'unsafe' }
if (([IO.File]::GetAttributes($p) -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'unsafe' }
$acl.SetOwner($sid)
$acl.SetAccessRuleProtection($true,$false)
foreach($rule in @($acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))) { $acl.RemoveAccessRuleSpecific($rule) }
$acl.SetAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,[Security.AccessControl.FileSystemRights]::FullControl,[Security.AccessControl.AccessControlType]::Allow))
[IO.File]::SetAccessControl($p,$acl)
`;
  const powershell = path.join(process.env.SystemRoot ?? 'C:/Windows', 'System32/WindowsPowerShell/v1.0/powershell.exe');
  await execute(powershell, ['-NoProfile', '-NonInteractive', '-EncodedCommand', Buffer.from(source, 'utf16le').toString('base64')],
    { windowsHide: true, timeout: 15_000, maxBuffer: 1024,
      env: { SystemRoot: process.env.SystemRoot, WINDIR: process.env.SystemRoot, FLUJO_PRIVATE_RECEIPT: filename } });
}

async function context() {
  require(/^[a-f0-9]{14}$/.test(machine ?? '') && ['--save', '--restore'].includes(operation)
    && process.argv.length === 4 && Boolean(process.env.USERPROFILE));
  phase = 'private receipt';
  const receiptPath = path.join(directory, 'verification-session.json');
  await protectReceipt(receiptPath);
  const receipt = await readPrivateJson(receiptPath);
  phase = 'exact run metadata';
  const metadata = await readPrivateJson(path.join(directory, 'verification-ledger-binding.json'));
  require(receipt.version === 1 && /^[a-f0-9-]{36}$/.test(receipt.runId ?? '')
    && /^[a-f0-9]{64}$/.test(receipt.bankSessionTokenHash ?? '')
    && receipt.phase === 'revocation-settled' && metadata.runId === receipt.runId && metadata.machine === machine);
  const suffix = hash(receipt.runId).slice(0, 16);
  const names = { script: `/tmp/savia-verification-${suffix}-audit.py`,
    receipt: `/tmp/savia-verification-${suffix}-session.json`,
    binding: `/tmp/savia-verification-${suffix}-binding.json` };
  require(roles.every(role => metadata[role] === names[role]));
  return { receipt, names };
}

function validatePayload(payload, current) {
  require(payload && roles.every(role => payload[role] && payload[role].path === current.names[role]
    && /^[a-f0-9]{64}$/.test(payload[role].sha256 ?? '') && typeof payload[role].base64 === 'string'));
  const bytes = Object.fromEntries(roles.map(role => [role, Buffer.from(payload[role].base64, 'base64')]));
  require(roles.every(role => bytes[role].length > 0 && bytes[role].length < 1024 * 1024
    && bytes[role].toString('base64') === payload[role].base64 && hash(bytes[role]) === payload[role].sha256));
  const frozen = JSON.parse(bytes.receipt.toString('utf8'));
  const binding = JSON.parse(bytes.binding.toString('utf8'));
  require(frozen.version === 1 && frozen.runId === current.receipt.runId
    && frozen.bankSessionTokenHash === current.receipt.bankSessionTokenHash
    && binding.version === 1 && binding.runId === current.receipt.runId
    && binding.bankSessionTokenHash === current.receipt.bankSessionTokenHash
    && typeof binding.sessionId === 'string' && binding.sessionId.length >= 16 && binding.sessionId.length <= 128
    && typeof binding.profileId === 'string' && binding.profileId.length > 0 && binding.profileId.length <= 128
    && Number.isSafeInteger(binding.expires));
  return bytes;
}

async function audit(names) {
  const output = await fly(['ssh', 'console', '--app', app, '--machine', machine, '--user', 'root', '--quiet',
    '--command', `python3 ${names.script} check --receipt ${names.receipt} --binding ${names.binding}`], true);
  const result = safeReport(output);
  require(result.auditPassed === true);
  return result;
}

async function remotePython(source) {
  const encoded = Buffer.from(source).toString('base64');
  const command = `python3 -c "import base64;exec(base64.b64decode('${encoded}'))"`;
  return safeReport(await fly(['ssh', 'console', '--app', app, '--machine', machine, '--user', 'root', '--quiet', '--command', command], true));
}

async function remoteFiles(payload, seal = false, selectedRoles = roles) {
  // Paths are derived from the validated run; this Python code never touches /data.
  const entries = selectedRoles.map(role => [role, payload[role].path, payload[role].sha256]);
  const source = `import hashlib,json,os,stat\nfrom pathlib import Path\nentries=${JSON.stringify(entries)}\nresult={}\ntry:\n for role,name,expected in entries:\n  p=Path(name)\n  present=p.exists() or p.is_symlink()\n  if present:\n   s=p.lstat()\n   assert stat.S_ISREG(s.st_mode) and s.st_uid==0 and s.st_nlink==1 and s.st_size<1048576 and p.resolve()==p\n   assert hashlib.sha256(p.read_bytes()).hexdigest()==expected\n   ${seal ? 'os.chmod(p,0o600)' : 'assert stat.S_IMODE(s.st_mode)==0o600'}\n  result[role+'Present']=present\n result['filesValidated']=True\n print(json.dumps(result))\nexcept Exception:\n print(json.dumps({'filesValidated':False}))\n raise SystemExit(2)\n`;
  const result = await remotePython(source);
  require(result.filesValidated === true);
  return result;
}

async function createRemoteStagingDirectory(current) {
  const suffix = hash(current.receipt.runId).slice(0, 16);
  const directory = `/tmp/savia-verification-${suffix}-restore-${randomUUID().replaceAll('-', '')}`;
  const source = `import json,os,stat\nfrom pathlib import Path\np=Path(${JSON.stringify(directory)})\ntry:\n assert os.getuid()==0 and p.parent==Path('/tmp')\n s=p.parent.lstat()\n assert stat.S_ISDIR(s.st_mode) and s.st_uid==0 and (s.st_mode & stat.S_ISVTX)\n os.mkdir(p,0o700)\n print(json.dumps({'privateStagingCreated':True}))\nexcept Exception:\n print(json.dumps({'privateStagingCreated':False}))\n raise SystemExit(2)\n`;
  require((await remotePython(source)).privateStagingCreated === true);
  return directory;
}

async function publishMissing(payload, directory, missing) {
  const entries = missing.map(role => [path.posix.join(directory, role), payload[role].path, payload[role].sha256]);
  // Upload into root0700 first, then link each verified file to its exact path.
  // link() refuses an existing target, including a symlink created in /tmp.
  const source = `import hashlib,json,os,stat\nfrom pathlib import Path\nd=Path(${JSON.stringify(directory)})\nentries=${JSON.stringify(entries)}\ntry:\n s=d.lstat()\n assert stat.S_ISDIR(s.st_mode) and s.st_uid==0 and stat.S_IMODE(s.st_mode)==0o700 and d.resolve()==d\n for source,target,expected in entries:\n  p=Path(source)\n  s=p.lstat()\n  assert p.parent==d and p.resolve()==p and stat.S_ISREG(s.st_mode) and s.st_uid==0 and s.st_nlink==1 and s.st_size<1048576\n  assert hashlib.sha256(p.read_bytes()).hexdigest()==expected\n  os.chmod(p,0o600)\n for source,target,expected in entries:\n  os.link(source,target,follow_symlinks=False)\n  os.unlink(source)\n os.rmdir(d)\n print(json.dumps({'filesPublished':len(entries),'privateStagingRemoved':True}))\nexcept Exception:\n print(json.dumps({'privateStagingRemoved':False}))\n raise SystemExit(2)\n`;
  const result = await remotePython(source);
  require(result.filesPublished === missing.length && result.privateStagingRemoved === true);
}

async function main() {
  const current = await context();
  const temporary = path.join(directory, `persistence-transfer-${randomUUID()}`);
  await ensurePrivateDirectory(temporary);
  try {
    if (operation === '--save') {
      phase = 'trusted audit script';
      const trusted = await remoteFiles({ script: { path: current.names.script,
        sha256: hash(await fs.readFile(localScript)) } }, false, ['script']);
      require(trusted.scriptPresent === true);
      phase = 'before-restart exact audit';
      const result = await audit(current.names);
      const payload = {};
      for (const role of roles) {
        phase = `download ${role}`;
        const filename = path.join(temporary, role);
        await fly(['ssh', 'sftp', 'get', current.names[role], filename, '--app', app, '--machine', machine, '--user', 'root', '--quiet']);
        const metadata = await fs.lstat(filename);
        require(metadata.isFile() && !metadata.isSymbolicLink() && metadata.nlink === 1 && metadata.size < 1024 * 1024);
        const bytes = await fs.readFile(filename);
        payload[role] = { path: current.names[role], sha256: hash(bytes), base64: bytes.toString('base64') };
      }
      phase = 'downloaded correlation';
      validatePayload(payload, current);
      require(payload.script.sha256 === hash(await fs.readFile(localScript)));
      phase = 'remote audit file ownership';
      const present = await remoteFiles(payload);
      require(roles.every(role => present[`${role}Present`] === true));
      require((await context()).receipt.runId === current.receipt.runId);
      phase = 'private bundle publication';
      await writePrivateJson(bundleFile, { version: 1, runId: current.receipt.runId, machine,
        savedAt: new Date().toISOString(), payload, beforeRestart: result });
      console.log(JSON.stringify({ saved: true, exactBindingValidated: true, filesPreserved: 3, auditPassed: true }));
      return;
    }

    const bundle = await readPrivateJson(bundleFile, { maxBytes: 4 * 1024 * 1024 });
    require(bundle.version === 1 && bundle.runId === current.receipt.runId && bundle.machine === machine
      && bundle.beforeRestart?.auditPassed === true);
    const bytes = validatePayload(bundle.payload, current);
    require(bundle.payload.script.sha256 === hash(await fs.readFile(localScript)));
    const present = await remoteFiles(bundle.payload);
    const missing = roles.filter(role => !present[`${role}Present`]);
    const staging = missing.length ? await createRemoteStagingDirectory(current) : null;
    for (const role of missing) {
      const filename = path.join(temporary, role);
      await fs.writeFile(filename, bytes[role], { mode: 0o600, flag: 'wx' });
      await fly(['ssh', 'sftp', 'put', filename, path.posix.join(staging, role), '--app', app, '--machine', machine,
        '--user', 'root', '--mode', '0600', '--quiet']);
    }
    if (missing.length) await publishMissing(bundle.payload, staging, missing);
    const sealed = await remoteFiles(bundle.payload, true);
    require(roles.every(role => sealed[`${role}Present`] === true));
    const result = await audit(current.names);
    require((await context()).receipt.runId === current.receipt.runId);
    await writePrivateJson(path.join(directory, 'verification-ledger-persistence-result.json'),
      { ...result, persistencePassed: true, filesRestored: missing.length });
    console.log(JSON.stringify({ ...result, persistencePassed: true, filesRestored: missing.length }));
  } finally {
    for (const role of roles) await fs.unlink(path.join(temporary, role)).catch(() => {});
    await fs.rmdir(temporary).catch(() => {});
  }
}

main().catch(() => {
  console.log(JSON.stringify({ persistenceOperationCompleted: false, persistencePassed: false }));
  console.error(`Persistence verification failed during ${phase}.`);
  process.exitCode = 1;
});
