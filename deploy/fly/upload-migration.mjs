import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
const directory = path.join(process.env.USERPROFILE, '.flujo-fly', 'flujo-factored-2026');
const access = JSON.parse(await fsp.readFile(path.join(directory, 'access.json'), 'utf8'));
const receipt = JSON.parse(await fsp.readFile(path.join(directory, 'migration-receipt.json'), 'utf8'));
const response = await fetch(`${access.url}/_migration`, {
  method: 'PUT', duplex: 'half', headers: { Authorization: `Bearer ${access.password}`, 'Content-Length': String(receipt.archiveBytes) },
  body: fs.createReadStream(path.join(directory, 'migration.tar.gz')),
  signal: AbortSignal.timeout(30 * 60_000),
});
if (!response.ok) throw new Error(`Private migration upload failed (${response.status})`);
const result = await response.json();
if (result.sha256 !== receipt.archiveSha256 || result.bytes !== receipt.archiveBytes) throw new Error('Stored migration receipt mismatch');
console.log(JSON.stringify(result));
