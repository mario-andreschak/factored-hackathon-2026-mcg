#!/usr/bin/env node
// Export reviewed Git blobs only. This command never reads runtime/private files,
// creates containers, installs dependencies, uploads a context, or deploys Fly.
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { createHash } from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const execute = promisify(execFile);
export const FLUJO_REVISION = '0ba62296520a505e6d71eddf5aa650691f3dc311';
const FLUJO_TREE = 'c1e66af0a8ba9cf436a4f3a76b6b684fdd2ccb1d';
const NATIVE_SHA256 = '3e2584f3f3829a43a0495011a1cecb2facbe64a2403e2b682351fd9c2983f970';
const CATALOG_SHA256 = '5a1ddcef609e52bd057b247d9487f2c8c4d9453d3d802745ba5325c2e10700e0';
const APP_ROOTS = new Set(['.gitattributes', 'graph_config_v3.yaml', 'requirements-dispute.txt',
  'requirements-pipeline.txt', 'requirements-s3.txt', 'frontend/package.json', 'frontend/package-lock.json',
  'frontend/index.html', 'frontend/vite.config.ts', 'frontend/tsconfig.json', 'frontend/requirements.txt']);
const APP_PREFIXES = ['frontend/src/', 'frontend/public/', 'frontend/server/', 'banking_mcp/',
  'pipeline/', 'dispute_workflow/', 'resources/prompts/', 'resources/policies/', 'config/', 'contracts/', 'deploy/fly/'];
const APP_SCRIPTS = new Set(['scripts/run_dispute.py', 'scripts/native_dispute_qualification.py',
  'scripts/native_dispute_qualification.ts', 'scripts/native_dispute_qualification.mjs',
  'scripts/build_dispute_graph.mjs', 'scripts/provision_banking_runtime_policy.mjs',
  'scripts/native_dispute_capability_probe.mjs', 'scripts/native_dispute_bridge_loader.mjs',
  'scripts/native_dispute_compatibility_probe.mjs', 'scripts/native_dispute_revocation_probe.mjs']);
const FLUJO_ROOTS = new Set(['package.json', 'package-lock.json', 'next.config.mjs', 'next-env.d.ts',
  'tsconfig.json', 'tsconfig.build.json', 'postcss.config.mjs', 'eslint.config.mjs', 'LICENSE']);
const FLUJO_PREFIXES = ['src/', 'scripts/', 'mcp-servers/', 'public/', 'bin/'];
const REQUIRED_APP = [...APP_ROOTS, 'scripts/run_dispute.py', 'scripts/native_dispute_qualification.py',
  'deploy/fly/Dockerfile.joined', 'deploy/fly/entrypoint.sh', 'deploy/fly/runtime.mjs',
  'deploy/fly/gateway.mjs', 'deploy/fly/dev-gateway.mjs', 'deploy/fly/dev-traces.mjs',
  'deploy/fly/native-execution.mts', 'deploy/fly/native-codex-wrapper.mjs'];

const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const select = (name, roots, prefixes) => roots.has(name) || prefixes.some(prefix => name.startsWith(prefix));

async function git(repository, ...args) {
  return (await execute('git', ['-C', repository, ...args], { encoding: 'buffer',
    maxBuffer: 64 * 1024 * 1024, windowsHide: true })).stdout;
}

function safeName(name) {
  const parts = name.split('/');
  return name && !name.includes('\\') && !/[\x00-\x1f\x7f]/.test(name) && !path.posix.isAbsolute(name)
    && path.posix.normalize(name) === name
    && !parts.some(part => ['..', '.git', 'node_modules', '.next', 'private', 'data',
      '__pycache__', '.codex', '.overlay', '.artifacts'].includes(part) || part.startsWith('.env'))
    && !/\.(?:env|pem|key|p12|pfx|sqlite3?|db|duckdb|parquet|csv|log|zip|pdf)$/i.test(name);
}

