#!/usr/bin/env node
/** Export committed public application source with a complete physical inventory. */
import { execFileSync } from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';

const prefixes = ['banking_mcp/', 'dispute_workflow/', 'pipeline/', 'frontend/server/',
  'resources/', 'contracts/', 'config/', 'deploy/local-dispute/'];
const fixed = new Set(['requirements-dispute.txt', 'requirements-pipeline.txt', 'frontend/requirements.txt',
  'scripts/run_dispute.py', 'scripts/local_dispute_demo.py', 'scripts/qualify_dispute_app.py',
  'scripts/native_dispute_qualification.py', 'scripts/native_dispute_qualification.ts',
  'scripts/native_dispute_qualification.mjs', 'frontend/server/deployment_transition.py',
  'deploy/fly/runtime.mjs']);
const manifestName = 'local-source-manifest.json';
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const samePath = (left, right) => process.platform === 'win32'
  ? path.resolve(left).toLowerCase() === path.resolve(right).toLowerCase()
  : path.resolve(left) === path.resolve(right);

function ancestors(filename) {
  const result = [];
  for (let current = filename; ; current = path.dirname(current)) {
    result.unshift(current);
    if (path.dirname(current) === current) return result;
  }
}

// lstat identifies symlinks and junctions, but not every Windows reparse type.
// Inspect FileAttributes and the actual owner SID; paths are data, not script.
function windowsPhysicalChecks(filenames, owned = new Set()) {
  if (process.platform !== 'win32') return;
  const script = `$ErrorActionPreference='Stop';try {
    $sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value;
    $trusted=@($sid,'S-1-5-18','S-1-5-32-544',
      'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464');
    foreach($entry in (ConvertFrom-Json $env:SAVIA_EXPORT_PHYSICAL_PATHS)) {
      $item=Get-Item -LiteralPath $entry.path -Force;
      if(($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Reparse path refused' };
      $acl=Get-Acl -LiteralPath $entry.path;
      $owner=$acl.GetOwner([Security.Principal.SecurityIdentifier]).Value;
      if(($entry.owned -and $owner -ne $sid) -or $trusted -notcontains $owner) { throw 'Trusted physical owner required' };
      foreach($rule in $acl.Access) {
        if($rule.AccessControlType -ne 'Allow' -or
           ($rule.PropagationFlags -band [Security.AccessControl.PropagationFlags]::InheritOnly) -ne 0) { continue };
        $ruleSid=$rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value;
        if($trusted -contains $ruleSid) { continue };
        # Existing system ancestors may allow new subdirectories (C:\\ does).
        # They must forbid modifying/deleting existing entries or ACL authority.
        # An owned export parent/tree also forbids untrusted child creation.
        $mutation=0x10000000 -bor 0x40000000 -bor 0x000D0152;
        if($entry.owned) { $mutation=$mutation -bor 0x00000004 };
        if(([int64]$rule.FileSystemRights -band $mutation) -ne 0) { throw 'Untrusted path write authority refused' };
      };
    };
    exit 0;
  } catch { [Console]::Error.WriteLine('Physical export path inspection failed.'); exit 1 }`;
  for (let offset = 0; offset < filenames.length; offset += 32) {
    const entries = filenames.slice(offset, offset + 32).map(filename => ({
      path: filename, owned: owned.has(filename),
    }));
    const options = { env: { ...process.env, SAVIA_EXPORT_PHYSICAL_PATHS: JSON.stringify(entries) },
      timeout: 15000, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] };
    const arguments_ = ['-NoProfile', '-NonInteractive', '-EncodedCommand',
      Buffer.from(script, 'utf16le').toString('base64')];
    try { execFileSync('pwsh.exe', arguments_, options); }
    catch (error) {
      if (error.code !== 'ENOENT') throw Error('Physical Windows export path inspection failed.', { cause: error });
      try { execFileSync('powershell.exe', arguments_, options); }
      catch (fallback) { throw Error('Physical Windows export path inspection failed.', { cause: fallback }); }
    }
  }
}

