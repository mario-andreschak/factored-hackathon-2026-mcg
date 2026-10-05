import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash, randomBytes } from 'node:crypto';
import { spawn } from 'node:child_process';
import { ensurePrivateDirectory, writePrivateJson } from '../../../flujo-cloud/lib/private-files.mjs';

const source = 'flujo-slack-flujo-1';
const project = path.resolve(import.meta.dirname, '../..');
const output = path.join(process.env.USERPROFILE, '.flujo-fly', 'flujo-factored-2026');
await ensurePrivateDirectory(output);
const stage = await ensurePrivateDirectory(path.join(output, `migration-${Date.now()}`));
const workerRoot = '/data/flujo/workspaces/default-workspace';
const targetRoot = path.join(stage, 'flujo', 'workspaces', 'default-workspace');
await fs.mkdir(path.join(targetRoot, 'db'), { recursive: true });

async function command(executable, args, input) {
  return new Promise((resolve, reject) => {
    const child = spawn(executable, args, { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
    const chunks = [], errors = [];
    child.stdout.on('data', chunk => chunks.push(chunk));
    child.stderr.on('data', chunk => errors.push(chunk));
    child.on('error', reject);
    child.on('close', code => code === 0 ? resolve(Buffer.concat(chunks)) : reject(new Error(`${executable} failed (${code}); private diagnostics withheld`)));
    child.stdin.end(input);
  });
}

async function dockerCopy(containerPath, localPath, optional = false) {
  await fs.mkdir(path.dirname(localPath), { recursive: true });
  try { await command('docker', ['cp', `${source}:${containerPath}`, localPath]); }
  catch (error) { if (!optional) throw error; }
}

for (const filename of ['encryption_key.json', 'models.json', 'global_env_vars.json',
  'speech_settings.json', 'mcp_servers.json']) {
  await dockerCopy(`${workerRoot}/db/${filename}`, path.join(targetRoot, 'db', filename));
}
for (const directory of ['flows', 'models', 'flow-versions']) {
  await dockerCopy(`${workerRoot}/db/${directory}`, path.join(targetRoot, 'db', directory));
}
for (const filename of ['auth.json', 'flujo-auth-source.json']) {
  await dockerCopy(`${workerRoot}/db/codex-runtime/${filename}`, path.join(targetRoot, 'db', 'codex-runtime', filename));
}
await dockerCopy(`${workerRoot}/.flujo-worker-snapshot.json`, path.join(targetRoot, '.flujo-worker-snapshot.json'));
// Installed MCP packages are execution dependencies, with no browser profile,
// recordings, user files or conversations included in this allowlist.
await dockerCopy(`${workerRoot}/mcp-servers`, path.join(targetRoot, 'mcp-servers'));
await fs.mkdir(path.join(targetRoot, 'userdata'), { recursive: true });
await fs.mkdir(path.join(targetRoot, 'db', 'conversations'), { recursive: true });
// Retain authority ownership/revocation tombstones separately from transcripts.
await dockerCopy('/data/flujo/banking-authority', path.join(stage, 'flujo', 'banking-authority'));

const bankPrivate = path.join(stage, 'private', 'banking');
await fs.mkdir(bankPrivate, { recursive: true });
for (const [from, to] of [['flujo-policy.json', 'policy.json'], ['real-stdio.json', 'bank-config.json'],
  ['operator-stdio.json', 'operator-config.json'], ['demo-stdio.json', 'demo-config.json'],
  ['restricted-model-catalog.json', 'restricted-model-catalog.json'], ['signer.pem', 'bank-signer.pem']]) {
  await fs.copyFile(path.join(project, 'private', 'banking-mcp', from), path.join(bankPrivate, to));
}
await fs.copyFile(path.join(project, 'S3credentials.env'), path.join(bankPrivate, 'source.env'));
await fs.mkdir(path.join(stage, 'private', 'frontend'), { recursive: true });
const frontend = JSON.parse(await fs.readFile(path.join(project, 'private', 'banking-frontend', 'frontend.json'), 'utf8'));
frontend.chat.base_url = 'http://127.0.0.1:4200';
frontend.chat.frontend_signing_key_file = '/run/frontend/signer.pem';
await fs.writeFile(path.join(stage, 'private', 'frontend', 'frontend.json'), JSON.stringify(frontend));
await fs.copyFile(path.join(project, 'private', 'banking-mcp', 'frontend-signer.pem'), path.join(stage, 'private', 'frontend', 'signer.pem'));
await fs.copyFile(path.resolve(project, '../flujo-slack-bot/.docker/worker.snapshot'), path.join(stage, 'private', 'worker.snapshot'));

// Preserve bank ledger generations via SQLite's consistent online backup.
// These are separate from FLUJO conversation and browser session history.
const backupScript = `import os, sqlite3, tempfile, tarfile, sys\nroot=tempfile.mkdtemp(prefix='fly-readonly-ledger-')\nfor prefix in ['banking-state','banking-demo-state']:\n os.makedirs(root+'/'+prefix,exist_ok=True)\n for name in os.listdir('/'+prefix):\n  if name.endswith('.db') or name.endswith('.sqlite3'):\n   src=sqlite3.connect('file:/'+prefix+'/'+name+'?mode=ro',uri=True)\n   dst=sqlite3.connect(root+'/'+prefix+'/'+name)\n   src.backup(dst);dst.close();src.close()\nwith tarfile.open(fileobj=sys.stdout.buffer,mode='w|') as archive:\n for prefix in ['banking-state','banking-demo-state']: archive.add(root+'/'+prefix,arcname=prefix)\nimport shutil;shutil.rmtree(root)\n`;
const bankArchive = await command('docker', ['exec', '-i', source, 'python3', '-c', backupScript]);
const bankArchivePath = path.join(output, 'bank-ledgers.tar');
await fs.writeFile(bankArchivePath, bankArchive);
await command('tar', ['-xf', bankArchivePath, '-C', stage]);
await fs.unlink(bankArchivePath);

// Only published silver/gold data; bronze downloads and unused builds stay local.
const dataset = path.join(project, 'data');
const current = (await fs.readFile(path.join(dataset, 'CURRENT'), 'utf8')).trim();
if (!/^[A-Za-z0-9_-]+$/.test(current)) throw new Error('Unsafe dataset build ID');
const snapshotTarget = path.join(stage, 'banking-data', 'builds', current);
await fs.mkdir(snapshotTarget, { recursive: true });
await fs.copyFile(path.join(dataset, 'CURRENT'), path.join(stage, 'banking-data', 'CURRENT'));
await fs.copyFile(path.join(dataset, 'builds', current, 'snapshot.json'), path.join(snapshotTarget, 'snapshot.json'));
await fs.copyFile(path.join(dataset, 'builds', current, 'source_objects.json'), path.join(snapshotTarget, 'source_objects.json'));
await fs.cp(path.join(dataset, 'builds', current, 'gold'), path.join(snapshotTarget, 'gold'), { recursive: true });
await fs.mkdir(path.join(snapshotTarget, 'silver'));
for (const filename of ['customers.parquet', 'products.parquet']) await fs.copyFile(path.join(dataset, 'builds', current, 'silver', filename), path.join(snapshotTarget, 'silver', filename));
await fs.cp(path.join(dataset, 'banking-demo'), path.join(stage, 'banking-data', 'banking-demo'), { recursive: true });

// Import SSH/Git credentials as private runtime files, with no repository clone.
await fs.mkdir(path.join(stage, 'private', 'github'), { recursive: true });
for (const filename of ['github-token', 'github-signing-key', 'github-allowed-signers']) {
  await fs.copyFile(path.resolve(project, '../flujo-slack-bot/.docker', filename), path.join(stage, 'private', 'github', filename));
}

const inspect = JSON.parse((await command('docker', ['inspect', source])).toString())[0];
if (inspect.Image !== 'sha256:a071761b46eed021471508f8de8b7d5726752125a3d19e66c4b286d59bde6d86') throw new Error('Source worker image changed; review its deployment identity before capture');
const workerEnvironment = Object.fromEntries(inspect.Config.Env.map(entry => { const index = entry.indexOf('='); return [entry.slice(0, index), entry.slice(index + 1)]; }));
const sourceSecrets = Object.fromEntries(['FLUJO_WORKER_SNAPSHOT_KEY', 'FLUJO_WORKER_SNAPSHOT_SHA256', 'FLUJO_SNAPSHOT_CONTROL_TOKEN'].map(name => [name, workerEnvironment[name]]));
if (Object.values(sourceSecrets).some(value => !value)) throw new Error('Worker bootstrap secrets missing');
let credentials;
try { credentials = JSON.parse(await fs.readFile(path.join(output, 'access.json'), 'utf8')); }
catch { credentials = { url: 'https://flujo-factored-2026.fly.dev', username: 'savia', password: randomBytes(32).toString('base64url'), demo_code: frontend.demo_code }; }
credentials.demo_code = frontend.demo_code;
await writePrivateJson(path.join(output, 'access.json'), credentials);
const secrets = { ...sourceSecrets, FLUJO_FLY_PASSWORD: credentials.password };
await writePrivateJson(path.join(output, 'fly-secrets.json'), secrets);
const receipt = { version: 1, workerImage: inspect.Image, dataset: current, migration: 'configuration-only', conversations: 0, userdata: 0 };
await fs.writeFile(path.join(stage, '.migration-complete.json'), JSON.stringify(receipt));
const archive = path.join(output, 'migration.tar.gz');
await command('tar', ['-czf', archive, '-C', stage, '.']);
const digest = createHash('sha256').update(await fs.readFile(archive)).digest('hex');
await writePrivateJson(path.join(output, 'migration-receipt.json'), { ...receipt, archiveSha256: digest, archiveBytes: (await fs.stat(archive)).size });
console.log(JSON.stringify({ archive, archiveSha256: digest, bytes: (await fs.stat(archive)).size, conversations: 0, userdata: 0 }));
