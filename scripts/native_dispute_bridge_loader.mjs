// Load the real production bridge source without changing the checkout.
// The only substituted dependency is its diagnostic logger.
import fs from 'node:fs';
import path from 'node:path';
import Module, { createRequire } from 'node:module';
import { createHash } from 'node:crypto';

export function loadProductionBridge(flujoRoot) {
  const root = path.resolve(flujoRoot);
  const sourcePath = path.join(root, 'src/backend/services/model/adapters/codexToolBridge.ts');
  const source = fs.readFileSync(sourcePath, 'utf8');
  const requirePackage = createRequire(path.join(root, 'package.json'));
  const ts = requirePackage('typescript');
  const compiled = ts.transpileModule(source, { compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, esModuleInterop: true,
  }, fileName: sourcePath, reportDiagnostics: true });
  if (compiled.diagnostics?.some(d => d.category === ts.DiagnosticCategory.Error)) {
    throw new Error('Production bridge transpilation failed.');
  }
  const loaded = new Module(sourcePath);
  loaded.filename = sourcePath;
  loaded.paths = Module._nodeModulePaths(path.dirname(sourcePath));
  const normalRequire = loaded.require.bind(loaded);
  loaded.require = specifier => specifier === '@/utils/logger'
    ? { createLogger: () => Object.fromEntries(['debug', 'error', 'warn', 'info', 'verbose'].map(k => [k, () => {}])) }
    : normalRequire(specifier);
  loaded._compile(compiled.outputText, sourcePath);
  const sdkPath = requirePackage.resolve('@modelcontextprotocol/sdk/server/index.js');
  const sdkRoot = path.resolve(path.dirname(sdkPath), '../../..');
  return { startCodexToolBridge: loaded.exports.startCodexToolBridge, evidence: {
    bridgeSourceSha256: createHash('sha256').update(source).digest('hex'),
    bridgeSourcePath: sourcePath,
    bridgeImplementation: 'production source transpiled in memory',
    loggerSubstitution: 'only @/utils/logger replaced with silent diagnostic logger',
    typescriptVersion: ts.version,
    mcpSdkVersion: JSON.parse(fs.readFileSync(path.join(sdkRoot, 'package.json'), 'utf8')).version,
  } };
}
