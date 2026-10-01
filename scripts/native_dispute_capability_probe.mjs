// Forced native dispatch probes use synthetic upstream responses and synthetic
// authentication. Real provider inference is separately tested by the runner.
// node native_dispute_capability_probe.mjs /absolute/native/codex /absolute/catalog [single_case-or-] /absolute/FLUJO
// Actual production bridge source; diagnostic logger alone is substituted.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import https from 'node:https';
import { spawn, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { zstdDecompressSync as decompress } from 'node:zlib';
import { loadProductionBridge } from './native_dispute_bridge_loader.mjs';
const flujoRoot = process.argv[5];
if (!flujoRoot) throw new Error('Supply trusted FLUJO source root as fifth argument (binary,catalog,case-or-,root).');
const productionBridge = loadProductionBridge(flujoRoot);

const binary = path.resolve(process.argv[2]);
const tlsRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'dispute-public-native-fixture-'));
const tlsCertificate = path.join(tlsRoot, 'public-fixture.crt');
const tlsKey = path.join(tlsRoot, 'public-fixture.key');
const tlsServerCertificate = path.join(tlsRoot, 'public-server.crt');
const caKey = path.join(tlsRoot, 'public-ca.key');
const csr = path.join(tlsRoot, 'public-server.csr');
const extensions = path.join(tlsRoot, 'public-server.ext');
fs.writeFileSync(extensions, 'basicConstraints=critical,CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=IP:127.0.0.1,DNS:localhost\n');
const generated = spawnSync('openssl', ['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
  '-keyout', caKey, '-out', tlsCertificate, '-subj', '/CN=dispute-public-synthetic-CA',
  '-addext', 'basicConstraints=critical,CA:TRUE'], { stdio: 'ignore' });
const requested = spawnSync('openssl', ['req', '-new', '-newkey', 'rsa:2048', '-nodes', '-keyout', tlsKey,
  '-out', csr, '-subj', '/CN=dispute-public-synthetic-server'], { stdio: 'ignore' });
const signed = spawnSync('openssl', ['x509', '-req', '-in', csr, '-CA', tlsCertificate, '-CAkey', caKey,
  '-CAcreateserial', '-out', tlsServerCertificate, '-days', '1', '-extfile', extensions], { stdio: 'ignore' });
if ([generated, requested, signed].some(result => result.status !== 0)) throw new Error('Cannot generate public synthetic TLS fixture');
function localOrigin(port) {
  const url = new URL(`https://127.0.0.1:${port}`);
  if (url.hostname !== '127.0.0.1' || url.protocol !== 'https:' || url.username || url.password) throw new Error('Non-loopback mock origin');
  return url.origin;
}
const catalog = process.argv[3] && process.argv[3] !== '-' && path.resolve(process.argv[3]);
const version = spawnSync(binary, ['--version'], { encoding: 'utf8' }).stdout.trim();
console.log(JSON.stringify({ ...productionBridge.evidence, fixtureSha256:createHash('sha256').update(fs.readFileSync(new URL(import.meta.url))).digest('hex'), version, sha256: createHash('sha256').update(fs.readFileSync(binary)).digest('hex'),
  ...(catalog ? { catalogSha256: createHash('sha256').update(fs.readFileSync(catalog)).digest('hex'),
    catalogSlugs: JSON.parse(fs.readFileSync(catalog, 'utf8')).models.map(m => m.slug) } : {}) }));
const disabled = ['shell_tool', 'unified_exec', 'multi_agent', 'multi_agent_v2', 'apps', 'plugins',
  'browser_use', 'browser_use_external', 'computer_use', 'code_mode', 'code_mode_host',
  'image_generation', 'memories', 'hooks', 'skill_search', 'tool_suggest', 'workspace_dependencies',
  'goals', 'in_app_browser', 'sleep_tool', 'view_image', 'auth_elicitation',
  'tool_call_mcp_elicitation', 'default_mode_request_user_input'];
