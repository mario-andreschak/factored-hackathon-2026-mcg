import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { writePrivateJson } from '../../../flujo-cloud/lib/private-files.mjs';

const auditName = process.argv[2] || 'dev-readiness';
if (!['readiness', 'dev-readiness'].includes(auditName)) throw new Error('Unknown read-only audit.');
const source = await fs.readFile(new URL(`./${auditName}.mjs`, import.meta.url), 'utf8');
const cli = path.join(os.homedir(), '.fly', 'bin', process.platform === 'win32' ? 'flyctl.exe' : 'flyctl');
const child = spawn(cli, ['ssh', 'console', '--app', 'flujo-factored-2026', '--machine', '683ddde5f044d8',
  '--user', 'root', '--quiet', '--command', '/usr/local/bin/node --input-type=module'],
  { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
let output = '';
child.stdout.on('data', bytes => {
  output += bytes.toString('utf8');
  if (output.length > 65536) child.kill();
});
child.stderr.resume();
child.stdin.on('error', () => {});
child.stdin.end(source);
await new Promise((resolve, reject) => { child.once('error', reject); child.once('close', resolve); });
const result = output.split(/\r?\n/).filter(line => /^\{.*\}$/.test(line)).map(line => JSON.parse(line)).at(-1);
if (!result || Object.values(result).some(value => typeof value !== 'boolean' && typeof value !== 'number')) {
  throw new Error('Fly SSH did not return a complete safe audit report.');
}
await writePrivateJson(path.join(os.homedir(), '.flujo-fly', 'flujo-factored-2026', `${auditName}-development.json`), result);
console.log(JSON.stringify(result));
if (!result.ready) process.exitCode = 1;
