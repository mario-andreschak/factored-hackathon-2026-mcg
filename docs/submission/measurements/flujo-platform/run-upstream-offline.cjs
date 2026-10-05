// Replay selected upstream unit suites from a Git archive of the immutable pin.
// Usage: node run-upstream-offline.cjs <FLUJO-git-checkout> <cached-node_modules> [output-directory]
// No install, fetch, provider, application-server startup, or checkout mutation.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const cp = require('node:child_process');
const crypto = require('node:crypto');

const [checkoutArg, dependenciesArg, outputArg] = process.argv.slice(2);
if (!checkoutArg || !dependenciesArg) throw new Error('Supply a local FLUJO Git checkout and an existing node_modules directory.');
const checkout = fs.realpathSync(checkoutArg);
const dependencies = fs.realpathSync(dependenciesArg);
const output = path.resolve(outputArg || path.join(__dirname, 'replay-output'));
const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, 'source-manifest.json'), 'utf8'));
const pin = manifest.commit;
const suites = manifest.files.filter((entry) => entry.upstreamPath.startsWith('__tests__/')).map((entry) => entry.upstreamPath);
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'savia-flujo-evidence-'));
const sourceRoot = path.join(temp, 'checkout');
fs.mkdirSync(sourceRoot);
fs.mkdirSync(output, { recursive: true });
const git = (args) => cp.execFileSync('git', args, { cwd: checkout, maxBuffer: 8 * 1024 * 1024 });
if (git(['rev-parse', `${pin}^{tree}`]).toString().trim() !== manifest.tree) throw new Error('Upstream tree differs from the evidence manifest.');
const archive = path.join(temp, 'source.tar');
git(['-c', 'core.autocrlf=false', '-c', 'core.eol=lf', 'archive', '--format=tar', `--output=${archive}`, pin,
  'src', '__tests__', 'mcp-servers', 'scripts', 'tooling', 'package.json', 'package-lock.json',
  'next.config.mjs', 'tsconfig.json', 'tsconfig.build.json', 'jest.config.mjs',
  'jest.testMatch.mjs', 'jest.setup.ts', 'jest.setup.jsdom.ts']);
cp.execFileSync('tar', ['-xf', archive, '-C', sourceRoot]);
for (const entry of manifest.files) {
  if (entry.upstreamPath === 'LICENSE') continue; // not required by the temporary runner
  const source = fs.readFileSync(path.join(sourceRoot, entry.upstreamPath));
  if (crypto.createHash('sha256').update(source).digest('hex') !== entry.sha256) throw new Error(`Archive source mismatch: ${entry.upstreamPath}`);
}
fs.symlinkSync(dependencies, path.join(sourceRoot, 'node_modules'), process.platform === 'win32' ? 'junction' : 'dir');
const lockBytes = fs.readFileSync(path.join(sourceRoot, 'package-lock.json'));
const lock = JSON.parse(lockBytes.toString('utf8'));
const pkg = JSON.parse(fs.readFileSync(path.join(sourceRoot, 'package.json'), 'utf8'));
const installedPackages = Object.keys({ ...pkg.dependencies, ...pkg.devDependencies }).sort().map((name) => {
  const lockedEntry = lock.packages?.[`node_modules/${name}`];
  const expectedVersion = lockedEntry?.link ? lock.packages?.[lockedEntry.resolved]?.version : lockedEntry?.version;
  let installedVersion;
  try { installedVersion = JSON.parse(fs.readFileSync(path.join(dependencies, name, 'package.json'), 'utf8')).version; }
  catch { installedVersion = null; }
  return { name, lockedVersion: expectedVersion ?? null, installedVersion, matchesLockedVersion: installedVersion === expectedVersion };
});
const cleanText = (text) => text.replaceAll(temp, '<temporary-evidence-directory>').replaceAll(temp.replaceAll('\\', '/'), '<temporary-evidence-directory>').replaceAll(dependencies, '<cached-node_modules>');
const networkLog = path.join(temp, 'network-attempts.log');
const rawResults = path.join(temp, 'jest-results.json');
// The archived tree has no .env files. Drop inherited credentials and private
// integration selections before evaluating any source/configuration modules.
const env = { ...process.env, NODE_PATH: '', NODE_OPTIONS: '', FLUJO_EVIDENCE_NETWORK_LOG: networkLog };
for (const name of Object.keys(env)) {
  if (/(API.?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)/i.test(name) || /^FLUJO_(EXECUTION|PARENT_DATA|DATA_DIR|EXPOSURE|WORKER)/i.test(name)) delete env[name];
}
const args = ['--require', path.join(__dirname, 'offline-preload.cjs'),
  path.join(sourceRoot, 'node_modules/jest/bin/jest.js'),
  '--config', path.join(sourceRoot, 'jest.config.mjs'), '--selectProjects', 'node',
  '--runInBand', '--runTestsByPath', ...suites, '--json', `--outputFile=${rawResults}`];
