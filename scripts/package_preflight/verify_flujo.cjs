#!/usr/bin/env node
'use strict';

// Inspect generated JavaScript as data. Never require a route or evaluate a
// webpack factory: importing FLUJO can initialize runtime services and state.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

function insist(condition, message) {
  if (!condition) throw new Error(message);
}
function options(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    insist(['--app-root', '--output', '--receipt-dir', '--parser', '--expected-flujo-revision'].includes(key)
      && argv[index + 1], 'invalid_arguments');
    insist(!result[key], 'duplicate_argument');
    result[key] = argv[index + 1];
  }
  insist(result['--app-root'] && Boolean(result['--output']) !== Boolean(result['--receipt-dir']), 'app_root_and_one_output_required');
  return result;
}
function json(filename) { return JSON.parse(fs.readFileSync(filename, 'utf8')); }
function within(root, filename) {
  const relative = path.relative(root, filename);
  return relative !== '..' && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative);
}
function walk(node, visit) {
  if (!node || typeof node !== 'object') return;
  if (typeof node.type === 'string') visit(node);
  for (const [key, value] of Object.entries(node)) {
    if (key === 'start' || key === 'end' || key === 'loc') continue;
    if (Array.isArray(value)) value.forEach(child => walk(child, visit));
    else if (value && typeof value === 'object') walk(value, visit);
  }
}
function name(node) {
  return node?.type === 'Identifier' ? node.name : node?.type === 'Literal' ? String(node.value) : undefined;
}
function property(node) {
  if (node?.type !== 'MemberExpression') return undefined;
  return node.computed ? node.property.type === 'Literal' ? String(node.property.value) : undefined : name(node.property);
}
function field(object, key) {
  return object?.type === 'ObjectExpression' ? object.properties.find(item => name(item.key) === key)?.value : undefined;
}
function functionNode(node) {
  return ['FunctionExpression', 'ArrowFunctionExpression', 'FunctionDeclaration'].includes(node?.type);
}
function returnValue(node) {
  if (node?.type === 'ArrowFunctionExpression' && node.body.type !== 'BlockStatement') return node.body;
  return node?.body?.body?.find(item => item.type === 'ReturnStatement')?.argument;
}
function numericImport(node, requireName) {
  return node?.type === 'CallExpression' && node.callee.type === 'Identifier'
    && node.callee.name === requireName && node.arguments.length === 1
    && node.arguments[0].type === 'Literal' && Number.isInteger(node.arguments[0].value)
    ? node.arguments[0].value : undefined;
}
function bindings(factory) {
  const found = new Map();
  for (const statement of factory.body.body) {
    if (statement.type === 'FunctionDeclaration') found.set(statement.id.name, statement);
    if (statement.type === 'VariableDeclaration') {
      for (const item of statement.declarations) {
        if (item.id.type === 'Identifier') found.set(item.id.name, item.init);
      }
    }
  }
  return found;
}
function exported(factory, key) {
  const requireName = name(factory.params[2]);
  const exportsName = name(factory.params[1]);
  let value;
  walk(factory.body, node => {
    if (node.type !== 'CallExpression' || property(node.callee) !== 'd'
      || name(node.callee.object) !== requireName || name(node.arguments[0]) !== exportsName) return;
    const getter = field(node.arguments[1], key);
    if (getter) {
      insist(value === undefined, `duplicate_export_${key}`);
      value = returnValue(getter);
    }
  });
  return value;
}
function imports(factory) {
  const result = new Set();
  const requireName = name(factory.params[2]);
  walk(factory.body, node => {
    const identifier = numericImport(node, requireName);
    if (identifier !== undefined) result.add(identifier);
  });
  return result;
}
function declaredFunction(factory, identifier) {
  let value = bindings(factory).get(identifier);
  const visited = new Set();
  while (value?.type === 'Identifier') {
    insist(!visited.has(value.name), 'binding_cycle');
    visited.add(value.name);
    value = bindings(factory).get(value.name);
  }
  return functionNode(value) ? value : undefined;
}
function postUsesRouteResponse(factory, coreId) {
  const declared = bindings(factory);
  const requireName = name(factory.params[2]);
  const namespaces = new Set([...declared].filter(([, value]) => numericImport(value, requireName) === coreId)
    .map(([identifier]) => identifier));
  const queued = [exported(factory, 'POST')];
  const visited = new Set();
  let responseCall = false;
  while (queued.length) {
    const expression = queued.shift();
    walk(expression, node => {
      if (node.type === 'Identifier' && declared.has(node.name) && !visited.has(node.name)) {
        visited.add(node.name);
        queued.push(declared.get(node.name));
      }
      if (node.type !== 'CallExpression') return;
      const callee = node.callee.type === 'SequenceExpression' ? node.callee.expressions.at(-1) : node.callee;
      if (property(callee) === 'executionExtensionRouteResponse' && namespaces.has(name(callee.object))) responseCall = true;
    });
  }
  return responseCall;
}

