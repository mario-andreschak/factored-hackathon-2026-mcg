import path from 'node:path';
import fs from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { writePrivateJson } from '../../../flujo-cloud/lib/private-files.mjs';
const filename = path.join(process.env.USERPROFILE, '.flujo-fly', 'flujo-factored-2026', 'registry-token.json');
async function run(command, args, input) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
    const output = [];
    child.stdout.on('data', bytes => output.push(bytes));
    child.stderr.on('data', () => {});
    child.on('error', reject);
    child.on('close', code => code === 0 ? resolve(Buffer.concat(output).toString()) : reject(new Error('Private registry authentication failed')));
    child.stdin.end(input);
  });
}
let token;
try { ({ token } = JSON.parse(await fs.readFile(filename, 'utf8'))); } catch {}
if (!token) {
  const created = JSON.parse(await run('C:/Users/Moe/.fly/bin/flyctl.exe', ['tokens', 'create', 'deploy', '--app', 'flujo-factored-2026', '--name', 'docker-migration-upload', '--expiry', '2h', '--json']));
  token = created.token;
  if (typeof token !== 'string' || !token.startsWith('FlyV1 ')) throw new Error('Unexpected deploy token response');
  await writePrivateJson(filename, { token, expiresAfter: '2h' });
}
await run('docker', ['login', 'registry.fly.io', '--username', 'x', '--password-stdin'], token + '\n');
console.log('Authenticated Docker with a temporary app-scoped upload token.');
