#!/usr/bin/env node
/** Export committed public application source, never a working directory or secrets. */
import { execFileSync } from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';

const [destination, ref = 'HEAD'] = process.argv.slice(2);
if (!destination) throw Error('Destination directory required.');
const revision = execFileSync('git', ['rev-parse', ref + '^{commit}'], { encoding: 'utf8' }).trim();
if (!/^[a-f0-9]{40}$/.test(revision)) throw Error('Committed source revision required.');
const prefixes = ['banking_mcp/', 'dispute_workflow/', 'pipeline/', 'frontend/server/',
  'resources/', 'contracts/', 'config/', 'deploy/local-dispute/'];
const fixed = new Set(['requirements-dispute.txt', 'requirements-pipeline.txt', 'frontend/requirements.txt',
  'scripts/run_dispute.py', 'scripts/local_dispute_demo.py', 'scripts/qualify_dispute_app.py',
  'scripts/native_dispute_qualification.py', 'scripts/native_dispute_qualification.ts',
  'scripts/native_dispute_qualification.mjs', 'frontend/server/deployment_transition.py',
  'deploy/fly/runtime.mjs']);
const files = execFileSync('git', ['ls-tree', '-r', '--name-only', revision], { encoding: 'utf8' })
  .trim().split('\n').filter(name => fixed.has(name) || prefixes.some(prefix => name.startsWith(prefix)));
if (!files.includes('scripts/local_dispute_demo.py')) throw Error('Commit the local launcher before exporting.');
const root = path.resolve(destination), hashes = {};
await fs.mkdir(root, { recursive: true });
for (const name of files) {
  if (name.includes('\\') || name.split('/').some(part => !part || part === '.' || part === '..')) throw Error('Unsafe source path.');
  const filename = path.resolve(root, name);
  if (!filename.startsWith(root + path.sep)) throw Error('Source path escaped destination.');
  const bytes = execFileSync('git', ['show', revision + ':' + name], { maxBuffer: 16 * 1024 * 1024 });
  hashes[name] = createHash('sha256').update(bytes).digest('hex');
  await fs.mkdir(path.dirname(filename), { recursive: true });
  try { await fs.writeFile(filename, bytes, { flag: 'wx' }); }
  catch (error) {
    if (error.code !== 'EEXIST' || createHash('sha256').update(await fs.readFile(filename)).digest('hex') !== hashes[name]) throw error;
  }
}
const manifest = { schema: 'local-dispute-source/v1', revision, files: hashes,
  scope: 'committed application overlay; native worker and UI assets remain identified by image digest' };
const encoded = JSON.stringify(manifest, null, 2) + '\n';
try { await fs.writeFile(path.join(root, 'local-source-manifest.json'), encoded, { flag: 'wx' }); }
catch (error) { if (error.code !== 'EEXIST' || await fs.readFile(path.join(root, 'local-source-manifest.json'), 'utf8') !== encoded) throw error; }
console.log(JSON.stringify({ revision, fileCount: files.length, destination: root }));
