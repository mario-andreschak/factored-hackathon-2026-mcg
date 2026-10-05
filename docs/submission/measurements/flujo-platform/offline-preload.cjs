// Test-harness guard, not an operating-system network sandbox. Logs API names only.
const fs = require('node:fs');
const { syncBuiltinESMExports } = require('node:module');
function blocked(api) {
  return function () {
    if (process.env.FLUJO_EVIDENCE_NETWORK_LOG) fs.appendFileSync(process.env.FLUJO_EVIDENCE_NETWORK_LOG, `${api}\n`);
    throw new Error(`Offline evidence run blocked network API: ${api}`);
  };
}
for (const [moduleName, methods] of [
  ['node:net', ['connect', 'createConnection']],
  ['node:tls', ['connect']],
  ['node:http', ['request', 'get']],
  ['node:https', ['request', 'get']],
  ['node:dgram', ['createSocket']],
]) {
  const module = require(moduleName);
  for (const method of methods) module[method] = blocked(`${moduleName}.${method}`);
}
require('node:net').Socket.prototype.connect = blocked('node:net.Socket.connect');
globalThis.fetch = async () => blocked('global.fetch')();
syncBuiltinESMExports();