async function collect(repository, revision, choose, required) {
  const output = (await git(repository, 'ls-tree', '-rz', revision)).toString('utf8');
  const entries = [];
  for (const line of output.split('\0').filter(Boolean)) {
    const match = /^(\d+) (\w+) ([a-f0-9]{40})\t([\s\S]+)$/.exec(line);
    if (!match) throw new Error('Invalid Git inventory.');
    const [, mode, kind, gitOid, name] = match;
    if (!choose(name)) continue;
    if (!safeName(name) || kind !== 'blob' || !['100644', '100755'].includes(mode)) {
      throw new Error(`Refusing nonregular or private build input: ${name}`);
    }
    entries.push({ path: name, mode, gitOid });
  }
  const names = new Set(entries.map(entry => entry.path));
  const missing = required.filter(name => !names.has(name));
  if (missing.length) throw new Error(`Required committed build inputs missing: ${missing.join(', ')}`);
  // Fetch by object ID, never by the worktree path. Batch to avoid one Git process
  // per file, while keeping the exported closure bounded in memory.
  const files = new Map();
  for (let offset = 0; offset < entries.length; offset += 24) {
    const batch = entries.slice(offset, offset + 24);
    const values = await Promise.all(batch.map(entry => git(repository, 'cat-file', 'blob', entry.gitOid)));
    batch.forEach((entry, index) => {
      const bytes = values[index];
      if (bytes.length > 16 * 1024 * 1024) throw new Error(`Oversized source asset: ${entry.path}`);
      files.set(entry.path, bytes);
      entry.bytes = bytes.length;
      entry.sha256 = hash(bytes);
    });
  }
  return { entries: entries.sort((a, b) => a.path.localeCompare(b.path)), files };
}

