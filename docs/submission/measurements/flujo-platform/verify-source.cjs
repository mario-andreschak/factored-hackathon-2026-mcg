// Verify exact copied upstream bytes without network access or dependencies.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const cp = require('node:child_process');

const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, 'source-manifest.json'), 'utf8'));
const gitRef = process.argv.find((arg) => arg.startsWith('--git-ref='))?.slice('--git-ref='.length);
const root = gitRef ? cp.execFileSync('git', ['rev-parse', '--show-toplevel'], { cwd: __dirname, encoding: 'utf8' }).trim() : null;
let bytes = 0;
for (const entry of manifest.files) {
  const sourcePath = path.join(__dirname, entry.path);
  const repoPath = root ? path.relative(root, sourcePath).replaceAll('\\', '/') : null;
  const file = gitRef ? cp.execFileSync('git', ['show', `${gitRef}:${repoPath}`], { cwd: root, maxBuffer: 4 * 1024 * 1024 }) : fs.readFileSync(sourcePath);
  const sha256 = crypto.createHash('sha256').update(file).digest('hex');
  const blob = crypto.createHash('sha1').update(`blob ${file.length}\0`).update(file).digest('hex');
  if (sha256 !== entry.sha256 || blob !== entry.gitBlob || file.length !== entry.bytes) {
    throw new Error(`Source differs from the recorded upstream blob: ${entry.upstreamPath}`);
  }
  bytes += file.length;
}
if (bytes !== manifest.totalBytes || manifest.files.length !== manifest.totalFiles) throw new Error('Manifest totals differ.');
console.log(JSON.stringify({ success: true, upstreamCommit: manifest.commit, submissionGitRef: gitRef ?? null, verifiedFiles: manifest.files.length, verifiedBytes: bytes }));
