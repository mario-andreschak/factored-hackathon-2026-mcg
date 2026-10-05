"""Local Slack raster assets, downloaded through read-only MCP and OCR screened.

No private URLs are fetched. Raw bytes and OCR text are temporary and never
exported. Unsupported/unreadable images stay as attachment placeholders.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .common import redact, sanitize
from .mcp import Client, configured_endpoint
from .slack import image_from_response

POLICY = 'contacts-local-ocr-v1'


def screen_image(data):
    """Strip metadata, then inspect locally. Fail closed if OCR is unavailable."""
    from PIL import Image
    with Image.open(io.BytesIO(data)) as original:
        if original.width * original.height > 20_000_000:
            raise ValueError('Image exceeds privacy-screening pixel limit')
        # Export pixels without EXIF/comments/location or source filenames.
        image = original.convert('RGB')
        encoded = io.BytesIO()
        image.save(encoded, format='PNG')
        clean = encoded.getvalue()
    helper = Path(__file__).with_name('ocr_history_image.ps1')
    executable = shutil.which('powershell.exe') if os.name == 'nt' else None
    if not executable:
        raise RuntimeError('Local Windows OCR is unavailable on this host')
    with tempfile.TemporaryDirectory(prefix='history-image-') as directory:
        file = Path(directory) / 'pixels.png'
        file.write_bytes(clean)
        command = [executable, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(helper), '-ImagePath', str(file.resolve())]
        process = subprocess.run(command, capture_output=True, timeout=45)
        if process.returncode:
            raise RuntimeError('Local OCR could not inspect this image')
        observed = json.loads(process.stdout.decode('utf-8-sig'))
    text = observed.get('text', '')
    # OCR often inserts spaces around @ and punctuation in contact details.
    normalized = re.sub(r'\s*(@|\.)\s*', r'\1', text)
    if redact(text) != text or redact(normalized) != normalized:
        return None, {'status': 'withheld', 'reason': 'Contact details detected in image; original pixels withheld.'}
    return clean, {'status': 'available', 'width': image.width, 'height': image.height,
                   'mimeType': 'image/png', 'privacyScreen': POLICY,
                   'privacyBasis': 'Local OCR found no contact details; image metadata stripped. OCR is not a guarantee of complete recognition.'}


def collect_assets(result, output, cache, config, offline=False):
    output, cache = Path(output), Path(cache)
    directory = output / 'media'
    directory.mkdir(parents=True, exist_ok=True)
    manifest_file = cache / 'slack-media.json'
    manifest = json.loads(manifest_file.read_text(encoding='utf-8')) if manifest_file.exists() else {}
    entries = {}
    files = {file['id']: file for event in result.get('events', []) for file in event.get('metadata', {}).get('files', [])
             if isinstance(file, dict) and re.fullmatch(r'F[A-Z0-9]+', str(file.get('id', ''))) and file.get('isImage')}
    client = None
    for identity, file in files.items():
        old = manifest.get(identity, {})
        existing = directory / str(old.get('assetName', ''))
        if old.get('privacyScreen') == POLICY and old.get('status') == 'available' and existing.is_file() and existing.resolve().parent == directory.resolve():
            entry = old
        elif offline or config.get('slack_images') is False:
            entry = old if old.get('status') == 'withheld' else {'status': 'unavailable', 'reason': 'Image needs a live rebuild and local privacy screening.'}
        else:
            try:
                if client is None:
                    endpoint, headers = configured_endpoint(config)
                    client = Client(endpoint, headers)
                raster = image_from_response(client.call('slack_read_file', {'file_id': identity}))
                if raster is None:
                    raise ValueError('Connector did not return a supported raster image')
                data, entry = screen_image(raster['data'])
                if data:
                    name = 'slack-' + identity + '-' + hashlib.sha256(data).hexdigest()[:16] + '.png'
                    target = directory / name
                    target.write_bytes(data)
                    entry.update(assetName=name, src='data/media/' + name, privacyScreen=POLICY)
            except Exception as error:
                # No error text from a connector/private response is exported.
                entry = {'status': 'unavailable', 'reason': 'Image unavailable or local privacy screening failed.', 'errorType': type(error).__name__}
        entries[identity] = entry
        print(f"Slack image {identity}: {entry['status']}", flush=True)
    for event in result.get('events', []):
        meta = event.get('metadata', {})
        for file in meta.get('files', []):
            file.pop('thumbnailUrl', None)
            for key in ('src', 'assetName', 'privacyScreen', 'privacyBasis', 'errorType', 'reason', 'status'):
                file.pop(key, None)
            if file.get('id') in entries:
                file.update(entries[file['id']])
        meta['images'] = [file for file in meta.get('files', []) if file.get('isImage')]
    cache.mkdir(parents=True, exist_ok=True)
    temp = manifest_file.with_suffix('.tmp')
    temp.write_text(json.dumps(sanitize(entries), ensure_ascii=False), encoding='utf-8')
    temp.replace(manifest_file)
    used = {entry.get('assetName') for entry in entries.values() if entry.get('status') == 'available'}
    for old in directory.glob('slack-F*-*.png'):
        if old.name not in used and old.resolve().parent == directory.resolve():
            old.unlink()
    counts = {status: sum(entry.get('status') == status for entry in entries.values()) for status in ('available', 'withheld', 'unavailable')}
    result.setdefault('stats', {}).update(images=counts, imageFiles=len(files), reactionMessages=sum(bool(event.get('metadata', {}).get('reactions')) for event in result.get('events', [])))
    result['notes'] = [note for note in result.get('notes', []) if not str(note).startswith('Slack images: ')]
    result['notes'].append(f"Slack images: {counts['available']} local assets, {counts['withheld']} withheld for contact privacy, {counts['unavailable']} unavailable. Reaction counts are observed at capture, not timestamped reaction history. Image OCR may miss text; metadata is stripped.")
    return result
