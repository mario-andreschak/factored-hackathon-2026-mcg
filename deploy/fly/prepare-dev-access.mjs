import os from 'node:os';
import path from 'node:path';
import { randomBytes } from 'node:crypto';
import { spawn } from 'node:child_process';
import { readPrivateJson, writePrivateJson } from '../../../flujo-cloud/lib/private-files.mjs';

const app = 'flujo-factored-2026';
const filename = path.join(os.homedir(), '.flujo-fly', app, 'development-access.json');
const mainUrl = `https://${app}.fly.dev`;
const url = 'https://flujo-factored-dev-2026.fly.dev';
const expiresAt = '2026-10-16T05:00:00.000Z';
let access;
try { access = await readPrivateJson(filename); }
catch (error) {
  if (error.code !== 'ENOENT') throw error;
  access = { version: 2, app, url, login_url: `${url}/_dev/login`, main_url: mainUrl, expires_at: expiresAt, purpose: 'Temporary live-worker development access',
    accounts: ['mario', 'gloria'].map(username => ({ username, password: randomBytes(32).toString('base64url') })) };
  await writePrivateJson(filename, access, { exclusive: true });
}
if (access.app !== app || ![url, mainUrl, `${mainUrl}:8443`].includes(access.url) || access.accounts?.length !== 2) throw new Error('Unexpected development access record.');
const secrets = {};
for (const username of ['mario', 'gloria']) {
  const account = access.accounts.find(value => value.username === username);
  if (!account || !/^[A-Za-z0-9_-]{43}$/.test(account.password)) throw new Error('Unsafe development credential record.');
  secrets[`FLUJO_DEV_UI_${username.toUpperCase()}_PASSWORD`] = account.password;
}
if (access.url !== url || access.login_url !== `${url}/_dev/login` || access.expires_at !== expiresAt || access.alternate_url) {
  access.version = 2; access.url = url; access.login_url = `${url}/_dev/login`; access.main_url = mainUrl; access.expires_at = expiresAt;
  delete access.alternate_url;
  await writePrivateJson(filename, access);
}
console.log(JSON.stringify({ credentialsFile: filename, url: access.login_url, accounts: ['mario', 'gloria'], ownerPrivate: true }));
if (process.argv.includes('--stage')) {
  const executable = process.env.FLYCTL_PATH || path.join(os.homedir(), '.fly', 'bin', process.platform === 'win32' ? 'flyctl.exe' : 'flyctl');
  const child = spawn(executable, ['secrets', 'import', '--app', app, '--stage'],
    { windowsHide: true, stdio: ['pipe', 'inherit', 'inherit'] });
  child.stdin.end(Object.entries(secrets).map(([name, value]) => `${name}=${value}`).join('\n') + '\n');
  process.exitCode = await new Promise((resolve, reject) => { child.once('error', reject); child.once('exit', resolve); });
}
