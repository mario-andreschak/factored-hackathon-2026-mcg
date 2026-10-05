// Read-only root audit through Fly SSH stdin. Outputs only booleans/counts.
import fs from 'node:fs/promises';
import { createHash } from 'node:crypto';

try {
  const counts = { worker: 0, frontend: 0, main: 0, development: 0 };
  let separated = true, nonRoot = true;
  for (const pid of (await fs.readdir('/proc')).filter(value => /^\d+$/.test(value))) {
    try {
      const args = (await fs.readFile(`/proc/${pid}/cmdline`, 'utf8')).split('\0');
      const service = args.includes('scripts/launch-next.mjs') ? 'worker' : args.includes('uvicorn') ? 'frontend'
        : args.includes('/opt/savia/fly/gateway.mjs') ? 'main' : args.includes('/opt/savia/fly/dev-gateway.mjs') ? 'development' : null;
      if (!service) continue;
      counts[service]++;
      const variables = Object.fromEntries((await fs.readFile(`/proc/${pid}/environ`, 'utf8')).split('\0')
        .filter(Boolean).map(value => { const index = value.indexOf('='); return [value.slice(0, index), value.slice(index + 1)]; }));
      const names = new Set(Object.keys(variables));
      const metadata = await fs.readFile(`/proc/${pid}/status`, 'utf8');
      nonRoot &&= /^Uid:\s+1000\s+1000\s+1000\s+1000$/m.test(metadata);
      if (service !== 'development') separated &&= ![...names].some(name => name.startsWith('FLUJO_DEV_UI_')) && !names.has('FLUJO_FLY_DEV_UI_ENABLED');
      else {
        separated &&= names.has('FLUJO_DEV_UI_MARIO_PASSWORD') && names.has('FLUJO_DEV_UI_GLORIA_PASSWORD')
          && variables.FLUJO_DEV_UI_HOST === 'flujo-factored-dev-2026.fly.dev'
          && variables.FLUJO_DEV_UI_EXPIRES_AT === '2026-10-16T05:00:00.000Z'
          && !names.has('FLUJO_DEV_UI_SAME_ORIGIN') && !names.has('FLUJO_FLY_MAIN_HOST')
          && !names.has('FLUJO_FLY_PASSWORD') && !names.has('FLUJO_WORKER_SNAPSHOT_KEY')
          && !names.has('FLUJO_WORKER_SNAPSHOT_SHA256') && !names.has('FLUJO_BANKING_CONFIG');
      }
    } catch (error) { if (!['ENOENT', 'ESRCH'].includes(error.code)) throw error; }
  }
  const provenance = JSON.parse(await fs.readFile('/opt/savia/fly/dev-ui-provenance.json', 'utf8'));
  const sha = async filename => createHash('sha256').update(await fs.readFile(filename)).digest('hex');
  const result = {
    workerProcesses: counts.worker, frontendProcesses: counts.frontend, mainGatewayProcesses: counts.main,
    developmentGatewayProcesses: counts.development, childCredentialSeparation: separated,
    allServicesNonRoot: nonRoot,
    mainGatewayMatchesDevImage: await sha('/opt/savia/fly/gateway.mjs') === provenance.mainGatewaySha256,
    qualifiedBrowserLoginBasePreserved: provenance.qualifiedBaseMainGatewaySha256 === 'a384a2728c1727908e0f32214c354debf7bf1c377621c8138a064c8ddb76395b',
    qualifiedCompiledManifestUnchanged: await sha('/opt/savia/fly/artifact-manifest.json') === provenance.inheritedArtifactManifestSha256,
    runtimeMatchesDevImage: await sha('/opt/savia/fly/runtime.mjs') === provenance.runtimeSha256,
    devGatewayMatchesImage: await sha('/opt/savia/fly/dev-gateway.mjs') === provenance.devGatewaySha256,
    devTraceAdapterMatchesImage: await sha('/opt/savia/fly/dev-traces.mjs') === provenance.devTracesSha256,
    developmentPrivateIpv6Listener: (await fs.readFile('/proc/net/tcp6', 'utf8')).split('\n')
      .some(line => line.trim().split(/\s+/)[1]?.toUpperCase() === '00000000000000000000000000000000:1F91' && line.trim().split(/\s+/)[3] === '0A'),
  };
  result.ready = Object.values(counts).every(value => value === 1) && Object.values(result).every(value => typeof value === 'number' || value === true);
  console.log(JSON.stringify(result));
  if (!result.ready) process.exitCode = 1;
} catch {
  console.log(JSON.stringify({ ready: false, auditFailed: true }));
  process.exitCode = 1;
}