function adapterProof(modules, coreId) {
  const core = modules.get(coreId);
  const getter = exported(core.factory, 'executionExtensionAdapter');
  insist(getter?.type === 'Identifier', 'unsupported_execution_adapter_export');
  const responseGetter = exported(core.factory, 'executionExtensionRouteResponse');
  const response = responseGetter?.type === 'Identifier' ? declaredFunction(core.factory, responseGetter.name) : undefined;
  insist(response, 'route_response_function_missing');
  let delegatesToAdapter = false;
  walk(response.body, node => {
    if (property(node) === 'handleRoute' && node.object.type === 'CallExpression'
      && name(node.object.callee) === getter.name) delegatesToAdapter = true;
  });
  insist(delegatesToAdapter, 'route_response_does_not_use_configured_adapter');
  const queued = [getter.name];
  const visited = new Set();
  const initializers = [];
  while (queued.length) {
    const identifier = queued.shift();
    if (visited.has(identifier)) continue;
    visited.add(identifier);
    const fn = declaredFunction(core.factory, identifier);
    insist(fn, 'execution_adapter_function_missing');
    walk(fn.body, node => {
      if (node.type === 'AssignmentExpression' && node.operator === '??='
        && property(node.left) === 'configuredAdapter') initializers.push(node.right);
      if (node.type === 'CallExpression' && node.callee.type === 'Identifier'
        && declaredFunction(core.factory, node.callee.name)) queued.push(node.callee.name);
    });
  }
  insist(initializers.length === 1, 'configured_adapter_initializer_not_unique');
  const resolving = new Set();
  function resolve(moduleId, value) {
    const module = modules.get(moduleId);
    insist(module, 'adapter_module_missing');
    if (value?.type === 'ObjectExpression') return { moduleId, value };
    if (value?.type === 'Identifier') {
      const key = `${moduleId}:${value.name}`;
      insist(!resolving.has(key), 'adapter_binding_cycle');
      resolving.add(key);
      const declared = bindings(module.factory).get(value.name);
      insist(declared, 'configured_adapter_is_empty');
      return resolve(moduleId, declared);
    }
    if (value?.type === 'MemberExpression') {
      const imported = value.object.type === 'Identifier'
        ? bindings(module.factory).get(value.object.name) : value.object;
      const dependency = numericImport(imported, name(module.factory.params[2]));
      const exportName = property(value);
      // Webpack may shorten this export. Follow the precise property selected
      // by the registry initializer, then prove its banking object shape.
      insist(dependency !== undefined && typeof exportName === 'string', 'unsupported_adapter_import');
      const target = modules.get(dependency);
      insist(target, 'configured_adapter_module_missing');
      return resolve(dependency, exported(target.factory, exportName));
    }
    throw new Error('unsupported_adapter_initializer');
  }
  const resolved = resolve(coreId, initializers[0]);
  const required = ['authorizeTransport', 'withRoute', 'handleRoute', 'assertRun',
    'normalizeArguments', 'requestMeta', 'validateResult'];
  for (const key of required) insist(functionNode(field(resolved.value, key)), `banking_adapter_method_missing_${key}`);
  const handle = field(resolved.value, 'handleRoute');
  let actionBranch = false;
  let actionDispatch = false;
  walk(handle.body, node => {
    if (node.type === 'BinaryExpression' && node.operator === '==='
      && [node.left, node.right].some(part => part.type === 'Literal' && part.value === '/v1/banking/action')) actionBranch = true;
    if (node.type === 'CallExpression'
      && node.arguments.some(argument => property(argument) === 'principal')
      && node.arguments.some(argument => property(argument) === 'body')) actionDispatch = true;
  });
  insist(actionBranch && actionDispatch, 'configured_banking_action_handler_missing');
  return { coreModule: coreId, adapterModule: resolved.moduleId, routeResponseUsesAdapter: true, configuredInitializer: true,
    actionHandlerBranch: true, principalAndBodyDispatch: true, methods: required };
}