export async function prepareContext({ appRepository, appRevision, flujoRepository, catalogPath, output }) {
  if (!/^[a-f0-9]{40}$/.test(appRevision)) throw new Error('An exact full application revision is required.');
  appRepository = await fs.realpath(appRepository);
  flujoRepository = await fs.realpath(flujoRepository);
  if (!output) throw new Error('A new build output directory is required.');
  output = path.resolve(output);
  output = path.join(await fs.realpath(path.dirname(output)), path.basename(output));
  if (await fs.stat(output).then(() => true, error => error.code === 'ENOENT' ? false : Promise.reject(error))) {
    throw new Error('Build output must be a new directory; no existing files are replaced.');
  }
  for (const repository of [appRepository, flujoRepository]) {
    const relative = path.relative(repository, output);
    const outside = relative === '..' || relative.startsWith('..' + path.sep) || path.isAbsolute(relative);
    if (!relative || !outside) {
      throw new Error('Build output must be outside either source checkout.');
    }
  }
  if ((await git(appRepository, 'rev-parse', 'HEAD')).toString().trim() !== appRevision) {
    throw new Error('Application checkout must match the requested immutable revision.');
  }
  if ((await git(appRepository, 'status', '--porcelain', '--untracked-files=normal')).length) {
    throw new Error('Commit/review the isolated source before exporting; its checkout must be clean.');
  }
  const resolvedFlujo = (await git(flujoRepository, 'rev-parse', `${FLUJO_REVISION}^{commit}`)).toString().trim();
  const flujoTree = (await git(flujoRepository, 'rev-parse', `${FLUJO_REVISION}^{tree}`)).toString().trim();
  if (resolvedFlujo !== FLUJO_REVISION || flujoTree !== FLUJO_TREE) throw new Error('Permitted FLUJO pin/tree mismatch.');
  const [application, flujo] = await Promise.all([
    collect(appRepository, appRevision,
      name => select(name, APP_ROOTS, APP_PREFIXES) || APP_SCRIPTS.has(name), REQUIRED_APP),
    collect(flujoRepository, FLUJO_REVISION,
      name => select(name, FLUJO_ROOTS, FLUJO_PREFIXES), [...FLUJO_ROOTS]),
  ]);
  if (JSON.parse(flujo.files.get('package.json')).version !== '3.46.1') throw new Error('FLUJO version mismatch.');
  // The sole non-Git input is owner-approved public vendor model metadata. Its
  // immutable byte hash is known independently; no neighboring private file is
  // read or exported. The catalog's path is intentionally omitted from the image.
  const metadata = await fs.lstat(catalogPath);
  if (!metadata.isFile() || metadata.isSymbolicLink() || metadata.size > 512 * 1024) {
    throw new Error('Catalog must be a bounded regular file.');
  }
  const catalog = await fs.readFile(catalogPath);
  if (hash(catalog) !== CATALOG_SHA256) throw new Error('Approved vendor catalog hash mismatch.');
  const parsedCatalog = JSON.parse(catalog);
  if (Object.keys(parsedCatalog).sort().join(',') !== 'client_version,models' || !Array.isArray(parsedCatalog.models)) {
    throw new Error('Vendor catalog schema mismatch.');
  }
  function denyCredentialFields(value) {
    if (!value || typeof value !== 'object') return;
    for (const [name, item] of Object.entries(value)) {
      if (/^(?:authorization|api[_-]?key|password|secret|credentials?|access[_-]?token|refresh[_-]?token)$/i.test(name)) {
        throw new Error('Vendor catalog contains a credential field.');
      }
      denyCredentialFields(item);
    }
  }
  denyCredentialFields(parsedCatalog);
  const appTree = (await git(appRepository, 'rev-parse', `${appRevision}^{tree}`)).toString().trim();
  const manifest = {
    schema: 'savia-fly-joined-build-context/v1', application_revision: appRevision, application_tree: appTree,
    flujo_revision: FLUJO_REVISION, flujo_tree: FLUJO_TREE, flujo_application_version: '3.46.1',
    dependency_install: { flujo: 'npm ci --include=dev', frontend: 'npm ci',
      python: 'requirements-dispute.txt followed by pip check; resolved freeze retained in image' },
    source_export: 'Exact committed Git blobs; no runtime, private or working-tree inputs',
    native_binary: { version: '0.157.1', sha256: NATIVE_SHA256, path: '/opt/native/codex.raw',
      supplied_by: 'registry.fly.io/flujo-factored-2026@sha256:78c3bf0bf4d090ca7db86b79e03ac8605b17b22a12807e465334df9ecac5746d' },
    native_catalog_sha256: hash(catalog),
    native_catalog_origin: 'Owner-approved public vendor model metadata; exact separately pinned byte hash',
    credential_files: 0,
    application_files: Object.fromEntries(application.entries.map(entry => [entry.path, entry.sha256])),
    flujo_files: Object.fromEntries(flujo.entries.map(entry => [entry.path, entry.sha256])),
    files: { application: application.entries, flujo: flujo.entries },
    image_built: false, deployed: false,
  };
  await fs.mkdir(output, { recursive: false });
  for (const [directory, inventory] of [['application', application], ['flujo', flujo]]) {
    for (const entry of inventory.entries) {
      const target = path.join(output, directory, ...entry.path.split('/'));
      await fs.mkdir(path.dirname(target), { recursive: true });
      await fs.writeFile(target, inventory.files.get(entry.path), { flag: 'wx', mode: entry.mode === '100755' ? 0o755 : 0o644 });
    }
  }
  const manifestBytes = Buffer.from(JSON.stringify(manifest, null, 2) + '\n');
  await fs.writeFile(path.join(output, 'source-manifest.json'), manifestBytes, { flag: 'wx' });
  await fs.mkdir(path.join(output, 'native'));
  await fs.writeFile(path.join(output, 'native', 'model-catalog.json'), catalog, { flag: 'wx' });
  await fs.writeFile(path.join(output, 'Dockerfile'), application.files.get('deploy/fly/Dockerfile.joined'), { flag: 'wx' });
  await fs.writeFile(path.join(output, '.dockerignore'), '**\n!Dockerfile\n!source-manifest.json\n!application\n!application/**\n!flujo\n!flujo/**\n!native\n!native/model-catalog.json\n', { flag: 'wx' });
  return { prepared: true, output, applicationRevision: appRevision, flujoRevision: FLUJO_REVISION,
    applicationFiles: application.entries.length, flujoFiles: flujo.entries.length,
    sourceManifestSha256: hash(manifestBytes), imageBuilt: false, deployed: false,
    buildArgs: { APPLICATION_REVISION: appRevision } };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  const options = {};
  for (let index = 2; index < process.argv.length; index += 2) {
    const name = process.argv[index], value = process.argv[index + 1];
    if (!['--app-repo', '--head', '--flujo-repo', '--catalog', '--out'].includes(name) || !value || name in options) {
      throw new Error('Usage: node build-joined-context.mjs --app-repo PATH --head FULL_SHA --flujo-repo PATH --catalog APPROVED_VENDOR_CATALOG --out NEW_DIRECTORY');
    }
    options[name] = value;
  }
  prepareContext({ appRepository: options['--app-repo'] ?? process.cwd(), appRevision: options['--head'] ?? '',
    flujoRepository: options['--flujo-repo'] ?? '', catalogPath: options['--catalog'] ?? '', output: options['--out'] ?? '' })
    .then(result => console.log(JSON.stringify(result)))
    .catch(error => { console.error(error.message); process.exitCode = 1; });
}
