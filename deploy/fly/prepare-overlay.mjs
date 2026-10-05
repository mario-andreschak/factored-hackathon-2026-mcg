#!/usr/bin/env node
import { execFile, spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { createReadStream, createWriteStream } from 'node:fs';
import fs from 'node:fs/promises';
import path from 'node:path';
import { pipeline } from 'node:stream/promises';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';

const execute = promisify(execFile);
const directory = path.dirname(fileURLToPath(import.meta.url));
const overlay = path.join(directory, '.overlay');
const publicBase = 'ghcr.io/mario-andreschak/flujo@sha256:3c1f028c41e6eaff3852aedc52d49a51f733ea7f274ff187a705fa9d0cd950d8';
const workerReference = process.env.FLUJO_OVERLAY_WORKER_IMAGE || 'flujo-slack-worker:turn-provenance-20260930';
const frontendReference = process.env.FLUJO_OVERLAY_FRONTEND_IMAGE || 'hackathon-banking-frontend:local';

async function docker(args, options = {}) {
  const result = await execute('docker', args, { maxBuffer: 32 * 1024 * 1024, windowsHide: true, ...options });
  return result.stdout.trim();
}

async function imageMetadata(reference) {
  const data = JSON.parse(await docker(['image', 'inspect', reference]))[0];
  return { reference, id: data.Id, labels: data.Config.Labels || {}, rootfs: data.RootFS.Layers };
}

async function archive(container, source, destination) {
  const filename = path.join(overlay, destination);
  await fs.mkdir(path.dirname(filename), { recursive: true });
  const child = spawn('docker', ['cp', `${container}:${source}`, '-'], { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
  let errors = '';
  child.stderr.on('data', chunk => { errors = (errors + chunk.toString()).slice(-2048); });
  const completed = new Promise((resolve, reject) => {
    child.once('error', reject);
    child.once('close', code => code === 0 ? resolve() : reject(new Error(`Could not archive immutable image path ${source}.`)));
  });
  await Promise.all([pipeline(child.stdout, createWriteStream(filename)), completed]);
}

async function copyFile(container, source, destination) {
  const filename = path.join(overlay, destination);
  await fs.mkdir(path.dirname(filename), { recursive: true });
  await docker(['cp', `${container}:${source}`, filename]);
}

const fingerprintScript = String.raw`
const fs=require('node:fs');const path=require('node:path');const {createHash}=require('node:crypto');
const roots=JSON.parse(process.argv[1]);const entries=[];
function visit(filename){const metadata=fs.lstatSync(filename);if(metadata.isSymbolicLink()){entries.push({path:filename,type:'symlink',target:fs.readlinkSync(filename),mode:metadata.mode&511});return;}if(metadata.isDirectory()){for(const name of fs.readdirSync(filename).sort())visit(path.join(filename,name));return;}if(!metadata.isFile())throw new Error('Unsupported immutable artifact type');entries.push({path:filename,type:'file',size:metadata.size,mode:metadata.mode&511,sha256:createHash('sha256').update(fs.readFileSync(filename)).digest('hex')});}
for(const root of roots)visit(root);entries.sort((a,b)=>a.path.localeCompare(b.path));console.log(JSON.stringify(entries));
`;

async function fingerprints(image, paths) {
  return JSON.parse(await docker(['run', '--rm', '--read-only', '--network', 'none', '--entrypoint', 'node', image, '-e', fingerprintScript, JSON.stringify(paths)]));
}

async function fileHash(filename) {
  const hash = createHash('sha256');
  for await (const chunk of createReadStream(filename)) hash.update(chunk);
  return hash.digest('hex');
}

async function main() {
  const worker = await imageMetadata(workerReference);
  const frontend = await imageMetadata(frontendReference);
  const containers = [];
  await fs.mkdir(overlay, { recursive: true });
  try {
    const workerContainer = await docker(['create', '--entrypoint', 'true', worker.id]);
    containers.push(workerContainer);
    const frontendContainer = await docker(['create', '--entrypoint', 'true', frontend.id]);
    containers.push(frontendContainer);
    // These allowlists deliberately contain only immutable application assets.
    // Tar streams retain Linux ownership, executable bits and npm symlinks even
    // when this script runs on Windows. No live volume or secret path is read.
    const workerArchives = [
      ['/app/.next', 'app/next.tar'], ['/app/scripts', 'app/scripts.tar'],
      ['/app/mcp-servers', 'app/mcp-servers.tar'], ['/app/github', 'app/github.tar'],
      ['/app/public', 'app/public.tar'], ['/app/node_modules/jose', 'app/jose.tar'],
      ['/app/node_modules/canonicalize', 'app/canonicalize.tar'],
      ['/opt/banking-mcp/banking_mcp', 'banking/banking_mcp.tar'],
      ['/opt/banking-mcp/pipeline', 'banking/pipeline.tar'],
      ['/opt/banking-mcp/scripts', 'banking/scripts.tar'],
    ];
    for (const [source, destination] of workerArchives) await archive(workerContainer, source, destination);
    for (const name of ['package.json', 'package-lock.json', 'next.config.mjs']) await copyFile(workerContainer, `/app/${name}`, `app/${name}`);
    for (const name of ['requirements-mcp.txt', 'requirements-pipeline.txt', 'requirements-s3.txt']) await copyFile(workerContainer, `/opt/banking-mcp/${name}`, `banking/${name}`);
    await archive(frontendContainer, '/app/server', 'savia/server.tar');
    await archive(frontendContainer, '/app/dist', 'savia/dist.tar');
    await copyFile(frontendContainer, '/app/requirements.txt', 'savia/requirements.txt');

    const freezeScript = 'import importlib.metadata,json;print(json.dumps(sorted([[d.metadata["Name"],d.version] for d in importlib.metadata.distributions()],key=lambda x:x[0].lower())))';
    const installed = JSON.parse(await docker(['run', '--rm', '--read-only', '--network', 'none', '--entrypoint', '/opt/banking-mcp/.venv/bin/python', worker.id, '-c', freezeScript]));
    const locked = installed.filter(([name]) => !['pip', 'setuptools', 'wheel'].includes(name.toLowerCase()));
    await fs.writeFile(path.join(overlay, 'banking', 'requirements.lock'), `${locked.map(([name, version]) => `${name}==${version}`).join('\n')}\n`);

    const workerPaths = workerArchives.map(([source]) => source).concat(
      ['/app/package.json', '/app/package-lock.json', '/app/next.config.mjs'],
      ['requirements-mcp.txt', 'requirements-pipeline.txt', 'requirements-s3.txt'].map(name => `/opt/banking-mcp/${name}`),
    );
    const workerFiles = await fingerprints(worker.id, workerPaths);
    // The frontend image has Python instead of Node; derive its fingerprints
    // with standard-library hashing without installing anything in that image.
    const frontendFingerprintScript = String.raw`import os,json,hashlib,stat
entries=[]
for root in ["/app/server","/app/dist","/app/requirements.txt"]:
 paths=[root] if os.path.isfile(root) else [os.path.join(d,n) for d,_,names in os.walk(root) for n in names]
 for p in paths:
  s=os.lstat(p)
  entries.append({"path":p,"type":"file","size":s.st_size,"mode":stat.S_IMODE(s.st_mode),"sha256":hashlib.sha256(open(p,"rb").read()).hexdigest()})
print(json.dumps(sorted(entries,key=lambda x:x["path"])))`;
    const frontendFiles = JSON.parse(await docker(['run', '--rm', '--read-only', '--network', 'none', '--entrypoint', 'python', frontend.id, '-c', frontendFingerprintScript]));
    const artifacts = [];
    for (const folder of ['app', 'banking', 'savia']) {
      for (const name of (await fs.readdir(path.join(overlay, folder))).sort()) {
        const filename = path.join(overlay, folder, name);
        artifacts.push({ path: `${folder}/${name}`, bytes: (await fs.stat(filename)).size, sha256: await fileHash(filename) });
      }
    }
    const manifest = {
      version: 1, preparedAt: new Date().toISOString(), publicBase,
      worker, frontend, workerFiles, frontendFiles, bankingDependencies: installed, artifacts,
    };
    await fs.writeFile(path.join(overlay, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);
    const bytes = artifacts.reduce((sum, artifact) => sum + artifact.bytes, 0);
    console.log(JSON.stringify({ overlayPrepared: true, workerImage: worker.id, frontendImage: frontend.id, artifacts: artifacts.length, immutableFiles: workerFiles.length + frontendFiles.length, bytes }));
  } finally {
    for (const container of containers.reverse()) {
      if (/^[a-f0-9]{64}$/.test(container)) await docker(['rm', container]).catch(() => undefined);
    }
  }
}

main().catch(error => { console.error(`Overlay preparation failed: ${error.message}`); process.exitCode = 1; });