function routeProof(appRoot, acorn) {
  const server = path.join(appRoot, '.next', 'server');
  const manifest = json(path.join(server, 'app-paths-manifest.json'));
  const routeKey = '/v1/banking/action/route';
  const relative = manifest[routeKey];
  insist(typeof relative === 'string', 'compiled_action_route_missing');
  const routeFile = path.resolve(server, relative);
  insist(within(server, routeFile), 'action_route_outside_server');
  const trace = json(`${routeFile}.nft.json`);
  insist(trace.version === 1 && Array.isArray(trace.files), 'unsupported_route_trace');
  const files = [routeFile];
  for (const item of trace.files) {
    insist(typeof item === 'string', 'invalid_route_trace_entry');
    const filename = path.resolve(path.dirname(routeFile), item);
    if (within(server, filename) && filename.endsWith('.js')) files.push(filename);
  }
  const parsed = new Map();
  const modules = new Map();
  for (const filename of [...new Set(files)].sort()) {
    const source = fs.readFileSync(filename, 'utf8');
    const ast = acorn.parse(source, { ecmaVersion: 'latest', sourceType: 'script' });
    parsed.set(filename, ast);
    walk(ast, node => {
      if (node.type !== 'AssignmentExpression' || property(node.left) !== 'modules'
        || node.right.type !== 'ObjectExpression') return;
      for (const item of node.right.properties) {
        const identifier = Number(name(item.key));
        insist(Number.isInteger(identifier) && functionNode(item.value), 'unsupported_webpack_module');
        const content = source.slice(item.value.start, item.value.end);
        const previous = modules.get(identifier);
        insist(!previous || previous.content === content, 'conflicting_webpack_module');
        modules.set(identifier, { factory: item.value, filename, content });
      }
    });
  }
  let userlandId;
  walk(parsed.get(routeFile), node => {
    if (node.type !== 'NewExpression' || property(node.callee) !== 'AppRouteRouteModule') return;
    const descriptor = node.arguments[0];
    if (field(field(descriptor, 'definition'), 'pathname')?.value !== '/v1/banking/action') return;
    const userland = field(descriptor, 'userland');
    const value = returnValue(userland);
    insist(value?.type === 'CallExpression' && value.arguments[0]?.type === 'Literal'
      && Number.isInteger(value.arguments[0].value), 'unsupported_action_userland');
    insist(userlandId === undefined, 'duplicate_action_route_definition');
    userlandId = value.arguments[0].value;
  });
  insist(userlandId !== undefined && modules.has(userlandId), 'action_userland_factory_missing');
  const userland = modules.get(userlandId);
  insist(exported(userland.factory, 'POST'), 'compiled_action_post_missing');
  const reachable = new Set();
  const queued = [userlandId];
  while (queued.length) {
    const identifier = queued.shift();
    if (reachable.has(identifier)) continue;
    reachable.add(identifier);
    const module = modules.get(identifier);
    insist(module, 'route_dependency_not_in_trace');
    queued.push(...imports(module.factory));
  }
  const coreIds = [...reachable].filter(identifier => exported(modules.get(identifier).factory, 'executionExtensionAdapter'));
  insist(coreIds.length === 1, 'route_execution_adapter_export_not_unique');
  const coreId = coreIds[0];
  insist(imports(userland.factory).has(coreId), 'action_route_does_not_import_execution_adapter_core');
  insist(exported(modules.get(coreId).factory, 'executionExtensionRouteResponse'), 'route_response_export_missing');
  insist(postUsesRouteResponse(userland.factory, coreId), 'action_post_does_not_call_route_response');
  const proof = adapterProof(modules, coreId);
  return { route: routeKey, userlandModule: userlandId, postCallsRouteResponse: true, reachableModules: reachable.size,
    ...proof, tracedFiles: [...new Set(files)].sort().map(filename => path.relative(appRoot, filename).split(path.sep).join('/')) };
}