async function physicalDirectory(filename, { owned = false } = {}) {
  const stat = await fs.lstat(filename);
  if (!stat.isDirectory() || stat.isSymbolicLink() || !samePath(await fs.realpath(filename), filename))
    throw Error('Physical export directory required.');
  if (process.platform !== 'win32') {
    const caller = process.getuid(), systemSticky = !owned && stat.uid === 0 && (stat.mode & 0o1000) !== 0;
    if ((owned && stat.uid !== caller) || (stat.uid !== caller && stat.uid !== 0)
      || ((stat.mode & 0o022) !== 0 && !systemSticky)) throw Error('Trusted owned export directory required.');
  }
  return stat;
}

async function inspectAncestors(filename, { owned = false } = {}) {
  const chain = ancestors(filename);
  for (const ancestor of chain) await physicalDirectory(ancestor, { owned: owned && ancestor === filename });
  windowsPhysicalChecks(chain, owned ? new Set([filename]) : new Set());
}

async function prepareParent(parent) {
  // Never recursively create directories through a link. The nearest existing
  // parent and every newly created parent must belong to the caller.
  const missing = [];
  let existing = parent;
  for (;;) {
    try { await fs.lstat(existing); break; }
    catch (error) {
      if (error.code !== 'ENOENT' || path.dirname(existing) === existing) throw error;
      missing.unshift(existing); existing = path.dirname(existing);
    }
  }
  await inspectAncestors(existing, { owned: true });
  for (const directory of missing) {
    await inspectAncestors(path.dirname(directory), { owned: true });
    await fs.mkdir(directory); // EEXIST refuses even concurrent creation.
    await inspectAncestors(directory, { owned: true });
  }
  await inspectAncestors(parent, { owned: true });
}

function safeSourceName(name) {
  return name && !/[\\\x00-\x1f<>:"|?*]/.test(name) && name.split('/').every(part =>
    part && part !== '.' && part !== '..' && !/[. ]$/.test(part)
    && !/^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(part));
}

function expectedDirectories(names) {
  const directories = new Set();
  for (const name of names) {
    const parts = name.split('/'); parts.pop();
    for (let count = 1; count <= parts.length; count++) directories.add(parts.slice(0, count).join('/'));
  }
  return directories;
}

/** Verify exactly the manifest, declared files and their parent directories. */
export async function verifyExportInventory(destination, manifest) {
  const root = path.resolve(destination);
  await inspectAncestors(root, { owned: true });
  const encoded = Buffer.from(JSON.stringify(manifest, null, 2) + '\n');
  const expectedFiles = new Map(Object.entries(manifest.files));
  expectedFiles.set(manifestName, digest(encoded));
  const expectedDirs = expectedDirectories(expectedFiles.keys());
  const observedFiles = new Set(), observedDirs = new Set();
  async function visit(directory, relative = '') {
    await physicalDirectory(directory, { owned: true });
    const names = await fs.readdir(directory);
    const entries = names.map(name => path.join(directory, name));
    windowsPhysicalChecks(entries, new Set(entries));
    for (const name of names) {
      const filename = path.join(directory, name), entry = relative ? relative + '/' + name : name;
      const before = await fs.lstat(filename);
      if (before.isSymbolicLink()) throw Error('Linked export entry refused.');
      if (before.isDirectory()) {
        if (!expectedDirs.has(entry)) throw Error('Unexpected export directory.');
        observedDirs.add(entry); await visit(filename, entry);
      } else {
        if (!before.isFile() || before.nlink !== 1 || !expectedFiles.has(entry)
          || !samePath(await fs.realpath(filename), filename)) throw Error('Unexpected or linked export file.');
        if (process.platform !== 'win32' && (before.uid !== process.getuid() || (before.mode & 0o022) !== 0))
          throw Error('Owned export file without shared write authority required.');
        const bytes = await fs.readFile(filename), after = await fs.lstat(filename);
        if (after.isSymbolicLink() || !after.isFile() || after.nlink !== 1
          || before.dev !== after.dev || before.ino !== after.ino || before.size !== after.size
          || before.uid !== after.uid || before.mode !== after.mode
          || (process.platform !== 'win32' && (after.uid !== process.getuid() || (after.mode & 0o022) !== 0))
          || before.mtimeMs !== after.mtimeMs || before.ctimeMs !== after.ctimeMs
          || bytes.length !== after.size || digest(bytes) !== expectedFiles.get(entry))
          throw Error('Export file changed or content differs.');
        observedFiles.add(entry);
      }
    }
  }
  await visit(root);
  await inspectAncestors(root, { owned: true });
  if (observedFiles.size !== expectedFiles.size || observedDirs.size !== expectedDirs.size)
    throw Error('Export inventory incomplete.');
  return { fileCount: observedFiles.size - 1, directoryCount: observedDirs.size };
}

