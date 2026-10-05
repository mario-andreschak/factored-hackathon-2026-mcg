"""Fixed private weight image preparation. Invoked only by the explicit CPU build."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from personaplex_modal import MODEL_FILES, MODEL_REPO, MODEL_REVISION, SOURCE_REVISION, VOICE, extract_voice

MODEL_DIRECTORY = Path('/opt/personaplex-weights')


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def prepare_weights(destination=MODEL_DIRECTORY, download=None) -> dict:
    if download is None:
        from huggingface_hub import hf_hub_download
        download = hf_hub_download
    token = os.environ.get('HF_TOKEN', '').strip()
    if not token:
        raise RuntimeError('Existing model access was not injected into the private build.')
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='personaplex-weight-build-') as cache:
        for filename in MODEL_FILES:
            downloaded = download(MODEL_REPO, filename, revision=MODEL_REVISION, token=token, cache_dir=cache)
            shutil.copyfile(downloaded, destination / filename)
        (destination / 'voices').mkdir()
        extract_voice(destination / 'voices.tgz', destination / 'voices' / VOICE)
    manifest = {
        'source_revision': SOURCE_REVISION, 'model_revision': MODEL_REVISION,
        'sha256': {filename: file_digest(destination / filename) for filename in (*MODEL_FILES, 'voices/' + VOICE)},
    }
    (destination / 'revision.json').write_text(json.dumps(manifest, indent=2), encoding='utf8')
    return manifest


if __name__ == '__main__':
    # Never print provider exceptions or token-bearing signed download URLs.
    try:
        prepare_weights()
        print(json.dumps({'status': 'fixed_weights_cached', 'model_revision': MODEL_REVISION}))
    except Exception:
        print(json.dumps({'status': 'failed', 'code': 'private_weight_build_failed'}))
        raise SystemExit(1)
