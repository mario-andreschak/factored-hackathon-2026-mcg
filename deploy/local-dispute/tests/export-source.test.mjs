import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { exportCommittedSource, verifyExportInventory } from '../export-source.mjs';

async function repositoryFixture(t) {
  const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'savia-public-export-'));
  t.after(() => fs.rm(temporary, { recursive: true, force: true }));
  const repository = path.join(temporary, 'repository'); await fs.mkdir(repository);
  const files = {
    'scripts/local_dispute_demo.py': 'print("committed launcher")\n',
    'dispute_workflow/owned.py': 'PUBLIC = "committed"\n',
    'banking_mcp/public.py': 'PUBLIC = True\n',
    'frontend/server/public.py': 'PUBLIC = True\n',
    'deploy/local-dispute/public.mjs': 'export const publicSource = true;\n',
    'requirements-dispute.txt': 'public-dependency\n',
    'private-credential.env': 'must never be exported\n',
  };
  for (const [name, contents] of Object.entries(files)) {
    const filename = path.join(repository, ...name.split('/'));
    await fs.mkdir(path.dirname(filename), { recursive: true }); await fs.writeFile(filename, contents);
  }
  const git = args => execFileSync('git', args, { cwd: repository, stdio: ['ignore', 'pipe', 'pipe'] });
  git(['init', '--quiet']); git(['add', '--all']);
  git(['-c', 'user.name=Export regression', '-c', 'user.email=export@example.invalid',
    '-c', 'commit.gpgSign=false', 'commit', '--quiet', '-m', 'Public fixture']);
  const revision = git(['rev-parse', 'HEAD']).toString('utf8').trim();
  return { temporary, repository, revision, files };
}

test('fresh export contains every allowed committed file and no working-tree or unlisted content', async t => {
  const fixture = await repositoryFixture(t), destination = path.join(fixture.temporary, 'new-parent', 'source');
  await fs.writeFile(path.join(fixture.repository, 'dispute_workflow/owned.py'), 'uncommitted replacement\n');
  await fs.writeFile(path.join(fixture.repository, 'dispute_workflow/untracked-secret.env'), 'untracked secret\n');
  const result = await exportCommittedSource({ destination, repository: fixture.repository });
  assert.equal(result.revision, fixture.revision); assert.equal(result.fileCount, 6); assert.equal(result.reused, false);
  for (const [name, contents] of Object.entries(fixture.files)) {
    if (name === 'private-credential.env') continue;
    assert.equal(await fs.readFile(path.join(destination, ...name.split('/')), 'utf8'), contents);
  }
  await assert.rejects(fs.lstat(path.join(destination, 'private-credential.env')), { code: 'ENOENT' });
  await assert.rejects(fs.lstat(path.join(destination, 'dispute_workflow/untracked-secret.env')), { code: 'ENOENT' });
  const manifest = JSON.parse(await fs.readFile(path.join(destination, 'local-source-manifest.json'), 'utf8'));
  assert.deepEqual(await verifyExportInventory(destination, manifest), { fileCount: 6, directoryCount: 7 });
});

test('prepare then start can reuse only the exact complete committed physical export without rewriting', async t => {
  const fixture = await repositoryFixture(t), destination = path.join(fixture.temporary, 'prepared-source');
  const initial = await exportCommittedSource({ destination, repository: fixture.repository });
  const filename = path.join(destination, 'dispute_workflow/owned.py'), before = await fs.lstat(filename);
  const manifest = await fs.readFile(path.join(destination, 'local-source-manifest.json'));
  const repeated = await exportCommittedSource({ destination, repository: fixture.repository });
  assert.deepEqual(repeated, { ...initial, reused: true });
  const after = await fs.lstat(filename);
  for (const field of ['dev', 'ino', 'mtimeMs', 'ctimeMs', 'size']) assert.equal(after[field], before[field]);
  assert.deepEqual(await fs.readFile(path.join(destination, 'local-source-manifest.json')), manifest);
});

