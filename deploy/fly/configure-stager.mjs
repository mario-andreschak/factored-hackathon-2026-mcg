import fs from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { writePrivateJson } from '../../../flujo-cloud/lib/private-files.mjs';
const cli = 'C:/Users/Moe/.fly/bin/flyctl.exe';
const machineId = process.argv[2];
if (!/^[a-f0-9]{14}$/.test(machineId ?? '')) throw new Error('Pass the temporary Alpine staging machine ID');
const privateDirectory = path.join(process.env.USERPROFILE, '.flujo-fly', 'flujo-factored-2026');
const receipt = JSON.parse(await fs.readFile(path.join(privateDirectory, 'migration-receipt.json'), 'utf8'));
if (!/^[a-f0-9]{64}$/.test(receipt.archiveSha256) || !Number.isSafeInteger(receipt.archiveBytes) || receipt.archiveBytes < 1) throw new Error('Invalid migration receipt');
function run(args) {
  return new Promise((resolve, reject) => {
    const child = spawn(cli, args, { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
    const output = [];
    child.stdout.on('data', bytes => output.push(bytes));
    child.stderr.on('data', bytes => process.stderr.write(bytes));
    child.once('exit', code => code === 0 ? resolve(Buffer.concat(output).toString()) : reject(new Error('Stager configuration failed')));
  });
}
const machines = JSON.parse(await run(['machine', 'list', '--app', 'flujo-factored-2026', '--json']));
const machine = machines.find(entry => entry.id === machineId);
if (machines.length !== 1 || !machine?.config?.image?.startsWith('docker-hub-mirror.fly.io/library/alpine:3.22@sha256:')) throw new Error('Staging requires one temporary Alpine machine; refusing production changes');
const config = machine.config;
config.init = { exec: ['/bin/sh', '-c', 'apk add --no-cache python3 >/dev/null && exec python3 /data/upload-server.py'] };
config.metadata = { fly_platform_version: 'v2', fly_process_group: 'app' };
config.env = { FLUJO_UPLOAD_SHA256: receipt.archiveSha256, FLUJO_UPLOAD_BYTES: String(receipt.archiveBytes) };
config.services = [{ protocol: 'tcp', internal_port: 8080, ports: [{ port: 443, handlers: ['tls', 'http'], http_options: { idle_timeout: 600 } }] }];
const filename = path.join(privateDirectory, 'stager-machine.json');
await writePrivateJson(filename, config);
console.log(await run(['machine', 'update', machineId, '--app', 'flujo-factored-2026', '--machine-config', filename, '--yes', '--detach']));
console.log(await run(['secrets', 'deploy', '--app', 'flujo-factored-2026', '--detach']));