const startedAt = new Date().toISOString();
const start = performance.now();
const run = cp.spawnSync(process.execPath, args, { cwd: sourceRoot, env, encoding: 'utf8', timeout: 120000, maxBuffer: 8 * 1024 * 1024 });
const durationMs = Math.round(performance.now() - start);
fs.writeFileSync(path.join(output, 'upstream-test-log.txt'), cleanText(`${run.stdout || ''}${run.stderr || ''}`));
const attempts = fs.existsSync(networkLog) ? fs.readFileSync(networkLog, 'utf8').trim().split('\n').filter(Boolean) : [];
let results;
if (fs.existsSync(rawResults)) {
  results = JSON.parse(cleanText(fs.readFileSync(rawResults, 'utf8')));
  fs.writeFileSync(path.join(output, 'upstream-tests.json'), JSON.stringify(results, null, 2) + '\n');
}
const receipt = {
  schemaVersion: 1, startedAt, finishedAt: new Date().toISOString(), durationMs,
  source: { repository: manifest.repository, commit: pin, tree: manifest.tree, method: 'git archive of pinned objects; temporary directory; source subset hashes checked' },
  runtime: { node: process.version, platform: process.platform, architecture: process.arch,
    dependencies: 'Reused pre-existing local node_modules; no installation or lockfile recreation',
    installedPackages, mismatchedLockedVersions: installedPackages.filter((entry) => !entry.matchesLockedVersion).length,
    lockfileSha256: crypto.createHash('sha256').update(lockBytes).digest('hex') },
  command: 'node --require <evidence>/offline-preload.cjs <isolated-checkout>/node_modules/jest/bin/jest.js --config <isolated-checkout>/jest.config.mjs --selectProjects node --runInBand --runTestsByPath <listed suites> --json --outputFile=<temporary-results>',
  suites, exitCode: run.status, signal: run.signal, runnerError: run.error ? cleanText(run.error.message) : null,
  networkGuard: { kind: 'In-process JavaScript API guard; not an OS sandbox', blockedAttempts: attempts.length, attemptedApis: attempts },
  result: results ? { success: results.success, suitesPassed: results.numPassedTestSuites, suitesFailed: results.numFailedTestSuites,
    testsPassed: results.numPassedTests, testsFailed: results.numFailedTests, testsPending: results.numPendingTests,
    assertions: results.testResults.map((suite) => ({ suite: suite.name.replace(/^.*checkout[\\/]/, ''), status: suite.status,
      passed: suite.assertionResults.filter((test) => test.status === 'passed').length,
      failed: suite.assertionResults.filter((test) => test.status === 'failed').length })) } : null,
  limits: ['Selected upstream unit tests with mocks; not the full suite or production build.',
    'Not a clean dependency installation. Exact locked-version comparison is recorded above; transitive dependency integrity was not reinstalled or audited.',
    'No deployed-runtime, live MCP transport, provider output, long-running endurance, or Savia customer-path acceptance is established.'],
};
fs.writeFileSync(path.join(output, 'upstream-test-receipt.json'), JSON.stringify(receipt, null, 2) + '\n');
// Only the fresh directory made by this script can be removed. Remove the
// dependency link first so cleanup never traverses the shared dependency tree.
fs.unlinkSync(path.join(sourceRoot, 'node_modules'));
if (!path.basename(temp).startsWith('savia-flujo-evidence-') || path.dirname(temp) !== path.resolve(os.tmpdir())) throw new Error('Temporary cleanup boundary mismatch.');
fs.rmSync(temp, { recursive: true, force: true });
console.log(JSON.stringify({ exitCode: receipt.exitCode, result: receipt.result, blockedNetworkAttempts: attempts.length, dependencyVersionMismatches: receipt.runtime.mismatchedLockedVersions, output }));
process.exitCode = run.status ?? 1;
