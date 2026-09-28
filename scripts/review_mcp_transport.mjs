// Review probe only: installed SDK carriers, not FLUJO banking authorization.
// No network, organizer data, real credentials, or modifications to FLUJO.
// node scripts/review_mcp_transport.mjs --flujo-root C:/path/to/FLUJO
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import { randomUUID, createHash } from 'node:crypto';
import { runInNewContext } from 'node:vm';

const flag = process.argv.indexOf('--flujo-root');
assert(flag >= 0 && process.argv[flag + 1], '--flujo-root is required');
const root = resolve(process.argv[flag + 1]);
const moduleAt = (path) => import(pathToFileURL(resolve(root, 'node_modules', path)).href);
const [{ Client: V1 }, { Client: V2, StreamableHTTPClientTransport: V2Http },
  { StreamableHTTPClientTransport: V1Http }, { Server }, { WebStandardStreamableHTTPServerTransport },
  { CallToolRequestSchema, ListToolsRequestSchema }] = await Promise.all([
  moduleAt('@modelcontextprotocol/sdk/dist/esm/client/index.js'),
  moduleAt('@modelcontextprotocol/client/dist/index.mjs'),
  moduleAt('@modelcontextprotocol/sdk/dist/esm/client/streamableHttp.js'),
  moduleAt('@modelcontextprotocol/sdk/dist/esm/server/index.js'),
  moduleAt('@modelcontextprotocol/sdk/dist/esm/server/webStandardStreamableHttp.js'),
  moduleAt('@modelcontextprotocol/sdk/dist/esm/types.js'),
]);
const versions = {};
for (const name of ['sdk', 'client']) {
  versions[name] = JSON.parse(await readFile(resolve(root, 'node_modules/@modelcontextprotocol', name, 'package.json'), 'utf8')).version;
}

async function probe(generation, carrier, count) {
  const server = new Server({ name: 'synthetic-bank-review', version: '0' }, { capabilities: { tools: {} } });
  const serverTransport = new WebStandardStreamableHTTPServerTransport({ sessionIdGenerator: randomUUID, enableJsonResponse: true });
  const seen = new Map();
  const headersByRequestId = new Map();
  server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: [{
    name: 'synthetic_echo', inputSchema: { type: 'object', properties: { slot: { type: 'integer' } }, required: ['slot'] },
  }] }));
  server.setRequestHandler(CallToolRequestSchema, async (req, extra) => {
    const slot = req.params.arguments.slot;
    const actual = carrier === 'meta' ? extra._meta?.['com.flujo.bank/assertion'] : headersByRequestId.get(extra.requestId)?.get('x-flujo-bank-assertion');
    const expected = `synthetic-principal-${slot}`;
    if (carrier === 'v1-header-negative') assert.equal(actual, null);
    else assert.equal(actual, expected);
    seen.set(slot, actual ?? 'absent-as-expected');
    // Deliberately reorder responses while sharing one client/transport.
    await new Promise((done) => setTimeout(done, (count - slot) % 11));
    return { content: [{ type: 'text', text: String(slot) }] };
  });
  await server.connect(serverTransport);
  const fetchStub = async (url, init) => {
    assert.equal(String(url), 'https://synthetic-bank.invalid/mcp');
    const headers = new Headers(init?.headers);
    assert.equal(headers.get('authorization'), 'Bearer synthetic-service');
    if (init?.body) {
      const body = JSON.parse(String(init.body));
      if (body.id !== undefined) headersByRequestId.set(body.id, headers);
      if (body.method === 'tools/call' && carrier !== 'meta') {
        assert(!String(init.body).includes('synthetic-principal-'), 'header assertion leaked into request body');
      }
    }
    return serverTransport.handleRequest(new Request(url, init));
  };
  const client = generation === 1
    ? new V1({ name: 'review-v1', version: '0' }, { capabilities: {} })
    : new V2({ name: 'review-v2', version: '0' }, { capabilities: {}, versionNegotiation: { mode: 'legacy' } });
  const Http = generation === 1 ? V1Http : V2Http;
  const transport = new Http(new URL('https://synthetic-bank.invalid/mcp'), {
    requestInit: { headers: { Authorization: 'Bearer synthetic-service' } }, fetch: fetchStub,
  });
  try {
    await client.connect(transport);
    await client.listTools();
    await Promise.all(Array.from({ length: count }, async (_, slot) => {
      const params = {
        name: 'synthetic_echo', arguments: { slot },
        ...(carrier === 'meta' ? { _meta: { 'com.flujo.bank/assertion': `synthetic-principal-${slot}` } } : {}),
      };
      const options = { timeout: 10000, ...(carrier !== 'meta' ? { headers: {
        'x-flujo-bank-assertion': `synthetic-principal-${slot}`,
        // v2 protects this connection-owned header; do not use it as the principal carrier.
        ...(generation === 2 ? { Authorization: 'Bearer forbidden-override' } : {}),
      } } : {}) };
      const result = generation === 1 ? await client.callTool(params, undefined, options) : await client.callTool(params, options);
      assert.equal(result.content[0].text, String(slot));
    }));
    assert.equal(seen.size, count);
    return { generation, carrier, calls: count, result: 'pass' };
  } finally {
    await client.close();
    await server.close();
  }
}

const results = [];
for (const [generation, carrier, count] of [[1, 'meta', 500], [2, 'meta', 500], [2, 'header', 500], [1, 'v1-header-negative', 2]]) {
  results.push(await probe(generation, carrier, count));
}

// Execute the actual TS module with only workspaceCacheKey stubbed to one fixed
// workspace. This isolates the server-keyed map behavior without booting FLUJO.
const { default: ts } = await moduleAt('typescript/lib/typescript.js');
const elicitationSource = await readFile(resolve(root, 'src/backend/services/mcp/elicitationContext.ts'), 'utf8');
const js = ts.transpileModule(elicitationSource, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const exported = {};
runInNewContext(js, { exports: exported, require(name) {
  assert.equal(name, '@/utils/workspace');
  return { workspaceCacheKey: (key) => `synthetic-workspace\0${key}` };
} });
exported.setElicitationContext('bank', { conversationId: 'synthetic-A', getUnattended: () => false });
exported.setElicitationContext('bank', { conversationId: 'synthetic-B', getUnattended: () => false });
assert.equal(exported.getElicitationContext('bank').conversationId, 'synthetic-B');
exported.clearElicitationContext('bank'); // A's completion would erase B's binding.
assert.equal(exported.getElicitationContext('bank'), undefined);
const elicitationOverlap = {
  sourceSha256: createHash('sha256').update(elicitationSource).digest('hex'),
  result: 'Observed: B overwrites A; clearing by server removes the remaining context.',
  limits: 'Actual module, transpiled; workspace namespace stubbed. No server elicitation or SSE was invoked.',
};
process.stdout.write(JSON.stringify({ versions, results, elicitationOverlap, limits: 'Synthetic SDK carrier probe; v2 legacy negotiation only. Not an end-to-end FLUJO isolation or performance test.' }, null, 2) + '\n');
