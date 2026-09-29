/** Root deployment step for the existing Linux worker. Never prints policy data. */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const source = '/run/banking/policy.json'; // Read-only host staging mount.
const directory = '/run/banking-runtime';
const target = path.join(directory, 'policy.json'); // Live authority, native filesystem.
const expected = process.argv[2];
let temporary;
try {
  if (process.platform !== 'linux' || process.getuid?.() !== 0 || !/^[a-f0-9]{64}$/.test(expected ?? '')) {
    throw new Error('root_and_approved_digest_required');
  }
  const parent = fs.lstatSync('/run');
  if (!parent.isDirectory() || parent.isSymbolicLink() || parent.uid !== 0 || (parent.mode & 0o022)) {
    throw new Error('protected_runtime_parent_required');
  }
  fs.mkdirSync(directory, { mode: 0o750 });
} catch (error) {
  if (error.code !== 'EEXIST') {
    console.error(JSON.stringify({ provisioned: false, code: 'runtime_policy_provision_failed' }));
    process.exit(1);
  }
}
try {
  const dir = fs.lstatSync(directory);
  if (!dir.isDirectory() || dir.isSymbolicLink() || dir.uid !== 0 || (dir.mode & 0o022)) {
    throw new Error('protected_runtime_directory_required');
  }
  fs.chownSync(directory, 0, 1000);
  fs.chmodSync(directory, 0o750);
  const bytes = fs.readFileSync(source);
  const digest = value => crypto.createHash('sha256').update(value).digest('hex');
  if (bytes.length > 65536 || !bytes.length || digest(bytes) !== expected) throw new Error('approved_policy_required');
  const policy = JSON.parse(bytes.toString('utf8'));
  if (!policy || typeof policy !== 'object' || Array.isArray(policy)
      || typeof policy.deploymentId !== 'string' || typeof policy.workspace !== 'string'
      || typeof policy.executionToken !== 'string' || typeof policy.graphHash !== 'string') {
    throw new Error('approved_policy_required');
  }
  if (fs.existsSync(target)) {
    const old = fs.lstatSync(target);
    if (!old.isFile() || old.isSymbolicLink() || old.uid !== 0) throw new Error('protected_runtime_file_required');
  }
  temporary = path.join(directory, `.policy-${crypto.randomUUID()}`);
  const handle = fs.openSync(temporary, 'wx', 0o440);
  try {
    fs.writeFileSync(handle, bytes);
    fs.fchownSync(handle, 0, 1000);
    fs.fchmodSync(handle, 0o440);
    fs.fsyncSync(handle);
  } finally { fs.closeSync(handle); }
  fs.renameSync(temporary, target);
  temporary = undefined;
  const parentHandle = fs.openSync(directory, 'r');
  try { fs.fsyncSync(parentHandle); } finally { fs.closeSync(parentHandle); }
  const installed = fs.lstatSync(target);
  if (installed.uid !== 0 || installed.gid !== 1000 || (installed.mode & 0o777) !== 0o440
      || digest(fs.readFileSync(target)) !== expected) throw new Error('runtime_policy_receipt_failed');
  console.log(JSON.stringify({ provisioned: true, sha256: expected, uid: 0, gid: 1000, mode: '0440', atomic: true }));
} catch {
  if (temporary && path.dirname(temporary) === directory) {
    try { fs.unlinkSync(temporary); } catch {}
  }
  console.error(JSON.stringify({ provisioned: false, code: 'runtime_policy_provision_failed' }));
  process.exit(1);
}
