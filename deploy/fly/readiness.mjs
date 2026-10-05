// Read-only restart audit. Run through root Fly SSH stdin; output is restricted
// to counts and booleans. Tokens, configuration bodies and identities stay local.
import fs from 'node:fs/promises';
import { createHash } from 'node:crypto';

async function listeningAddresses(port) {
  const addresses = [];
  for (const filename of ['/proc/net/tcp', '/proc/net/tcp6']) {
    const content = await fs.readFile(filename, 'utf8');
    for (const line of content.trim().split('\n').slice(1)) {
      const fields = line.trim().split(/\s+/);
      const [address, hexPort] = fields[1].split(':');
      if (fields[3] === '0A' && Number.parseInt(hexPort, 16) === port) addresses.push(address);
    }
  }
  return addresses;
}

async function childCredentialSeparation() {
  let workerProcesses = 0;
  let frontendProcesses = 0;
  let separated = true;
  for (const pid of (await fs.readdir('/proc')).filter(value => /^\d+$/.test(value))) {
    try {
      const args = (await fs.readFile(`/proc/${pid}/cmdline`, 'utf8')).split('\0');
      const worker = args.includes('scripts/launch-next.mjs');
      const frontend = args.includes('uvicorn');
      if (!worker && !frontend) continue;
      if (worker) workerProcesses++;
      if (frontend) frontendProcesses++;
      const names = new Set((await fs.readFile(`/proc/${pid}/environ`, 'utf8'))
        .split('\0').map(value => value.split('=', 1)[0]));
      if (names.has('FLUJO_FLY_PASSWORD')) separated = false;
      if (frontend && [...names].some(value => value.startsWith('FLUJO_WORKER_')
        || value === 'FLUJO_SNAPSHOT_CONTROL_TOKEN' || value === 'FLUJO_BANKING_CONFIG')) separated = false;
    } catch (error) {
      // A child can exit between proc directory enumeration and the read.
      if (error.code !== 'ENOENT' && error.code !== 'ESRCH') throw error;
    }
  }
  return { workerProcesses, frontendProcesses,
    childCredentialsSeparated: separated && workerProcesses === 1 && frontendProcesses === 1 };
}

async function audit() {
  const token = process.env.FLUJO_SNAPSHOT_CONTROL_TOKEN;
  if (!token) {
    console.log(JSON.stringify({ ready: false, controlTokenConfigured: false }));
    process.exitCode = 1;
    return;
  }
  const response = await fetch('http://127.0.0.1:4200/api/worker/status', {
    headers: { authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(5000),
  });
  const status = response.ok ? await response.json() : null;
  const servers = Array.isArray(status?.servers) ? status.servers : [];
  const expected = new Set(['bash', 'browser', 'brave-search-mcp-server', 'mcp-slack-com',
    'Banking MCP Demo', 'Banking MCP', 'Banking MCP Operator', 'FLUJO']);
  const total = servers.length;
  const connected = servers.filter(value => value.status === 'ready').length;
  const connecting = servers.filter(value => value.status === 'connecting' || value.status === 'starting').length;
  const [workerAddresses, frontendAddresses, credentials, policy, policyBytes] = await Promise.all([
    listeningAddresses(4200), listeningAddresses(8082), childCredentialSeparation(),
    fs.lstat('/run/banking-runtime/policy.json'), fs.readFile('/run/banking-runtime/policy.json'),
  ]);
  const loopback = addresses => addresses.length > 0 && addresses.every(value => value === '0100007F');
  const result = {
    workerHttpStatus: response.status,
    workerReady: status?.mode === 'worker' && status.state === 'ready',
    mcpServersTotal: total,
    mcpServersConnected: connected,
    mcpServersConnecting: connecting,
    expectedMcpServersPresent: total === expected.size && new Set(servers.map(value => value.name)).size === expected.size
      && servers.every(value => expected.has(value.name)),
    workerLoopbackOnly: loopback(workerAddresses),
    frontendLoopbackOnly: loopback(frontendAddresses),
    approvedPolicyPermissions: policy.isFile() && !policy.isSymbolicLink()
      && policy.uid === 0 && policy.gid === 1000 && (policy.mode & 0o777) === 0o440,
    approvedPolicyDigest: createHash('sha256').update(policyBytes).digest('hex') === process.env.FLUJO_FLY_POLICY_SHA256,
    ...credentials,
  };
  result.ready = response.ok && result.workerReady && total === 8 && connected === 8 && connecting === 0
    && result.expectedMcpServersPresent && result.workerLoopbackOnly && result.frontendLoopbackOnly
    && result.approvedPolicyPermissions && result.approvedPolicyDigest && result.childCredentialsSeparated;
  console.log(JSON.stringify(result));
  if (!result.ready) process.exitCode = 1;
}

audit().catch(() => {
  console.log(JSON.stringify({ ready: false, auditFailed: true }));
  process.exitCode = 1;
});
