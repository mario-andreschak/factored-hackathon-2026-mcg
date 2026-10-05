// Private correlation only: no HTTP/provider calls and no ledger mutations.
import { execFile } from 'node:child_process';
import { createHash } from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { promisify } from 'node:util';
import { writePrivateJson } from '../../../flujo-cloud/lib/private-files.mjs';

const execute = promisify(execFile);
const cli = 'C:/Users/Moe/.fly/bin/flyctl.exe';
const app = 'flujo-factored-2026';
const machine = process.argv[2];
if (!/^[a-f0-9]{14}$/.test(machine ?? '')) throw new Error('Pass the production Machine ID');
const directory = path.join(process.env.USERPROFILE, '.flujo-fly', app);
const receiptFile = path.join(directory, 'verification-session.json');
const bindingFile = path.join(directory, 'verification-ledger-binding.json');
const localScript = path.join(import.meta.dirname, 'verify-ledger.py');

async function fly(args, allowSafeReport = false) {
  try {
    return (await execute(cli, args, { windowsHide: true, maxBuffer: 1024 * 1024 })).stdout;
  } catch (error) {
    if (allowSafeReport && typeof error.stdout === 'string') return error.stdout;
    throw new Error('Private ledger SSH/SFTP operation failed');
  }
}

function resultFrom(output) {
  const result = output.split(/\r?\n/).filter(line => /^\{.*\}$/.test(line)).map(line => JSON.parse(line)).at(-1);
  if (!result || Object.values(result).some(value => typeof value !== 'boolean' && typeof value !== 'number')) {
    throw new Error('Private ledger returned an invalid safe report');
  }
  return result;
}

async function main() {
  if (process.argv.includes('--check')) {
    const binding = JSON.parse(await fs.readFile(bindingFile, 'utf8'));
    const receipt = JSON.parse(await fs.readFile(receiptFile, 'utf8'));
    if (binding.runId !== receipt.runId || binding.machine !== machine
        || !/^\/tmp\/savia-verification-[a-f0-9]{16}-session\.json$/.test(binding.receipt)
        || !/^\/tmp\/savia-verification-[a-f0-9]{16}-binding\.json$/.test(binding.binding)
        || !/^\/tmp\/savia-verification-[a-f0-9]{16}-audit\.py$/.test(binding.script)) {
      throw new Error('Private ledger binding does not match the verification run');
    }
    const output = await fly(['ssh', 'console', '--app', app, '--machine', machine, '--user', 'root', '--quiet',
      '--command', `python3 ${binding.script} check --receipt ${binding.receipt} --binding ${binding.binding}`], true);
    const result = resultFrom(output);
    await writePrivateJson(path.join(directory, 'verification-ledger-result.json'), result);
    console.log(JSON.stringify(result));
    if (!result.auditPassed) process.exitCode = 1;
    return;
  }

  const deadline = Date.now() + 90_000;
  let receipt;
  while (Date.now() < deadline) {
    try {
      const value = JSON.parse(await fs.readFile(receiptFile, 'utf8'));
      if (value.phase === 'awaiting-ledger' && value.version === 1
          && /^[a-f0-9-]{36}$/.test(value.runId) && /^[a-f0-9]{64}$/.test(value.bankSessionTokenHash)) {
        receipt = value;
        break;
      }
    } catch {}
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  if (!receipt) throw new Error('No verification run is awaiting its private ledger binding');
  const suffix = createHash('sha256').update(receipt.runId).digest('hex').slice(0, 16);
  const frozen = path.join(directory, 'verification-session-for-ledger.json');
  const remoteReceipt = `/tmp/savia-verification-${suffix}-session.json`;
  const remoteBinding = `/tmp/savia-verification-${suffix}-binding.json`;
  const script = `/tmp/savia-verification-${suffix}-audit.py`;
  await writePrivateJson(frozen, receipt);
  await fly(['ssh', 'sftp', 'put', localScript, script, '--app', app, '--machine', machine, '--mode', '0600', '--quiet']);
  await fly(['ssh', 'sftp', 'put', frozen, remoteReceipt, '--app', app, '--machine', machine, '--mode', '0600', '--quiet']);
  const command = `chmod 0600 ${script} ${remoteReceipt} && python3 ${script} bind --receipt ${remoteReceipt} --binding ${remoteBinding}`;
  const output = await fly(['ssh', 'console', '--app', app, '--machine', machine, '--user', 'root', '--quiet',
    '--command', `sh -c '${command}'`], true);
  const result = resultFrom(output);
  if (!result.bindingSaved) throw new Error('The exact verification session was not bound');
  const current = JSON.parse(await fs.readFile(receiptFile, 'utf8'));
  if (current.runId !== receipt.runId || current.phase !== 'awaiting-ledger') {
    throw new Error('Verification changed before the private binding acknowledgement');
  }
  await writePrivateJson(bindingFile, { runId: receipt.runId, machine, script, receipt: remoteReceipt, binding: remoteBinding });
  await writePrivateJson(path.join(directory, 'verification-ledger-bound.json'), { runId: receipt.runId, bound: true });
  console.log(JSON.stringify({ ...result, ledgerBindingAcknowledged: true }));
}

main().catch(() => {
  console.log(JSON.stringify({ ledgerOperationCompleted: false, ledgerBindingAcknowledged: false }));
  process.exitCode = 1;
});