const failures = [];
for (const model of ['gpt-6-sol', 'gpt-6-luna']) {
  for (const tool of ['inventory', 'approved_mcp', 'read_mcp_resource', 'rogue_namespace', 'mcp__rogue__rogue_access', 'apply_patch_foreign', 'functions_exec']) {
    if (process.argv[4] && process.argv[4] !== '-' && process.argv[4] !== tool) continue;
    const ancestor = fs.mkdtempSync(path.join(os.tmpdir(), 'flujo-codex-restricted-probe-'));
    spawnSync('git', ['init', ancestor], { stdio: 'ignore' });
    fs.mkdirSync(path.join(ancestor, '.codex'));
    const home = fs.mkdtempSync(path.join(ancestor, 'codex-private-'));
    const neutral = path.join(home,'workspace');
    const privatePaths = {APPDATA:path.join(home,'AppData','Roaming'),LOCALAPPDATA:path.join(home,'AppData','Local'),XDG_CONFIG_HOME:path.join(home,'.config'),XDG_CACHE_HOME:path.join(home,'.cache'),XDG_DATA_HOME:path.join(home,'.local','share'),XDG_STATE_HOME:path.join(home,'.local','state'),XDG_RUNTIME_DIR:path.join(home,'.runtime'),TMPDIR:path.join(home,'tmp'),TMP:path.join(home,'tmp'),TEMP:path.join(home,'tmp')};
    for(const directory of [neutral,...new Set(Object.values(privatePaths))])fs.mkdirSync(directory,{recursive:true,mode:0o700});
    const catalogSnapshot = path.join(home,'model-catalog.json');
    fs.writeFileSync(catalogSnapshot,fs.readFileSync(catalog),{flag:'wx',mode:0o600});
    fs.writeFileSync(path.join(home,'config.toml'),'cli_auth_credentials_store = "file"\n',{flag:'wx',mode:0o600});
    const foreign = path.join(ancestor, 'foreign-sentinel.txt');
    const sentinel = `SYNTHETIC_FOREIGN_${Math.random().toString(36).slice(2)}`;
    fs.writeFileSync(foreign, sentinel);
    const mcpScript = path.join(neutral, 'synthetic-mcp.cjs');
    fs.writeFileSync(mcpScript, `const readline=require('node:readline'),fs=require('node:fs');
      const allowed=process.argv[2],marker=process.argv[3];
      readline.createInterface({input:process.stdin}).on('line',line=>{const r=JSON.parse(line);if(r.id===undefined)return;
      let result;if(r.method==='initialize')result={protocolVersion:r.params.protocolVersion,capabilities:{tools:{}},serverInfo:{name:'synthetic',version:'1'}};
      else if(r.method==='tools/list')result={tools:[{name:allowed,description:'Synthetic approved read',inputSchema:{type:'object',properties:{},additionalProperties:false}}]};
      else if(r.method==='tools/call'&&r.params.name===allowed){fs.writeFileSync(marker,'called');result={content:[{type:'text',text:'SYNTHETIC_APPROVED_READ'}]};}
      else{process.stdout.write(JSON.stringify({jsonrpc:'2.0',id:r.id,error:{code:-32601,message:'Synthetic denied'}})+'\\n');return;}
      process.stdout.write(JSON.stringify({jsonrpc:'2.0',id:r.id,result})+'\\n');});`);
    const rogueMarker = path.join(neutral, 'rogue-executed');
    const approvedMarker = path.join(neutral, 'approved-executed');
    fs.writeFileSync(path.join(ancestor, '.codex', 'config.toml'), `[mcp_servers.rogue]\ncommand=${JSON.stringify(process.execPath)}\nargs=${JSON.stringify([mcpScript, 'rogue_access', rogueMarker])}\n`);
    const bridgeCalls = [];
    const bridge = await productionBridge.startCodexToolBridge([{name:'approved_read',description:'Synthetic approved read',inputSchema:{type:'object',properties:{},additionalProperties:false},handler:async args=>{bridgeCalls.push({name:'approved_read',argumentKeys:Object.keys(args)});fs.writeFileSync(approvedMarker,'called');return {content:[{type:'text',text:'SYNTHETIC_APPROVED_READ'}]};}}]);
    let child, round = 0, timedOut = false;
    const observed = [];
    const requests = [];
    let stderr = '', stdout = '';
    let names = [];
    const patch = tool === 'apply_patch_foreign'
      ? `*** Begin Patch\n*** Update File: ${foreign}\n@@\n-${sentinel}\n+modified\n*** End Patch`
      : '*** Begin Patch\n*** Add File: forced-marker.txt\n+synthetic\n*** End Patch';
    const args = tool.startsWith('apply_patch') ? JSON.stringify({ patch })
      : tool === 'view_image' ? JSON.stringify({ path: path.join(neutral, 'missing.png') })
      : ['spawn_agent', 'collaboration_spawn', 'collaboration.spawn_agent'].includes(tool) ? JSON.stringify({ message: 'Synthetic only' })
      : tool === 'functions_exec' ? JSON.stringify({ code: "await import('node:fs').then(fs => fs.writeFileSync('forced-marker.txt', 'synthetic'))" })
      : ['list_mcp_resources', 'list_mcp_resource_templates', 'read_mcp_resource'].includes(tool) ? JSON.stringify({ server: 'flujo', uri: `file://${foreign}` })
      : tool === 'request_user_input' ? JSON.stringify({ questions: [{ header: 'Probe', id: 'probe',
          question: 'Synthetic only?', options: [{ label: 'Yes', description: 'Synthetic' }, { label: 'No', description: 'Synthetic' }] }] })
      : JSON.stringify({ cmd: 'echo synthetic > forced-marker.txt', command: 'echo synthetic > forced-marker.txt',
          path: path.join(neutral, 'missing.txt'), query: 'synthetic local probe' });
    const server = https.createServer({key:fs.readFileSync(tlsKey),cert:fs.readFileSync(tlsServerCertificate)},(req, res) => {
      let chunks = [];
      req.on('data', b => chunks.push(b));
      req.on('end', () => {
        const bytes = Buffer.concat(chunks);
        const body = Buffer.from(req.headers['content-encoding']==='zstd' ? decompress(bytes) : bytes).toString('utf8');
        if (req.method === 'GET') {
          requests.push({method:req.method,path:req.url,authorization:req.headers.authorization === 'Bearer synthetic-chatgpt-access',account:req.headers['chatgpt-account-id']});
          res.writeHead(200, {'content-type':'application/json'});
          res.end(JSON.stringify(req.url.includes('/accounts/check') ? {accounts:[{id:'synthetic-account',plan_type:'plus',workspace_backend_origin:localOrigin(server.address().port),account_routing_override:'NO_CONSTRAINT',structure:'personal'}],account_ordering:['synthetic-account'],default_account_id:'synthetic-account'} : req.url.includes('/models') ? JSON.parse(fs.readFileSync(catalog,'utf8')) : {}));
          return;
        }
        const payload = body ? JSON.parse(body) : {};
        if (req.url === '/codex/analytics-events/events') {res.writeHead(200,{'content-type':'application/json'});res.end('{}');return;}
        requests.push({method:req.method,transport:req.ws ? 'websocket':'https',path:req.url,authorization:req.headers.authorization === 'Bearer synthetic-chatgpt-access',account:req.headers['chatgpt-account-id'],originator:req.headers.originator,contentType:req.headers['content-type'],contentEncoding:req.headers['content-encoding'],responsesLite:req.headers['x-openai-internal-codex-responses-lite'],keys:Object.keys(payload),model:payload.model});
        if (req.method !== 'POST' || !req.url.endsWith('/responses') || !Array.isArray(payload.input)) {
          failures.push({ model, tool, unexpectedRequest: true });
          res.writeHead(400); res.end(); child.kill(); return;
        }
        names = (payload.tools ?? []).flatMap(t => t.type === 'namespace' ? t.tools.map(x => `${t.name}.${x.name}`) : [t.name ?? t.type]);
        observed.push(...payload.input.filter(i => ['function_call_output', 'custom_tool_call_output'].includes(i.type))
          .map(i => typeof i.output === 'string' ? i.output : JSON.stringify(i.output)));
        res.writeHead(200, { 'content-type': 'text/event-stream' });
        if(payload.generate===false){
          res.write(`data: ${JSON.stringify({type:'response.created',response:{id:'resp_warm'}})}\n\n`);
          res.write(`data: ${JSON.stringify({type:'response.completed',response:{id:'resp_warm',output:[],usage:{input_tokens:0,output_tokens:0,total_tokens:0}}})}\n\n`);
          res.end();return;
        }
        const item = round++ === 0 && tool !== 'inventory'
          ? ['apply_patch_custom', 'apply_patch_foreign'].includes(tool)
            ? { type: 'custom_tool_call', id: 'ctc_probe', call_id: 'call_probe', name: 'apply_patch', input: patch }
            : { type: 'function_call', id: 'fc_probe', call_id: 'call_probe', name: tool === 'approved_mcp' ? 'approved_read'
                : tool === 'rogue_namespace' ? 'rogue_access' : tool === 'functions_exec' ? 'exec'
                  : tool === 'collaboration_spawn' ? 'spawn_agent' : tool,
                ...(tool === 'approved_mcp' ? { namespace: 'mcp__flujo' }
                  : tool === 'rogue_namespace' ? { namespace: 'mcp__rogue' }
                    : tool === 'functions_exec' ? { namespace: 'functions' }
                      : tool === 'collaboration_spawn' ? { namespace: 'collaboration' } : {}),
                arguments: tool === 'approved_mcp' ? '{}' : args }
          : { type: 'message', id: 'msg_done', role: 'assistant', content: [{ type: 'output_text', text: 'Synthetic done.' }] };
        for (const [type, data] of [['response.created', { response: { id: 'resp_probe' } }],
          ['response.output_item.added', { output_index: 0, item }], ['response.output_item.done', { output_index: 0, item }],
          ['response.completed', { response: { id: 'resp_probe', output: [item], usage: { input_tokens: 1, output_tokens: 1, total_tokens: 2 } } }]]) {
          res.write(`data: ${JSON.stringify({ type, ...data })}\n\n`);
        }
        res.end();
      });
    });
    server.on('upgrade',(req,socket,head)=>{
      socket.on('error',()=>{});
      requests.push({method:'UPGRADE',transport:'websocket',path:req.url,authorization:req.headers.authorization==='Bearer synthetic-chatgpt-access',account:req.headers['chatgpt-account-id'],originator:req.headers.originator});
      if(req.url !== '/backend-api/codex/responses') {socket.destroy();return;}
      const accept=createHash('sha1').update(req.headers['sec-websocket-key']+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
      socket.write(`HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`);
      const send=(value,opcode=1)=>{
        const body=Buffer.isBuffer(value)?value:Buffer.from(value);
        const header=Buffer.alloc(body.length <126?2:4);header[0]=0x80|opcode;
        if(body.length<126)header[1]=body.length;else {header[1]=126;header.writeUInt16BE(body.length,2);}
        socket.write(Buffer.concat([header,body]));
      };
      let buffered=head,fragments=[];
      const read=chunk=>{
        buffered=Buffer.concat([buffered,chunk]);
        while(buffered.length>=2){
          const first=buffered[0],opcode=first&15,masked=!!(buffered[1]&128);let length=buffered[1]&127,offset=2;
          if(length===126){if(buffered.length<4)return;length=buffered.readUInt16BE(2);offset=4;}
          else if(length===127){if(buffered.length<10)return;length=Number(buffered.readBigUInt64BE(2));offset=10;}
          if(length>2*1024*1024){socket.destroy();return;}
          if(buffered.length<offset+(masked?4:0)+length)return;
          const mask=masked?buffered.subarray(offset,offset+4):undefined;offset+=masked?4:0;
          const body=Buffer.from(buffered.subarray(offset,offset+length));buffered=buffered.subarray(offset+length);
          if(mask)for(let i=0;i<body.length;i++)body[i]^=mask[i%4];
          if(opcode===8){socket.end();return;}if(opcode===9){send(body,10);continue;}if(opcode===10)continue;
          fragments.push(body);if(!(first&128))continue;
          const message=JSON.parse(Buffer.concat(fragments).toString('utf8'));fragments=[];
          if(message.type!=='response.create'){failures.push({model,tool,unexpectedWebsocketMessage:message.type});socket.destroy();return;}
          const payload=message.response ?? message;
          const mockReq={...req,ws:true,method:'POST',headers:{...req.headers,'content-encoding':undefined},on(event,callback){if(event==='data')callback(Buffer.from(JSON.stringify(payload)));if(event==='end')callback();return this;}};
          const mockRes={writeHead(){},write(value){send(value.slice(6).trim());},end(){}};
          server.emit('request',mockReq,mockRes);
        }
      };
      socket.on('data',read);if(head.length)read(Buffer.alloc(0));
    });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const jwt = `${Buffer.from(JSON.stringify({alg:'none',typ:'JWT'})).toString('base64url')}.${Buffer.from(JSON.stringify({exp:Math.floor(Date.now()/1000)+86400,iat:Math.floor(Date.now()/1000),email:'synthetic@example.invalid','https://api.openai.com/auth':{chatgpt_account_id:'synthetic-account',chatgpt_user_id:'synthetic-user',chatgpt_plan_type:'plus'}})).toString('base64url')}.synthetic`;
    fs.writeFileSync(path.join(home,'auth.json'),JSON.stringify({auth_mode:'chatgpt',OPENAI_API_KEY:null,tokens:{id_token:jwt,access_token:'synthetic-chatgpt-access',refresh_token:'synthetic-chatgpt-refresh',account_id:'synthetic-account'},last_refresh:new Date().toISOString()}),{flag:'wx',mode:0o600});
    const config = [`chatgpt_base_url=${JSON.stringify(localOrigin(server.address().port))}`,
      `openai_base_url=${JSON.stringify(`${localOrigin(server.address().port)}/backend-api/codex`)}`,
      `model="${model}"`, 'web_search="disabled"', 'tools.view_image=false', 'project_doc_max_bytes=0', 'approval_policy="never"',
      'forced_login_method="chatgpt"', 'cli_auth_credentials_store="file"', 'history.persistence="none"',
      'project_root_markers=[]', `projects.${JSON.stringify(neutral)}.trust_level="untrusted"`,
      `mcp_servers.flujo.url=${JSON.stringify(bridge.url)}`,
      'mcp_servers.flujo.default_tools_approval_mode="approve"',
      ...disabled.map(f => `features.${f}=false`), `model_catalog_json=${JSON.stringify(catalogSnapshot)}`];
    const baseNames=['PATH','SystemRoot','SYSTEMROOT','WINDIR','COMSPEC','PATHEXT','LANG','LC_ALL','TZ','TERM','SSL_CERT_FILE','SSL_CERT_DIR'];
    const env=Object.fromEntries(baseNames.flatMap(name=>process.env[name]===undefined?[]:[[name,process.env[name]]]));
    Object.assign(env,privatePaths,{HOME:home,USERPROFILE:home,CODEX_HOME:home,CODEX_INTERNAL_ORIGINATOR_OVERRIDE:'codex_sdk_ts',CODEX_CA_CERTIFICATE:tlsCertificate,SSL_CERT_FILE:tlsCertificate});
    if(process.platform==='win32'){const root=path.parse(home).root;Object.assign(env,{HOMEDRIVE:root.replace(/[\\/]$/,''),HOMEPATH:home.slice(root.length-1)});}
    child = spawn(binary, ['exec', '--experimental-json',
      ...config.flatMap(c => ['--config', c]), '--model',model,'--sandbox','read-only','--cd',neutral,'--skip-git-repo-check',
      '--config','sandbox_workspace_write.network_access=false'], {
      cwd: ancestor, env, stdio: ['pipe', 'pipe', 'pipe'] });
    child.stdin.end('Synthetic router validation only.');
    child.stderr.on('data',value=>stderr+=value);
    child.stdout.on('data',value=>stdout+=value);
    const timer = setTimeout(() => { timedOut = true; child.kill(); }, 15000);
    await new Promise(resolve => child.on('exit', resolve));
    clearTimeout(timer);
    server.close();
    await bridge.close();
    const markerExists = fs.existsSync(path.join(neutral, 'forced-marker.txt'));
    const foreignChanged = fs.readFileSync(foreign, 'utf8') !== sentinel;
    const foreignLeaked = observed.some(value => value.includes(sentinel));
    const denied = tool === 'inventory' || observed.some(value => /unsupported.*call|not available|unavailable|unknown tool/i.test(value)
      || (['list_mcp_resources', 'list_mcp_resource_templates', 'read_mcp_resource'].includes(tool)
        && /unknown.*server|server.*not found|not configured|method.*not found|does not support.*resource|resources.*not supported/i.test(value)));
    const approvedCalled = fs.existsSync(approvedMarker);
    const rogueCalled = fs.existsSync(rogueMarker);
    const inventorySafe = names.some(name => ['mcp__flujo.approved_read', 'mcp__flujo__approved_read'].includes(name))
      && names.every(name => ['request_user_input', 'list_mcp_resources', 'list_mcp_resource_templates',
        'read_mcp_resource', 'mcp__flujo.approved_read', 'mcp__flujo__approved_read'].includes(name));
    const approved = tool === 'approved_mcp' ? approvedCalled && observed.some(value => value.includes('SYNTHETIC_APPROVED_READ')) : denied;
    const inferenceRequests = requests.filter(request => request.method === 'POST');
    const routeSafe = inferenceRequests.length > 0 && inferenceRequests.every(request => request.transport === 'websocket' && request.originator === 'codex_sdk_ts' && request.path === '/backend-api/codex/responses' && request.authorization === true && request.account === 'synthetic-account' && request.model === model && !request.responsesLite && request.keys.includes('tools'));
    const bridgeSafe = tool === 'approved_mcp' ? bridgeCalls.length === 1 && bridgeCalls[0].argumentKeys.length === 0 : bridgeCalls.length === 0;
    const passed = bridgeSafe && routeSafe && !timedOut && !markerExists && !foreignChanged && !foreignLeaked && !rogueCalled && approved && inventorySafe && round > 0;
    console.log(JSON.stringify({ model, tool, startup:{args:child.spawnargs.slice(1),spawnCwd:ancestor,home,workingDirectory:neutral,environmentKeys:Object.keys(env).sort(),privatePaths,catalogSnapshotSha256:createHash('sha256').update(fs.readFileSync(catalogSnapshot)).digest('hex')},bridgeTransport:'production StreamableHTTP',bridgeToolFilter:'none',bridgeCalls,bridgeSafe,requests, routeSafe, names, outputs: observed, ...(!passed ? {stderr,stdout} : {}), markerExists, foreignChanged, foreignLeaked, approvedCalled, rogueCalled, timedOut, passed }));
    if (!passed) failures.push({ model, tool });
    if (path.dirname(path.resolve(ancestor)) !== path.resolve(os.tmpdir()) || !path.basename(ancestor).startsWith('flujo-codex-restricted-probe-')) throw new Error('Unsafe fixture cleanup');
    fs.rmSync(ancestor, { recursive: true, force: true });
  }
}
console.log(JSON.stringify({ failures }));
if (path.dirname(path.resolve(tlsRoot)) !== path.resolve(os.tmpdir()) || !path.basename(tlsRoot).startsWith('dispute-public-native-fixture-')) throw new Error('Unsafe TLS fixture cleanup');
fs.rmSync(tlsRoot, { recursive: true, force: true });
process.exitCode = failures.length ? 1 : 0;

