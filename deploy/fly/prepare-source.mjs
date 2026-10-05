#!/usr/bin/env node
// Export only pinned immutable builder inputs. No live worktree or secrets.
import { spawn, execFile } from 'node:child_process';
import { createHash } from 'node:crypto';
import { createReadStream, createWriteStream } from 'node:fs';
import fs from 'node:fs/promises';
import path from 'node:path';
import { pipeline } from 'node:stream/promises';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';

const execute = promisify(execFile);
const directory = path.dirname(fileURLToPath(import.meta.url));
const repository = path.resolve(directory, '../../../FLUJO');
const revision = '153a039185b1d303fb0853f1d4935980388a1903';
const builder = 'sha256:965b248df034fc2bf238df1d1b8468fc401f9bb8004a2e2dbfa9e24aaf7cad26';
const originalPatch = path.resolve(directory, '../../../flujo-slack-bot/.docker/turn-provenance/worker-source.patch');
const patchSha256 = 'df9b3ecae46c2f9c1032d0bfa817fdfb7c24a6724ee7e6364cf8e7503d5e21e5';
const destination = path.join(directory, '.overlay', 'compile');
const inputs = ['src', 'public', 'scripts', 'mcp-servers', 'package.json', 'package-lock.json',
  'next.config.mjs', 'next-env.d.ts', 'tsconfig.json', 'tsconfig.build.json', 'postcss.config.mjs'];

async function git(args, binary = false) {
  return (await execute('git', ['-C', repository, ...args], {
    encoding: binary ? 'buffer' : 'utf8', maxBuffer: 64 * 1024 * 1024, windowsHide: true,
  })).stdout;
}

async function main() {
  if ((await git(['rev-parse', `${revision}^{commit}`])).trim() !== revision) throw new Error('Pinned source commit unavailable.');
  const tracked = (await git(['ls-tree', '-r', revision, '--', ...inputs])).trim().split('\n');
  if (tracked.some(line => !/^100(?:644|755) blob [a-f0-9]{40}\t/.test(line))) throw new Error('Compile source contains a nonregular tracked input.');
  const inventoryCode = String.raw`const fs=require('fs'),path=require('path'),crypto=require('crypto');const entries=[];function walk(p){const s=fs.lstatSync(p);if(s.isDirectory()){for(const n of fs.readdirSync(p).sort())if(!['node_modules','dist'].includes(n))walk(path.join(p,n));return;}if(!s.isFile())throw Error('Nonregular compile source input');const b=fs.readFileSync(p),normalized=Buffer.from(b.toString().replaceAll('\r\n','\n'));entries.push({path:p.slice(5),sha256:crypto.createHash('sha256').update(b).digest('hex'),gitBlob:crypto.createHash('sha1').update('blob '+normalized.length+'\0').update(normalized).digest('hex')});}for(const p of JSON.parse(process.argv[1]))walk('/app/'+p);console.log(JSON.stringify(entries));`;
  const observed = JSON.parse((await execute('docker', ['run', '--rm', '--read-only', '--network', 'none', '--entrypoint', 'node', builder, '-e', inventoryCode, JSON.stringify(inputs)], { maxBuffer: 16 * 1024 * 1024, windowsHide: true })).stdout);
  const committed = new Map(tracked.map(line => { const match=/^[0-9]+ blob ([a-f0-9]{40})\t(.+)$/.exec(line);return[match[2],match[1]]; }));
  const sourceDifferences = observed.filter(entry => committed.get(entry.path) !== entry.gitBlob).map(({ path: filename, sha256 }) => ({ path: filename, sha256 }));
  const hashes = {};
  for (const name of ['package.json', 'package-lock.json', 'next.config.mjs']) {
    const content = (await execute('docker', ['run', '--rm', '--read-only', '--network', 'none', '--entrypoint', 'cat', builder, '/app/' + name], { encoding: 'buffer', maxBuffer: 8 * 1024 * 1024, windowsHide: true })).stdout;
    const original = await fs.readFile(path.join(directory, '.overlay', 'app', name));
    if (!content.equals(original)) throw new Error(`Immutable builder ${name} differs from the existing runtime image.`);
    hashes[name] = createHash('sha256').update(content).digest('hex');
  }
  const patch = await fs.readFile(originalPatch);
  if (createHash('sha256').update(patch).digest('hex') !== patchSha256) throw new Error('Original turn-provenance patch digest mismatch.');
  await fs.mkdir(destination, { recursive: true });
  await fs.writeFile(path.join(destination, 'turn-provenance.patch'), patch);
  const hotfixFiles = ['src/app/v1/chat/conversations/[conversationId]/route.ts',
    'src/backend/execution/flow/conversationLog.ts', 'src/backend/execution/flow/runFlow.ts',
    'src/shared/types/chat.ts', 'src/shared/types/execution/events.ts'];
  const frozenSource = path.join(path.dirname(originalPatch), 'source');
  const originalTurnProvenanceSourceFiles = [];
  for (const filename of hotfixFiles) {
    const bytes = await fs.readFile(path.join(frozenSource, filename));
    originalTurnProvenanceSourceFiles.push({path: filename, sha256: createHash('sha256').update(bytes).digest('hex')});
  }
  await execute('tar', ['-cf', path.join(destination, 'turn-provenance.tar'), '-C', frozenSource, ...hotfixFiles], { windowsHide: true });
  const filename = path.join(destination, 'source.tar');
  const pending = filename + '.pending';
  const child = spawn('docker', ['run', '--rm', '--read-only', '--network', 'none', '--entrypoint', 'tar', builder,
    '--exclude=node_modules', '--exclude=dist', '-C', '/app', '-cf', '-', ...inputs], {
    windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
  });
  const completed = new Promise((resolve, reject) => {
    child.once('error', reject);
    child.once('close', code => code === 0 ? resolve() : reject(new Error('Pinned immutable builder source archive failed.')));
  });
  // Drain diagnostic stderr without printing source or environment data.
  child.stderr.resume();
  await Promise.all([pipeline(child.stdout, createWriteStream(pending)), completed]);
  await fs.rename(pending, filename);
  const digest = createHash('sha256');
  for await (const chunk of createReadStream(filename)) digest.update(chunk);
  const receipt = { version: 1, revision, revisionRole: 'comparison reference only; immutable builder is authoritative',
    sourceBuilderImage: builder, originalTurnProvenancePatchSha256: patchSha256, originalTurnProvenanceSourceFiles,
    adapter: 'src/integrations/hackathon-banking/configuredAdapter.ts',
    inputs, fileCount: observed.length, sourceArchiveSha256: digest.digest('hex'), runtimeInputHashes: hashes,
    sourceFiles: observed.map(({path: filename, sha256}) => ({path: filename,sha256})),
    comparisonToGit: { revision, matchingFiles: observed.length - sourceDifferences.length, differences: sourceDifferences },
    preservedRuntimeImage: 'registry.fly.io/flujo-factored-2026@sha256:fd81d2931c1031b25387b28473e7578165a3c9276d33af467198f41484bfc89d' };
  await fs.writeFile(path.join(destination, 'source-manifest.json'), JSON.stringify(receipt, null, 2) + '\n');
  console.log(JSON.stringify({ prepared: true, revision, sourceBuilderImage: builder, fileCount: observed.length,
    archiveBytes: (await fs.stat(filename)).size, sourceArchiveSha256: receipt.sourceArchiveSha256,
    runtimeInputsIdentical: true, gitSourceDifferenceCount: sourceDifferences.length,
    originalTurnProvenancePatchSha256: patchSha256 }));
}

main().catch(error => { console.error(error.message); process.exitCode = 1; });
