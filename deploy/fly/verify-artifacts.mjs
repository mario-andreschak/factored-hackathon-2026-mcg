#!/usr/bin/env node
// Read-only production verification. Prints hashes, versions and paths only;
// does not read /data, /run, environment credentials, or application APIs.
import { execFile } from 'node:child_process';
import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { pathToFileURL } from 'node:url';
import { promisify } from 'node:util';

const execute = promisify(execFile);
const workerRoots = [
  '/app/.next', '/app/scripts', '/app/mcp-servers', '/app/github', '/app/public',
  '/app/node_modules/jose', '/app/node_modules/canonicalize',
  '/opt/banking-mcp/banking_mcp', '/opt/banking-mcp/pipeline', '/opt/banking-mcp/scripts',
];
const workerFiles = [
  '/app/package.json', '/app/package-lock.json', '/app/next.config.mjs',
  '/opt/banking-mcp/requirements-mcp.txt', '/opt/banking-mcp/requirements-pipeline.txt', '/opt/banking-mcp/requirements-s3.txt',
];
const frontendRoots = ['/opt/savia/server', '/opt/savia/dist'];
const frontendDependencies = [
  ['annotated-doc', '0.0.5'], ['annotated-types', '0.8.0'], ['anyio', '4.15.1'], ['certifi', '2026.7.22'],
  ['cffi', '2.1.1'], ['click', '8.5.0'], ['cryptography', '46.0.7'], ['duckdb', '1.5.5'], ['fastapi', '0.141.1'],
  ['h11', '0.16.0'], ['httpcore', '1.0.9'], ['httptools', '0.8.0'], ['httpx', '0.28.1'], ['idna', '3.20'],
  ['pycparser', '3.0'], ['pydantic', '2.13.5'], ['pydantic_core', '2.46.5'], ['PyJWT', '2.15.1'],
  ['python-dotenv', '1.2.3'], ['PyYAML', '6.0.3'], ['starlette', '1.7.0'], ['typing-inspection', '0.4.4'],
  ['typing_extensions', '4.16.0'], ['uvicorn', '0.54.0'], ['uvloop', '0.22.1'], ['watchfiles', '1.3.0'], ['websockets', '17.1'],
];

function allowed(filename, roots, exactFiles = []) {
  return path.posix.normalize(filename) === filename
    && (exactFiles.includes(filename) || roots.some(root => filename.startsWith(`${root}/`)));
}

async function sha256(filename) {
  const digest = createHash('sha256');
  for await (const bytes of createReadStream(filename)) digest.update(bytes);
  return digest.digest('hex');
}

async function inventory(root, result) {
  for (const name of await fs.readdir(root)) {
    const filename = path.join(root, name);
    const metadata = await fs.lstat(filename);
    if (metadata.isDirectory() && !metadata.isSymbolicLink()) await inventory(filename, result);
    else result.add(filename);
  }
}

async function checkFile(entry) {
  try {
    const metadata = await fs.lstat(entry.path);
    if ((metadata.mode & 0o777) !== entry.mode) return { path: entry.path, reason: 'mode_mismatch' };
    if (entry.type === 'symlink') {
      if (!metadata.isSymbolicLink() || await fs.readlink(entry.path) !== entry.target) return { path: entry.path, reason: 'symlink_mismatch' };
    } else {
      if (!metadata.isFile() || metadata.isSymbolicLink() || await fs.realpath(entry.path) !== entry.path) return { path: entry.path, reason: 'unsafe_file_type' };
      if (metadata.size !== entry.size || await sha256(entry.path) !== entry.sha256) return { path: entry.path, reason: 'content_mismatch' };
    }
    return undefined;
  } catch (error) { return { path: entry.path, reason: error.code === 'ENOENT' ? 'missing' : 'read_failed' }; }
}

async function pythonPackages(python) {
  const source = 'import importlib.metadata,json,platform;print(json.dumps({"python":platform.python_version(),"packages":sorted([[d.metadata["Name"],d.version] for d in importlib.metadata.distributions()],key=lambda x:x[0].lower())}))';
  const result = await execute(python, ['-c', source], {
    timeout: 15000, maxBuffer: 128 * 1024,
    env: { PATH: '/usr/local/bin:/usr/bin:/bin', PYTHONDONTWRITEBYTECODE: '1', PYTHONNOUSERSITE: '1' },
  });
  return JSON.parse(result.stdout);
}