export async function exportCommittedSource({ destination, ref = 'HEAD', repository = process.cwd() }) {
  if (!destination) throw Error('Destination directory required.');
  const git = arguments_ => execFileSync('git', arguments_, { cwd: repository, maxBuffer: 16 * 1024 * 1024 });
  const revision = git(['rev-parse', '--verify', '--end-of-options', ref + '^{commit}']).toString('utf8').trim();
  if (!/^[a-f0-9]{40}$/.test(revision)) throw Error('Committed source revision required.');
  const tree = git(['ls-tree', '-rz', '--full-tree', revision]);
  if (!Buffer.from(tree.toString('utf8')).equals(tree)) throw Error('UTF-8 committed source paths required.');
  const entries = tree.toString('utf8').split('\0').filter(Boolean);
  const files = [], names = new Set();
  for (const entry of entries) {
    const separator = entry.indexOf('\t'), name = entry.slice(separator + 1);
    if (!fixed.has(name) && !prefixes.some(prefix => name.startsWith(prefix))) continue;
    if (separator < 0 || !safeSourceName(name) || !/^(?:100644|100755) blob [a-f0-9]{40}$/.test(entry.slice(0, separator))
      || names.has(name.toLowerCase())) throw Error('Unsafe or linked committed source path.');
    names.add(name.toLowerCase()); files.push(name);
  }
  if (!files.includes('scripts/local_dispute_demo.py')) throw Error('Commit the local launcher before exporting.');
  const root = path.resolve(destination), hashes = {};
  if (root === path.parse(root).root || root.startsWith('\\\\')) throw Error('Local export destination required.');
  // Prepare the full expected committed inventory before any destination
  // mutation. A prior preparation is reusable only after every entry verifies.
  for (const name of files) hashes[name] = digest(git(['show', revision + ':' + name]));
  const manifest = { schema: 'local-dispute-source/v1', revision, files: hashes,
    scope: 'committed application overlay; native worker and UI assets remain identified by image digest' };
  let exists = false;
  try { await fs.lstat(root); exists = true; }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  if (exists) {
    await inspectAncestors(path.dirname(root), { owned: true });
    const inventory = await verifyExportInventory(root, manifest);
    return { revision, ...inventory, destination: root, reused: true };
  }
  await prepareParent(path.dirname(root));
  await fs.mkdir(root);
  await inspectAncestors(root, { owned: true });
  const directories = expectedDirectories(files), created = [root];
  for (const name of [...directories].sort((left, right) => left.split('/').length - right.split('/').length || left.localeCompare(right))) {
    const directory = path.join(root, ...name.split('/'));
    await physicalDirectory(path.dirname(directory), { owned: true });
    await fs.mkdir(directory);
    await physicalDirectory(directory, { owned: true });
    created.push(directory);
  }
  windowsPhysicalChecks(created, new Set(created));
  for (const name of files) {
    const filename = path.join(root, ...name.split('/'));
    await physicalDirectory(path.dirname(filename), { owned: true });
    const bytes = git(['show', revision + ':' + name]);
    if (digest(bytes) !== hashes[name]) throw Error('Committed source blob changed.');
    await fs.writeFile(filename, bytes, { flag: 'wx' });
  }
  await fs.writeFile(path.join(root, manifestName), JSON.stringify(manifest, null, 2) + '\n', { flag: 'wx' });
  const inventory = await verifyExportInventory(root, manifest);
  return { revision, ...inventory, destination: root, reused: false };
}

if (process.argv[1] && samePath(fileURLToPath(import.meta.url), process.argv[1])) {
  const [destination, ref = 'HEAD'] = process.argv.slice(2);
  console.log(JSON.stringify(await exportCommittedSource({ destination, ref })));
}
