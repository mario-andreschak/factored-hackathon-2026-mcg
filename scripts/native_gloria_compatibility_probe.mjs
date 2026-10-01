/** Availability probe only; full graph/MCP qualification is a separate run. */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { spawn, spawnSync } from 'node:child_process';
const [binary, catalog, model] = process.argv.slice(2);
const home = fs.mkdtempSync(path.join(os.tmpdir(), 'gloria-native-compat-'));
const workspace = path.join(home, 'workspace');
const disabled = ['shell_tool', 'unified_exec', 'multi_agent', 'multi_agent_v2', 'apps', 'plugins', 'browser_use',
  'browser_use_external', 'computer_use', 'code_mode', 'code_mode_host', 'image_generation', 'memories', 'hooks',
  'skill_search', 'tool_suggest', 'workspace_dependencies', 'goals', 'in_app_browser', 'sleep_tool', 'view_image',
  'auth_elicitation', 'tool_call_mcp_elicitation', 'default_mode_request_user_input'];
fs.mkdirSync(workspace); fs.copyFileSync('/auth/auth.json', path.join(home, 'auth.json'));
fs.copyFileSync(catalog, path.join(home, 'model-catalog.json'));
fs.writeFileSync(path.join(home, 'config.toml'), 'cli_auth_credentials_store = "file"\n');
const environment = Object.fromEntries(['PATH', 'LANG', 'LC_ALL', 'TZ', 'TERM', 'SSL_CERT_FILE', 'SSL_CERT_DIR']
  .flatMap(key => process.env[key] === undefined ? [] : [[key, process.env[key]]]));
for (const key of ['APPDATA', 'LOCALAPPDATA', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_DATA_HOME', 'XDG_STATE_HOME',
  'XDG_RUNTIME_DIR', 'TMPDIR', 'TMP', 'TEMP']) { const directory = path.join(home, key); fs.mkdirSync(directory); environment[key] = directory; }
Object.assign(environment, { HOME: home, USERPROFILE: home, CODEX_HOME: home, CODEX_INTERNAL_ORIGINATOR_OVERRIDE: 'codex_sdk_ts' });
const config = ['forced_login_method="chatgpt"', 'cli_auth_credentials_store="file"', 'web_search="disabled"',
  'project_doc_max_bytes=0', 'history.persistence="none"', 'tools.view_image=false', 'project_root_markers=[]',
  'sandbox_workspace_write.network_access=false', `model_catalog_json=${JSON.stringify(path.join(home, 'model-catalog.json'))}`,
  ...disabled.map(key => `features.${key}=false`)];
const child = spawn(binary, ['exec', '--experimental-json', ...config.flatMap(value => ['--config', value]),
  '--model', model, '--sandbox', 'read-only', '--cd', workspace, '--skip-git-repo-check'], { cwd: workspace,
  env: environment, stdio: ['pipe', 'pipe', 'pipe'] });
child.stdin.end('Return exactly the JSON object {"ready":true}. Do not use any tool.');
let stdout = '', stderr = '', timeout = false;
child.stdout.on('data', value => stdout += value); child.stderr.on('data', value => stderr += value);
const timer = setTimeout(() => { timeout = true; child.kill(); }, 90000);
const exit = await new Promise(resolve => child.on('exit', resolve)); clearTimeout(timer);
const rows = stdout.split('\n').flatMap(line => { try { return [JSON.parse(line)]; } catch { return []; } });
console.log(JSON.stringify({ model, version: spawnSync(binary, ['--version'], { encoding: 'utf8' }).stdout.trim(),
  binarySha256: createHash('sha256').update(fs.readFileSync(binary)).digest('hex'),
  catalogSha256: createHash('sha256').update(fs.readFileSync(catalog)).digest('hex'), exit, timeout,
  events: rows, stderr, availabilityOnly: true }));
if (path.dirname(path.resolve(home)) !== path.resolve(os.tmpdir()) || !path.basename(home).startsWith('gloria-native-compat-')) throw new Error('Unsafe compatibility cleanup');
fs.rmSync(home, { recursive: true, force: true });
process.exitCode = exit === 0 && !timeout ? 0 : 1;
