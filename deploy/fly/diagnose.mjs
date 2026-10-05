import fs from 'node:fs/promises';
import path from 'node:path';
const access = JSON.parse(await fs.readFile(path.join(process.env.USERPROFILE, '.flujo-fly', 'flujo-factored-2026', 'access.json'), 'utf8'));
const response = await fetch(`${access.url}/healthz`, { headers: {
  Authorization: `Basic ${Buffer.from(`${access.username}:${access.password}`).toString('base64')}`,
}, signal: AbortSignal.timeout(10_000) });
const result = await response.json();
console.log(JSON.stringify({ httpStatus: response.status, datasetReady: result.dataset_ready, revocations: result.chat_revocations }));