test('a preexisting export with matching declared bytes and an unexpected file is refused unchanged', async t => {
  const fixture = await repositoryFixture(t), destination = path.join(fixture.temporary, 'existing-source');
  await exportCommittedSource({ destination, repository: fixture.repository });
  const sentinel = path.join(destination, 'unexpected-secret.env'); await fs.writeFile(sentinel, 'leave me unchanged\n');
  const manifest = await fs.readFile(path.join(destination, 'local-source-manifest.json'));
  await assert.rejects(exportCommittedSource({ destination, repository: fixture.repository }), /Unexpected or linked export file/);
  assert.equal(await fs.readFile(sentinel, 'utf8'), 'leave me unchanged\n');
  assert.deepEqual(await fs.readFile(path.join(destination, 'local-source-manifest.json')), manifest);
});

test('a linked ancestor is rejected before writing through it, preserving the outside sentinel', async t => {
  const fixture = await repositoryFixture(t), outside = path.join(fixture.temporary, 'outside');
  await fs.mkdir(outside); await fs.writeFile(path.join(outside, 'sentinel'), 'outside unchanged\n');
  const linkedParent = path.join(fixture.temporary, 'linked-parent');
  await fs.symlink(outside, linkedParent, process.platform === 'win32' ? 'junction' : 'dir');
  await assert.rejects(exportCommittedSource({ destination: path.join(linkedParent, 'source'),
    repository: fixture.repository }), /Physical export directory/);
  assert.deepEqual(await fs.readdir(outside), ['sentinel']);
  assert.equal(await fs.readFile(path.join(outside, 'sentinel'), 'utf8'), 'outside unchanged\n');
});

test('matching file bytes reached through a symlink cannot authorize destination reuse', async t => {
  const fixture = await repositoryFixture(t), outside = path.join(fixture.temporary, 'outside-source');
  await exportCommittedSource({ destination: outside, repository: fixture.repository });
  const sentinel = path.join(outside, 'sentinel'); await fs.writeFile(sentinel, 'outside unchanged\n');
  const destination = path.join(fixture.temporary, 'linked-source');
  await fs.symlink(outside, destination, process.platform === 'win32' ? 'junction' : 'dir');
  const before = await fs.readFile(path.join(outside, 'local-source-manifest.json'));
  await assert.rejects(exportCommittedSource({ destination, repository: fixture.repository }), /Physical export directory/);
  assert.deepEqual(await fs.readFile(path.join(outside, 'local-source-manifest.json')), before);
  assert.equal(await fs.readFile(sentinel, 'utf8'), 'outside unchanged\n');
});

test('individual matching declared-file symlink refuses reuse and inventory without changing outside bytes', async t => {
  const fixture = await repositoryFixture(t), destination = path.join(fixture.temporary, 'file-symlink-inventory');
  await exportCommittedSource({ destination, repository: fixture.repository });
  const manifestBytes = await fs.readFile(path.join(destination, 'local-source-manifest.json'));
  const manifest = JSON.parse(manifestBytes);
  const declared = path.join(destination, 'banking_mcp/public.py'), outside = path.join(fixture.temporary, 'outside-public.py');
  await fs.rename(declared, outside);
  try { await fs.symlink(outside, declared, 'file'); }
  catch (error) {
    if (process.platform === 'win32' && ['EPERM', 'EACCES', 'ENOTSUP'].includes(error.code)) {
      t.skip('Windows host does not permit file symlink creation; supported Linux still executes this regression.'); return;
    }
    throw error;
  }
  await assert.rejects(exportCommittedSource({ destination, repository: fixture.repository }),
    /Linked export entry|Physical Windows export path inspection/);
  await assert.rejects(verifyExportInventory(destination, manifest),
    /Linked export entry|Physical Windows export path inspection/);
  assert.equal(await fs.readFile(outside, 'utf8'), fixture.files['banking_mcp/public.py']);
  assert.deepEqual(await fs.readFile(path.join(destination, 'local-source-manifest.json')), manifestBytes);
  assert.equal((await fs.lstat(declared)).isSymbolicLink(), true);
});

