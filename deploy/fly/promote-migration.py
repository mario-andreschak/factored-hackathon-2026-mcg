"""Activate the verified, targeted archive on a temporary Fly staging machine."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile

ROOT = Path('/data')
ROOTS = {'flujo', 'banking-data', 'banking-state', 'banking-demo-state', 'private'}
MARKER = '.migration-complete.json'

if len(sys.argv) != 3:
    raise SystemExit('Usage: promote-migration.py SHA256 BYTES')
expected_hash, expected_bytes = sys.argv[1], int(sys.argv[2])
archive = ROOT / 'migration.tar.gz'
if not archive.is_file() or archive.is_symlink() or archive.stat().st_size != expected_bytes:
    raise SystemExit('Archive size or file type mismatch')
digest = hashlib.sha256()
with archive.open('rb') as source:
    for chunk in iter(lambda: source.read(1024 * 1024), b''):
        digest.update(chunk)
if digest.hexdigest() != expected_hash:
    raise SystemExit('Archive checksum mismatch')
if (ROOT / MARKER).exists() or any((ROOT / name).exists() for name in ROOTS):
    raise SystemExit('Refusing to overwrite an initialized volume')
incoming = ROOT / '.migration-incoming'
if incoming.exists():
    if incoming.is_symlink() or incoming.resolve() != incoming:
        raise SystemExit('Unsafe existing extraction directory')
    # A failed first extraction can be retried before any root is promoted.
    shutil.rmtree(incoming)
incoming.mkdir(mode=0o700)
with tarfile.open(archive, 'r:gz') as bundle:
    members = bundle.getmembers()
    for member in members:
        name = PurePosixPath(member.name)
        parts = [part for part in name.parts if part != '.']
        if name.is_absolute() or '..' in parts or (parts and parts[0] not in ROOTS | {MARKER}):
            raise SystemExit('Archive contains an unexpected destination')
    dependency_links = {
        f'flujo/workspaces/default-workspace/mcp-servers/{name}/node_modules'
        for name in ['shared', 'flujo', 'browser', 'bash']
    }
    delayed_links = []
    regular_members = []
    for member in members:
        normalized_name = PurePosixPath(member.name).as_posix().lstrip('./')
        if member.issym() and normalized_name in dependency_links:
            if member.linkname != '/app/node_modules':
                raise SystemExit('Unexpected shared MCP dependency link')
            delayed_links.append(normalized_name)
        else:
            regular_members.append(member)
    # This source-owned link points to immutable image dependencies. Create it
    # after extraction, so no archive member can write through it into the image.
    bundle.extractall(incoming, members=regular_members, filter='data')
    for relative in delayed_links:
        destination = incoming / relative
        if destination.parent.resolve() != destination.parent or destination.exists() or destination.is_symlink():
            raise SystemExit('Unsafe shared MCP dependency destination')
        destination.symlink_to('/app/node_modules')
receipt_file = incoming / MARKER
receipt = json.loads(receipt_file.read_text())
if receipt.get('workerImage') != 'sha256:a071761b46eed021471508f8de8b7d5726752125a3d19e66c4b286d59bde6d86':
    raise SystemExit('Unexpected source worker image')
if receipt.get('conversations') != 0 or receipt.get('userdata') != 0:
    raise SystemExit('Migration must omit conversations and user workspace files')
for relative in ['flujo/workspaces/default-workspace/userdata', 'flujo/workspaces/default-workspace/db/conversations']:
    directory = incoming / relative
    if not directory.is_dir() or directory.is_symlink() or any(directory.iterdir()):
        raise SystemExit('Excluded workspace or conversation directory is not empty')
for name in ROOTS:
    directory = incoming / name
    if not directory.is_dir() or directory.is_symlink():
        raise SystemExit('Missing migration root')
    os.rename(directory, ROOT / name)
receipt.update(archiveSha256=expected_hash, archiveBytes=expected_bytes)
receipt_file.write_text(json.dumps(receipt) + '\n')
os.chmod(receipt_file, 0o600)
with receipt_file.open('rb') as source:
    os.fsync(source.fileno())
os.rename(receipt_file, ROOT / MARKER)
directory_fd = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY)
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
incoming.rmdir()
archive.unlink()
print(json.dumps({'status': 'activated', 'sha256': expected_hash, 'conversations': 0, 'userdata': 0}))
