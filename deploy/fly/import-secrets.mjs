import fs from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';
const filename = path.join(process.env.USERPROFILE, '.flujo-fly', 'flujo-factored-2026', 'fly-secrets.json');
const secrets = JSON.parse(await fs.readFile(filename, 'utf8'));
for (const [name, value] of Object.entries(secrets)) {
  if (!/^[A-Z][A-Z0-9_]*$/.test(name) || typeof value !== 'string' || /[\r\n]/.test(value)) throw new Error('Invalid secret format');
}
const child = spawn('C:/Users/Moe/.fly/bin/flyctl.exe', ['secrets', 'import', '--app', 'flujo-factored-2026', '--stage'],
  { windowsHide: true, stdio: ['pipe', 'inherit', 'inherit'] });
child.stdin.end(Object.entries(secrets).map(([name, value]) => `${name}=${value}`).join('\n') + '\n');
child.once('exit', code => { process.exitCode = code; });