async function sha256(filename) {
  const digest = crypto.createHash('sha256');
  for await (const chunk of fs.createReadStream(filename)) digest.update(chunk);
  return digest.digest('hex');
}
async function hashTree(appRoot, directory) {
  const result = {};
  async function inspect(current) {
    for (const item of fs.readdirSync(current, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      const filename = path.join(current, item.name);
      insist(!item.isSymbolicLink(), 'unexpected_compiled_output_symlink');
      if (item.isDirectory()) await inspect(filename);
      else if (item.isFile()) {
        insist(Object.keys(result).length < 50000, 'compiled_manifest_too_large');
        result[path.relative(appRoot, filename).split(path.sep).join('/')] = await sha256(filename);
      }
    }
  }
  await inspect(directory);
  return result;
}
async function main() {
  const args = options(process.argv.slice(2));
  const appRoot = path.resolve(args['--app-root']);
  const output = args['--output'] ? path.resolve(args['--output'])
    : path.join(path.resolve(args['--receipt-dir']), 'flujo-compiled-provenance.json');
  const pinnedRevision = '961fd13b823088c9f0f473cddefd962816a13bc2';
  const expectedRevision = args['--expected-flujo-revision'] ?? pinnedRevision;
  insist(expectedRevision === pinnedRevision, 'unexpected_flujo_source_pin');
  const parserFile = args['--parser'] ? path.resolve(args['--parser'])
    : path.join(appRoot, 'node_modules', 'next', 'dist', 'compiled', 'acorn', 'acorn.js');
  const acorn = require(parserFile); // Parser only; no application code is imported.
  const pkg = json(path.join(appRoot, 'package.json'));
  insist(pkg.name === 'flujo-ai' && pkg.version === '3.46.1', 'unexpected_pinned_flujo_package');
  const lock = json(path.join(appRoot, 'package-lock.json'));
  insist(lock.packages?.['']?.version === pkg.version, 'lock_package_version_mismatch');
  const proof = routeProof(appRoot, acorn);
  insist(process.env.FLUJO_BUILD_REVISION === expectedRevision, 'runtime_build_revision_mismatch');
  const files = await hashTree(appRoot, path.join(appRoot, '.next'));
  for (const relative of ['package.json', 'package-lock.json', 'next.config.mjs', 'scripts/launch-next.mjs', 'scripts/healthcheck.mjs']) {
    files[relative] = await sha256(path.join(appRoot, relative));
  }
  const workspaces = {};
  for (const directory of ['bash', 'browser', 'filesystem', 'flujo', 'shared']) {
    const workspaceRoot = path.join(appRoot, 'mcp-servers', directory);
    const workspace = json(path.join(workspaceRoot, 'package.json'));
    insist(fs.statSync(path.join(workspaceRoot, 'dist', 'index.js')).isFile(), `mcp_dist_missing_${directory}`);
    workspaces[directory] = { name: workspace.name, version: workspace.version,
      files: await hashTree(appRoot, path.join(workspaceRoot, 'dist')) };
  }
  const observedEnvironment = {};
  for (const key of ['NODE_ENV', 'FLUJO_BUILD_REVISION', 'FLUJO_CONTAINER', 'FLUJO_APP_ROOT', 'FLUJO_DATA_DIR', 'PLAYWRIGHT_BROWSERS_PATH']) {
    observedEnvironment[key] = process.env[key] ?? null;
  }
  const receipt = { schemaVersion: 1, application: { name: pkg.name, version: pkg.version,
    revision: process.env.FLUJO_BUILD_REVISION, expectedRevision }, observedEnvironment,
    inspection: 'static_ast_no_application_import_or_handler_call', parser: { package: 'next/dist/compiled/acorn', sha256: await sha256(parserFile) },
    configuredAdapter: proof, fileHashes: files, builtInMcp: workspaces };
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.writeFileSync(output, `${JSON.stringify(receipt, null, 2)}\n`);
  console.log(JSON.stringify({ verified: true, manifest: output, configuredAdapter: true,
    actionRoute: true, hashedFiles: Object.keys(files).length }));
}
main().catch(error => {
  console.error(JSON.stringify({ verified: false, code: error.message }));
  process.exitCode = 1;
});