test('complete inventory rejects unknown files or empty directories, plus missing or altered declared bytes', async t => {
  const fixture = await repositoryFixture(t), destination = path.join(fixture.temporary, 'inventory');
  await exportCommittedSource({ destination, repository: fixture.repository });
  const manifest = JSON.parse(await fs.readFile(path.join(destination, 'local-source-manifest.json'), 'utf8'));
  const unexpected = path.join(destination, 'unlisted.env'); await fs.writeFile(unexpected, 'not allowed\n');
  await assert.rejects(verifyExportInventory(destination, manifest), /Unexpected or linked export file/);
  await fs.unlink(unexpected);
  const unexpectedDirectory = path.join(destination, 'unlisted-directory'); await fs.mkdir(unexpectedDirectory);
  await assert.rejects(verifyExportInventory(destination, manifest), /Unexpected export directory/);
  await fs.rmdir(unexpectedDirectory);
  const declared = path.join(destination, 'banking_mcp/public.py');
  await fs.writeFile(declared, 'changed bytes\n');
  await assert.rejects(verifyExportInventory(destination, manifest), /Export file changed or content differs/);
  await fs.unlink(declared);
  await assert.rejects(verifyExportInventory(destination, manifest), /Export inventory incomplete/);
});

test('complete inventory rejects matching declared bytes hard-linked outside the export', async t => {
  const fixture = await repositoryFixture(t), destination = path.join(fixture.temporary, 'hard-linked-inventory');
  await exportCommittedSource({ destination, repository: fixture.repository });
  const manifest = JSON.parse(await fs.readFile(path.join(destination, 'local-source-manifest.json'), 'utf8'));
  const declared = path.join(destination, 'banking_mcp/public.py'), outside = path.join(fixture.temporary, 'outside-public.py');
  await fs.rename(declared, outside); await fs.link(outside, declared);
  await assert.rejects(verifyExportInventory(destination, manifest), /Unexpected or linked export file/);
  assert.equal(await fs.readFile(outside, 'utf8'), fixture.files['banking_mcp/public.py']);
});

test('POSIX shared-writable declared file refuses reuse and inventory without repairing modes or bytes',
  { skip: process.platform === 'win32' ? 'POSIX mode authority is checked by actual Linux execution; Windows uses ACL authority.' : false },
  async t => {
    const fixture = await repositoryFixture(t), destination = path.join(fixture.temporary, 'shared-writable-inventory');
    await exportCommittedSource({ destination, repository: fixture.repository });
    const declared = path.join(destination, 'banking_mcp/public.py'), original = await fs.lstat(declared);
    const manifestBytes = await fs.readFile(path.join(destination, 'local-source-manifest.json'));
    const manifest = JSON.parse(manifestBytes), declaredBytes = await fs.readFile(declared);
    const outside = path.join(fixture.temporary, 'outside-sentinel'); await fs.writeFile(outside, 'outside unchanged\n');
    try {
      await fs.chmod(declared, 0o666);
      await assert.rejects(exportCommittedSource({ destination, repository: fixture.repository }), /shared write authority/);
      await assert.rejects(verifyExportInventory(destination, manifest), /shared write authority/);
      assert.equal((await fs.lstat(declared)).mode & 0o777, 0o666);
      assert.deepEqual(await fs.readFile(declared), declaredBytes);
      assert.deepEqual(await fs.readFile(path.join(destination, 'local-source-manifest.json')), manifestBytes);
      assert.equal(await fs.readFile(outside, 'utf8'), 'outside unchanged\n');
    } finally {
      await fs.chmod(declared, original.mode & 0o7777); // Restore only this test-owned file.
    }
  });
