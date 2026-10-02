"""Two fixed synthetic Qwen native audio samples. Default --plan is inert.

--prepare-cache is one CPU download/hash job. --execute is one separate bounded
H100 job after a valid cache receipt. No TTS API, microphone, bank, service or HF
secret. No automatic retry, quantization/offload, second GPU or model fallback.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
import wave

ROOT = Path(__file__).resolve().parent.parent
DIRECTORY = ROOT / '.local' / 'qwen-native'
CACHE_RECEIPT = DIRECTORY / 'cache.json'
MODEL = 'Qwen/Qwen3-Omni-30B-A3B-Instruct'
MODEL_REVISION = '26291f793822fb6be9555850f06dfe95f2d7e695'
SOURCE_REVISION = 'e4235853125589c789f06a2dd83e9f4126df5e9d'
WEIGHT_BYTES = 70_519_637_090
ASSETS_FILE = Path(__file__).with_name('qwen_native_assets.json')
VOLUME_NAME = 'elsewhere-qwen3-omni-native-26291f79'
OUTPUT_VOLUME = 'elsewhere-qwen-public-native-audition-output'
REMOTE_OUTPUT = Path('/audition-output')
REMOTE_MODEL = Path('/cache') / MODEL_REVISION
REMOTE_WORK = Path('/tmp/qwen-native')
GPU = 'H100'
FUNCTION_SECONDS, WORKER_SECONDS, CLIENT_SECONDS = 600, 540, 675
CACHE_SECONDS = 1800
DELIVERY_SECONDS, DELIVERY_CLIENT_SECONDS, DOWNLOAD_SECONDS = 30, 60, 45
DELIVERY_FIXTURE = b'Public synthetic Qwen artifact transport fixture.\n' * 256
VOICE = 'Chelsie'
RATE, MAX_AUDIO_SECONDS = 24_000, 31
THINKER_TOKENS, TALKER_TOKENS = 128, 384
SYSTEM = ('You are Qwen-Omni, a smart voice assistant created by Alibaba Qwen. '
          'Use brief, natural spoken replies in the language requested by the user. '
          'Your response contains only words to be spoken, with no formatting, '
          'stage directions or descriptions of emotions or voice changes.')
CASES = (
    {'id': 'es', 'locale': 'es-CO', 'text': 'Estoy un poco nervioso. Acompáñame con dos frases breves, cálidas y tranquilas en español colombiano natural, sin exagerar el acento.'},
    {'id': 'pt', 'locale': 'pt-BR', 'text': 'Estou um pouco nervoso. Me acompanhe com duas frases curtas, acolhedoras e calmas em português brasileiro natural, sem exagerar o sotaque.'},
)
DEPENDENCIES = ('transformers==5.2.0', 'accelerate==1.12.0', 'huggingface_hub==1.4.1',
                'numpy==2.2.6', 'librosa==0.11.0', 'soundfile==0.13.1', 'pillow==11.3.0')


def assets() -> dict:
    value = json.loads(ASSETS_FILE.read_text(encoding='utf8'))
    if len(value) != 23 or any(not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or not isinstance(meta, list) or
        len(meta) != 2 or type(meta[0]) is not int or meta[0] <= 0 or not re.fullmatch(r'[a-f0-9]{64}', meta[1])
        for name, meta in value.items()):
        raise ValueError('Pinned Qwen asset manifest required')
    if sum(meta[0] for name, meta in value.items() if name.endswith('.safetensors')) < WEIGHT_BYTES:
        raise ValueError('All fifteen full native model shards required')
    return value


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def verify_assets(directory: Path, manifest=None) -> dict:
    expected = assets() if manifest is None else manifest
    for name, (size, wanted) in expected.items():
        candidate = directory / name
        if candidate.is_symlink() or not candidate.is_file() or candidate.stat().st_size != size:
            raise ValueError('Pinned cached asset size/type mismatch')
        actual = hashlib.sha256()
        with candidate.open('rb') as source:
            while block := source.read(8 * 1024 * 1024):
                actual.update(block)
        if actual.hexdigest() != wanted:
            raise ValueError('Pinned cached asset checksum mismatch')
    return {'files': len(expected), 'bytes': sum(meta[0] for meta in expected.values()),
            'manifest_sha256': digest(json.dumps(expected, sort_keys=True).encode('utf8'))}


def messages(sample) -> list:
    if sample not in CASES:
        raise ValueError('Only the two fixed synthetic text cases are allowed')
    return [{'role': 'system', 'content': [{'type': 'text', 'text': SYSTEM}]},
            {'role': 'user', 'content': [{'type': 'text', 'text': sample['text']}]}]


def generation_options() -> dict:
    # Exact current Transformers 5.2.0 model.generate parameters, no lexical forcing.
    return {'speaker': VOICE, 'return_audio': True, 'use_audio_in_video': False,
            'thinker_max_new_tokens': THINKER_TOKENS, 'thinker_do_sample': False,
            'talker_max_new_tokens': TALKER_TOKENS}


def plan() -> dict:
    manifest = assets()
    return {'status': 'prepared_not_dispatched', 'model': MODEL, 'model_revision': MODEL_REVISION,
            'official_source_revision': SOURCE_REVISION, 'license': 'Apache-2.0; ungated model',
            'gpu': GPU, 'gpu_count': 1, 'bf16_weight_bytes': WEIGHT_BYTES,
            'fit': 'Unqualified short-text native audio fit; all weights CUDA0, no offload or quantization fallback',
            'attention': 'SDPA supported by pinned Transformers source; official memory table uses FlashAttention2',
            'dependencies': ['torch==2.8.0/cu128', 'torchaudio==2.8.0/cu128', 'torchvision==0.23.0/cu128', *DEPENDENCIES],
            'cpu_cache': {'volume': VOLUME_NAME, 'files': len(manifest), 'bytes': sum(v[0] for v in manifest.values()),
                'timeout_seconds': CACHE_SECONDS, 'creates_model_only_storage': True, 'hf_secret': False},
            'voice': VOICE, 'locales': [case['locale'] for case in CASES], 'model_loads': 1,
            'native_generations': 2, 'generation_bounds': generation_options(),
            'function_seconds': FUNCTION_SECONDS, 'worker_seconds': WORKER_SECONDS, 'client_seconds': CLIENT_SECONDS,
            'max_containers': 1, 'max_inputs': 1, 'retries': 0, 'runtime_downloads': False,
            'delivery': {'volume': OUTPUT_VOLUME, 'return': 'small committed size/hash receipt only',
                'preflight_function_seconds': DELIVERY_SECONDS, 'preflight_client_seconds': DELIVERY_CLIENT_SECONDS,
                'client_download_seconds': DOWNLOAD_SECONDS, 'corrected_gpu_flag': '--execute-delivery-fix'},
            'persistent_service': False, 'banking_access': False, 'room_microphone': False, 'dedicated_tts': False,
            'first_packet_latency_qualified': False, 'native_duplex_qualified': False,
            'cost_note': '600s one H100 plus 4CPU/96GiB allocation; CPU image/cache preparation and persistent model storage are separate billable resources.'}


def safe_failure(error: Exception, stage: str) -> dict:
    name = type(error).__name__
    allowed = {'ValueError', 'RuntimeError', 'TimeoutExpired', 'TimeoutError', 'FunctionTimeoutError',
               'FileNotFoundError', 'ModuleNotFoundError', 'ImportError', 'InvalidError', 'AuthenticationError',
               'RemoteError', 'ExecutionError', 'OSError', 'OutOfMemoryError', 'TypeError', 'AttributeError',
               'ClientConnectorDNSError', 'ServiceError', 'ConflictError', 'ClientClosed'}
    if name in {'OutOfMemoryError'} or 'out of memory' in str(error).lower(): code = 'gpu_memory_exhausted'
    elif name in {'TimeoutExpired', 'TimeoutError', 'FunctionTimeoutError'}: code = 'deadline_exceeded'
    elif name in {'ImportError', 'ModuleNotFoundError'}: code = 'dependency_unavailable'
    elif name == 'ClientConnectorDNSError': code = 'artifact_network_unavailable'
    else: code = 'qualification_failed'
    return {'status': 'failed', 'stage': stage, 'code': code, 'error_class': name if name in allowed else 'UnclassifiedError'}


def cache_model() -> dict:
    stage = 'cpu_cache'
    try:
        from huggingface_hub import snapshot_download
        import modal
        snapshot_download(MODEL, revision=MODEL_REVISION, local_dir=str(REMOTE_MODEL),
                          allow_patterns=list(assets()), token=False, max_workers=4)
        stage = 'cpu_checksum'; evidence = verify_assets(REMOTE_MODEL)
        modal.Volume.from_name(VOLUME_NAME).commit()
        return {'status': 'cache_verified', 'model_revision': MODEL_REVISION, 'volume': VOLUME_NAME, **evidence}
    except Exception as error:
        return safe_failure(error, stage)


def audio_profile(value: bytes) -> dict:
    if len(value) > 2 * 1024 * 1024:
        raise ValueError('Bounded native WAV required')
    with wave.open(io.BytesIO(value), 'rb') as audio:
        seconds = audio.getnframes() / audio.getframerate()
        if audio.getnchannels() != 1 or audio.getsampwidth() != 2 or audio.getframerate() != RATE or not 0 < seconds <= MAX_AUDIO_SECONDS:
            raise ValueError('Bounded native 24k mono PCM16 WAV required')
        return {'sample_rate': RATE, 'channels': 1, 'bits': 16, 'seconds': seconds, 'bytes': len(value), 'sha256': digest(value)}


def artifact_limits(kind: str) -> dict:
    if kind == 'native': return {'es.wav': 2 * 1024 * 1024, 'pt.wav': 2 * 1024 * 1024, 'report.json': 65_536}
    if kind == 'delivery-preflight': return {'delivery-fixture.bin': len(DELIVERY_FIXTURE)}
    raise ValueError('Exact public audition delivery kind required')


def validate_artifacts(kind: str, values: dict) -> None:
    limits = artifact_limits(kind)
    if not isinstance(values, dict) or set(values) != set(limits): raise ValueError('Exact public artifacts required')
    for name, value in values.items():
        if not isinstance(value, bytes) or not 0 < len(value) <= limits[name]: raise ValueError('Bounded artifact required')
        if name.endswith('.wav'): audio_profile(value)
    if kind == 'delivery-preflight':
        if values['delivery-fixture.bin'] != DELIVERY_FIXTURE: raise ValueError('Fixed public delivery fixture required')
        return
    report = json.loads(values['report.json'])
    expected = {'status': 'completed', 'model': MODEL, 'model_revision': MODEL_REVISION,
        'source_revision': SOURCE_REVISION, 'voice': VOICE, 'model_loads': 1, 'native_generations': 2,
        'runtime_downloads': False, 'banking_access': False, 'room_microphone': False, 'dedicated_tts': False,
        'gpu': GPU, 'gpu_count': 1, 'native_duplex_qualified': False, 'human_voice_quality_verified': False}
    if any(report.get(key) != value for key, value in expected.items()) or len(report.get('samples', [])) != 2:
        raise ValueError('Pinned native audition report required')
    for case, sample in zip(CASES, report['samples']):
        if sample.get('id') != case['id'] or sample.get('locale') != case['locale'] or \
                sample.get('audio') != audio_profile(values[case['id'] + '.wav']):
            raise ValueError('Native sample/header/hash receipt mismatch')


def validate_delivery(value: dict) -> dict:
    keys = {'status', 'kind', 'output_volume', 'model_revision', 'run_id', 'files'}
    if not isinstance(value, dict) or set(value) != keys or value['status'] != 'artifacts_committed' or \
            value['output_volume'] != OUTPUT_VOLUME or value['model_revision'] != MODEL_REVISION or \
            not isinstance(value['run_id'], str) or not re.fullmatch(r'[a-f0-9]{32}', value['run_id']):
        raise ValueError('Exact tiny committed delivery receipt required')
    limits = artifact_limits(value['kind'])
    if not isinstance(value['files'], dict) or set(value['files']) != set(limits): raise ValueError('Exact receipt files required')
    for name, item in value['files'].items():
        if not isinstance(item, dict) or set(item) != {'bytes', 'sha256'} or type(item['bytes']) is not int or \
                not 0 < item['bytes'] <= limits[name] or not isinstance(item['sha256'], str) or \
                not re.fullmatch(r'[a-f0-9]{64}', item['sha256']):
            raise ValueError('Bounded size/hash receipt required')
    if value['kind'] == 'delivery-preflight' and value['files']['delivery-fixture.bin'] != \
            {'bytes': len(DELIVERY_FIXTURE), 'sha256': digest(DELIVERY_FIXTURE)}:
        raise ValueError('Exact verified public delivery fixture receipt required')
    if len(json.dumps(value)) > 4096: raise ValueError('Tiny inline delivery receipt required')
    return value


def persist_artifacts(kind: str, values: dict, commit, root=REMOTE_OUTPUT) -> dict:
    validate_artifacts(kind, values)
    run_id = secrets.token_hex(16); destination = Path(root) / run_id
    destination.mkdir(exist_ok=False)
    for name, data in values.items():
        with (destination / name).open('xb') as output: output.write(data)
    commit()  # SDK VolumeCommit uses the existing internal RPC, never an artifact blob upload.
    receipt = {'status': 'artifacts_committed', 'kind': kind, 'output_volume': OUTPUT_VOLUME,
        'model_revision': MODEL_REVISION, 'run_id': run_id,
        'files': {name: {'bytes': len(data), 'sha256': digest(data)} for name, data in values.items()}}
    return validate_delivery(receipt)


async def download_artifacts(value: dict, volume=None, timeout=DOWNLOAD_SECONDS) -> dict:
    validate_delivery(value)
    if not 0 < timeout <= DOWNLOAD_SECONDS: raise TimeoutError('Bounded artifact download deadline expired')
    async def read():
        nonlocal volume
        if volume is None:
            import modal
            volume = modal.Volume.from_name(OUTPUT_VOLUME)
        outputs = {}
        for name, expected in value['files'].items():
            data = bytearray()
            async for block in volume.read_file.aio(value['run_id'] + '/' + name):
                if not isinstance(block, bytes) or len(data) + len(block) > expected['bytes']:
                    raise ValueError('Artifact download exceeded its pinned size')
                data.extend(block)
            result = bytes(data)
            if len(result) != expected['bytes'] or digest(result) != expected['sha256']:
                raise ValueError('Artifact download size/hash mismatch')
            outputs[name] = result
        validate_artifacts(value['kind'], outputs)
        return outputs
    return await asyncio.wait_for(read(), timeout=timeout)


def delivery_preflight() -> dict:
    try:
        import modal
        return persist_artifacts('delivery-preflight', {'delivery-fixture.bin': DELIVERY_FIXTURE},
            modal.Volume.from_name(OUTPUT_VOLUME).commit)
    except Exception as error:
        return safe_failure(error, 'delivery_preflight')


def native_worker(progress: dict) -> None:
    progress['stage'] = 'offline_cache_verification'; started = time.perf_counter()
    if os.environ.get('HF_TOKEN') or os.environ.get('HUGGING_FACE_HUB_TOKEN'):
        raise ValueError('Runtime HF credentials are forbidden')
    verify_assets(REMOTE_MODEL); verified = time.perf_counter() - started
    progress['stage'] = 'dependencies'
    import torch
    import numpy as np
    from transformers import Qwen3OmniMoeForConditionalGeneration, Qwen3OmniMoeProcessor
    if torch.cuda.device_count() != 1 or not torch.cuda.is_bf16_supported():
        raise ValueError('Exactly one BF16 CUDA GPU required')
    free, total = torch.cuda.mem_get_info(0)
    if free < WEIGHT_BYTES + 6 * 1024**3:
        raise ValueError('Insufficient GPU weight/runtime headroom; no fallback')
    torch.manual_seed(42); torch.cuda.reset_peak_memory_stats(0)
    progress['stage'] = 'model_loading'; began = time.perf_counter()
    model = Qwen3OmniMoeForConditionalGeneration.from_pretrained(str(REMOTE_MODEL), dtype=torch.bfloat16,
        device_map={'': 0}, attn_implementation='sdpa', local_files_only=True, trust_remote_code=False).eval()
    if not model.has_talker or any(parameter.device.type != 'cuda' or parameter.device.index != 0 for parameter in model.parameters()):
        raise ValueError('All native Thinker/Talker/codec weights must stay on CUDA0')
    processor = Qwen3OmniMoeProcessor.from_pretrained(str(REMOTE_MODEL), local_files_only=True, trust_remote_code=False)
    torch.cuda.synchronize(); loading = time.perf_counter() - began
    outputs = []
    for sample in CASES:
        progress.update(stage='native_generation', sample=sample['id']); began = time.perf_counter()
        text = processor.apply_chat_template(messages(sample), add_generation_prompt=True, tokenize=False)
        inputs = processor(text=text, return_tensors='pt', padding=True).to(model.device)
        if inputs['input_ids'].shape[-1] > 512: raise ValueError('Tiny text prompt bound exceeded')
        with torch.inference_mode(): text_ids, audio = model.generate(**inputs, **generation_options())
        torch.cuda.synchronize(); elapsed = time.perf_counter() - began
        # Version 5.2 returns sequence tensor; compatibility with documented dict form remains bounded.
        sequences = text_ids.sequences if hasattr(text_ids, 'sequences') else text_ids
        caption = processor.batch_decode(sequences[:, inputs['input_ids'].shape[1]:], skip_special_tokens=True,
                                         clean_up_tokenization_spaces=False)[0]
        if not isinstance(caption, str) or not 0 < len(caption) <= 4000 or re.search(r'https?://|Bearer\s|sk-[A-Za-z0-9_-]+', caption):
            raise ValueError('Bounded public synthetic caption required')
        if audio is None: raise ValueError('The native model returned no audio')
        data = audio.reshape(-1).detach().float().cpu().numpy()
        if data.size <= 0 or data.size > MAX_AUDIO_SECONDS * RATE or not np.isfinite(data).all():
            raise ValueError('Native waveform bound exceeded')
        pcm = (np.clip(data, -1, 1) * 32767).astype('<i2').tobytes(); buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(RATE); output.writeframes(pcm)
        value = buffer.getvalue(); profile = audio_profile(value)
        (REMOTE_WORK / (sample['id'] + '.wav')).write_bytes(value)
        outputs.append({'id': sample['id'], 'locale': sample['locale'], 'caption': caption,
            'caption_source': 'native Thinker output, not independent ASR', 'native_generation_seconds': elapsed,
            'real_time_factor': elapsed / profile['seconds'], 'audio': profile})
        del inputs, text_ids, sequences, audio, data
    progress['stage'] = 'artifacts'
    report = {'status': 'completed', 'model': MODEL, 'model_revision': MODEL_REVISION, 'voice': VOICE,
        'source_revision': SOURCE_REVISION, 'attention': 'sdpa', 'dtype': 'bfloat16', 'model_loads': 1,
        'native_generations': 2, 'runtime_downloads': False, 'banking_access': False, 'room_microphone': False,
        'dedicated_tts': False, 'gpu': GPU, 'gpu_count': 1, 'gpu_total_bytes': total,
        'gpu_peak_allocated_bytes': torch.cuda.max_memory_allocated(0), 'gpu_peak_reserved_bytes': torch.cuda.max_memory_reserved(0),
        'cache_verification_seconds': verified, 'model_load_seconds': loading, 'worker_seconds': time.perf_counter() - started,
        'first_packet_latency_qualified': False, 'native_duplex_qualified': False, 'human_voice_quality_verified': False, 'samples': outputs}
    (REMOTE_WORK / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')


def gpu_native() -> dict:
    stage = 'native_worker'
    try:
        REMOTE_WORK.mkdir(exist_ok=False)
        child = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker'],
            capture_output=True, timeout=WORKER_SECONDS, env={**os.environ, 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1'})
        if child.returncode:
            failure = REMOTE_WORK / 'failure.json'
            if failure.is_file() and failure.stat().st_size < 4096:
                value = json.loads(failure.read_text(encoding='utf8'))
                if set(value) <= {'status', 'stage', 'code', 'error_class'} and value.get('status') == 'failed':
                    return value
            raise RuntimeError('Bounded native worker failed')
        artifacts = {name: (REMOTE_WORK / name).read_bytes() for name in ('es.wav', 'pt.wav', 'report.json')}
        validate_artifacts('native', artifacts)
        stage = 'artifact_commit'
        import modal
        return persist_artifacts('native', artifacts, modal.Volume.from_name(OUTPUT_VOLUME).commit)
    except Exception as error:
        return safe_failure(error, stage)


def build_app(mode: str):
    if mode not in ('cache', 'gpu', 'delivery-preflight') or gpu_native.__module__ != 'qwen_native_audition':
        raise ValueError('Canonical bounded source module required')
    import modal
    image = (modal.Image.debian_slim(python_version='3.11').apt_install('libsndfile1')
        .pip_install('torch==2.8.0', 'torchaudio==2.8.0', 'torchvision==0.23.0', index_url='https://download.pytorch.org/whl/cu128')
        .pip_install(*DEPENDENCIES).add_local_python_source('qwen_native_audition', copy=True)
        .add_local_file(str(ASSETS_FILE), '/root/qwen_native_assets.json', copy=True)
        .env({'HF_HUB_DISABLE_IMPLICIT_TOKEN': '1', 'TOKENIZERS_PARALLELISM': 'false', 'HF_HUB_DISABLE_PROGRESS_BARS': '1'})
        .run_commands("python -c 'from transformers import Qwen3OmniMoeForConditionalGeneration,Qwen3OmniMoeProcessor; import torch'"))
    volumes = {'/cache': modal.Volume.from_name(VOLUME_NAME, create_if_missing=(mode == 'cache'))} if mode != 'delivery-preflight' else {}
    if mode != 'cache': volumes[str(REMOTE_OUTPUT)] = modal.Volume.from_name(OUTPUT_VOLUME, create_if_missing=True)
    app = modal.App('elsewhere-qwen-delivery-preflight' if mode == 'delivery-preflight' else 'elsewhere-qwen-native-language-audition')
    common = dict(image=image, volumes=volumes, cpu=(2, 4), max_containers=1, min_containers=0,
        buffer_containers=0, retries=0, scaledown_window=2, single_use_containers=True, max_inputs=1,
        serialized=False, include_source=True, startup_timeout=60)
    if mode == 'cache':
        function = app.function(timeout=CACHE_SECONDS, memory=(4096, 16384), **common)(cache_model)
    elif mode == 'delivery-preflight':
        function = app.function(timeout=DELIVERY_SECONDS, memory=(1024, 2048), block_network=True,
            env={'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1'}, **common)(delivery_preflight)
    else:
        function = app.function(gpu=GPU, timeout=FUNCTION_SECONDS, memory=(32768, 98304),
            block_network=True, env={'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1'}, **common)(gpu_native)
    return app, function


def save_json(path: Path, value: dict, exclusive=False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x' if exclusive else 'w', encoding='utf8') as output:
        json.dump(value, output, indent=2); output.write('\n')


def require_cache_receipt() -> dict:
    if CACHE_RECEIPT.is_symlink() or not CACHE_RECEIPT.is_file() or CACHE_RECEIPT.stat().st_size > 4096:
        raise ValueError('Explicit CPU cache receipt required before GPU admission')
    value = json.loads(CACHE_RECEIPT.read_text(encoding='utf8'))
    manifest = assets()
    expected = {'status': 'cache_verified', 'model_revision': MODEL_REVISION, 'volume': VOLUME_NAME,
                'files': len(manifest), 'bytes': sum(v[0] for v in manifest.values()),
                'manifest_sha256': digest(json.dumps(manifest, sort_keys=True).encode('utf8'))}
    if value != expected:
        raise ValueError('Pinned verified CPU cache receipt required')
    return value


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__); modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--plan', action='store_true'); modes.add_argument('--prepare-cache', action='store_true')
    modes.add_argument('--execute', action='store_true', help='Disabled original delivery mode; historical admission is retained')
    modes.add_argument('--delivery-preflight', action='store_true'); modes.add_argument('--execute-delivery-fix', action='store_true')
    modes.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        progress = {'stage': 'offline_cache_verification'}
        try:
            if os.environ.get('HF_HUB_OFFLINE') != '1' or not REMOTE_WORK.is_dir(): raise ValueError('Offline child required')
            native_worker(progress); return 0
        except Exception as error:
            save_json(REMOTE_WORK / 'failure.json', safe_failure(error, progress['stage'])); return 1
    if args.execute:
        print(json.dumps({'status': 'failed', 'stage': 'local_admission', 'code': 'original_delivery_disabled', 'error_class': 'ValueError'}))
        return 1
    if not args.prepare_cache and not args.execute_delivery_fix and not args.delivery_preflight:
        print(json.dumps(plan(), indent=2)); return 0
    mode = 'cache' if args.prepare_cache else 'delivery-preflight' if args.delivery_preflight else 'gpu'; stage = 'local_cache_receipt'
    destination = DIRECTORY / (time.strftime('%Y%m%d-%H%M%S') + '-' + str(time.time_ns()))
    try:
        if mode == 'gpu':
            require_cache_receipt()
            preflight = json.loads((DIRECTORY / 'delivery-preflight.json').read_text(encoding='utf8'))
            validate_delivery(preflight)
            if preflight['kind'] != 'delivery-preflight': raise ValueError('Verified CPU delivery preflight required')
            save_json(DIRECTORY / 'gpu-delivery-fix-admitted.json', {'status': 'spent_before_dispatch', 'model_revision': MODEL_REVISION}, exclusive=True)
        elif mode == 'delivery-preflight':
            save_json(DIRECTORY / 'delivery-preflight-admitted.json', {'status': 'spent_before_dispatch', 'model_revision': MODEL_REVISION}, exclusive=True)
        stage = 'app_definition'; app, function = build_app(mode)
        stage = 'cpu_cache' if mode == 'cache' else 'delivery_preflight' if mode == 'delivery-preflight' else 'bounded_gpu'
        with app.run(detach=False):
            client_seconds = CACHE_SECONDS + 75 if mode == 'cache' else DELIVERY_CLIENT_SECONDS if mode == 'delivery-preflight' else CLIENT_SECONDS
            client_deadline = time.monotonic() + client_seconds
            job = function.spawn()
            try: value = job.get(timeout=client_seconds)
            finally:
                try: job.cancel(terminate_containers=True)
                except Exception: pass
        if mode == 'cache' and value.get('status') == 'cache_verified':
            save_json(CACHE_RECEIPT, value); require_cache_receipt(); print(json.dumps(value)); return 0
        if value.get('status') != 'artifacts_committed':
            save_json(destination / 'failure.json', value); print(json.dumps(value)); return 1
        stage = 'artifact_download'; validate_delivery(value)
        if value['kind'] != ('delivery-preflight' if mode == 'delivery-preflight' else 'native'):
            raise ValueError('Delivery kind mismatch')
        artifacts = asyncio.run(download_artifacts(value, timeout=min(DOWNLOAD_SECONDS, client_deadline - time.monotonic())))
        if mode == 'delivery-preflight':
            save_json(DIRECTORY / 'delivery-preflight.json', value)
            print(json.dumps({'status': 'delivery_preflight_verified', 'bytes': len(DELIVERY_FIXTURE),
                'gpu': False, 'model_loaded': False, 'inference': False})); return 0
        destination.mkdir(parents=True, exist_ok=False)
        for name, data in artifacts.items(): (destination / name).write_bytes(data)
        save_json(destination / 'delivery.json', value)
        print(json.dumps({'status': 'completed', 'output_directory': str(destination), 'human_voice_quality_verified': False,
                          'native_duplex_qualified': False, 'termination_verification_required': True})); return 0
    except Exception as error:
        value = safe_failure(error, stage); save_json(destination / 'failure.json', value); print(json.dumps(value)); return 1


if __name__ == '__main__':
    from importlib import import_module
    raise SystemExit(import_module('qwen_native_audition').main())