function packageDifferences(expected, actual) {
  const normalize = name => name.toLowerCase().replaceAll('_', '-');
  const wanted = new Map(expected.filter(([name]) => !['pip', 'setuptools', 'wheel'].includes(normalize(name))).map(([name, version]) => [normalize(name), version]));
  const observed = new Map(actual.filter(([name]) => !['pip', 'setuptools', 'wheel'].includes(normalize(name))).map(([name, version]) => [normalize(name), version]));
  const differences = [];
  for (const [name, version] of wanted) if (observed.get(name) !== version) differences.push({ package: name, expected: version, actual: observed.get(name) ?? null });
  for (const [name, version] of observed) if (!wanted.has(name)) differences.push({ package: name, expected: null, actual: version });
  return differences;
}

export async function verifyArtifacts({ manifestPath = '/opt/savia/fly/artifact-manifest.json', checkDependencies = true } = {}) {
  const manifest = JSON.parse(await fs.readFile(manifestPath, 'utf8'));
  if (manifest.version !== 1 || !Array.isArray(manifest.workerFiles) || !Array.isArray(manifest.frontendFiles)) throw new Error('Invalid immutable artifact manifest.');
  const entries = manifest.workerFiles.map(entry => {
    if (!allowed(entry.path, workerRoots, workerFiles)) throw new Error('Manifest contains a path outside immutable worker assets.');
    return entry;
  });
  for (const entry of manifest.frontendFiles) {
    const filename = entry.path.replace(/^\/app\//, '/opt/savia/');
    if (!allowed(filename, frontendRoots, ['/opt/savia/requirements.txt'])) throw new Error('Manifest contains a path outside immutable frontend assets.');
    entries.push({ ...entry, path: filename });
  }
  const failures = [];
  for (let offset = 0; offset < entries.length; offset += 32) {
    for (const failure of await Promise.all(entries.slice(offset, offset + 32).map(checkFile))) if (failure) failures.push(failure);
  }
  const expectedPaths = new Set(entries.map(entry => entry.path));
  const observedPaths = new Set();
  for (const root of [...workerRoots, ...frontendRoots]) await inventory(root, observedPaths);
  for (const filename of observedPaths) if (!expectedPaths.has(filename)) failures.push({ path: filename, reason: 'unexpected_immutable_file' });

  const tools = [
    ['/opt/codex/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex', '3e2584f3f3829a43a0495011a1cecb2facbe64a2403e2b682351fd9c2983f970'],
    ['/opt/codex-restricted/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex', '3e2584f3f3829a43a0495011a1cecb2facbe64a2403e2b682351fd9c2983f970'],
    ['/opt/github-cli/bin/gh', 'ea857a3f0f7d4276cf5848b236542c5048e2eaa7bdd1b6ddec238f8793e74bff'],
  ];
  const toolFailures = [];
  for (const [filename, wanted] of tools) if (await sha256(filename) !== wanted) toolFailures.push(filename);
  let runtime;
  if (checkDependencies) {
    const [banking, frontend] = await Promise.all([pythonPackages('/opt/banking-mcp/.venv/bin/python'), pythonPackages('/opt/savia/.venv/bin/python')]);
    runtime = {
      bankingPython: banking.python, bankingPackageDifferences: packageDifferences(manifest.bankingDependencies, banking.packages),
      frontendSourcePython: '3.13.15', frontendPython: frontend.python,
      frontendPackageDifferences: packageDifferences(frontendDependencies, frontend.packages),
    };
  }
  return {
    verified: failures.length === 0 && toolFailures.length === 0 && (!runtime || (runtime.bankingPackageDifferences.length === 0 && runtime.frontendPackageDifferences.length === 0)),
    sourceWorkerImage: manifest.worker.id, sourceFrontendImage: manifest.frontend.id,
    immutableFilesChecked: entries.length, immutableFailureCount: failures.length, immutableFailures: failures.slice(0, 12),
    toolchainBinariesChecked: tools.length, toolchainFailures: toolFailures, ...(runtime ? { runtime } : {}),
    ...(manifest.compilation ? { compilation: {
      sourceBuilderImage: manifest.compilation.sourceBuilderImage,
      originalTurnProvenancePatchSha256: manifest.compilation.originalTurnProvenancePatchSha256,
      adapterSelected: manifest.compilation.adapterSelected,
      compiledFileCount: manifest.compilation.compiledFileCount,
      nextManifestSha256: manifest.compilation.nextManifestSha256,
      replacesOnly: manifest.compilation.replacesOnly,
    } } : {}),
  };
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href || import.meta.url.endsWith('/[eval1]')) {
  verifyArtifacts().then(result => { console.log(JSON.stringify(result)); process.exitCode = result.verified ? 0 : 1; }).catch(error => {
    console.error(JSON.stringify({ verified: false, error: error.message })); process.exitCode = 1;
  });
}
