"""Inert-by-default Qwen engine-duplex WebSocket Stage A qualification.

--prepare-runtime is an explicitly admitted CPU image/import/protocol/delivery
preflight. --execute is one separately admitted, finite two-H100 job. Neither is
called by --plan. No app provider, browser, microphone, bank or live endpoint.
"""
from __future__ import annotations

import argparse
import asyncio
import array
import base64
import ctypes
import importlib.metadata
import io
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import time
import urllib.request
import urllib.parse
import wave

import qwen_native_audition as native

DIRECTORY = native.ROOT / '.local' / 'qwen-live'
RUNTIME_RECEIPT = DIRECTORY / 'runtime.json'
PYTHON3_PROVENANCE = DIRECTORY / 'runtime-python3-failure.json'
OMNI_REVISION = '423f34326ed420e5acf0b1fb862a1b5ffb7e0fa7'
BASE_IMAGE = 'vllm/vllm-openai@sha256:5f5e535216848d0c52159c8c13a0af04be5f6fe1a84e79914300610796f76d40'
REPO = Path('/opt/vllm-omni')
WORK = Path('/tmp/qwen-live')
PREP = Path('/opt/audition')
VAD_REVISION = '8b14476858ef240c50b3884bb38cc67290c1cc70'
VAD_SHA256 = '1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3'
VAD_FILE = PREP / 'silero_vad.onnx'
VAD_URL = f'https://huggingface.co/istupakov/silero-vad-onnx/resolve/{VAD_REVISION}/silero_vad.onnx'
FIXTURE_DIRECTORY = native.DIRECTORY / '20261001-084853-1790862533806878800'
FIXTURES = (
    {'id': 'es', 'locale': 'es-CO', 'bytes': 198614,
     'sha256': '3956bc585e5bac204010593ea5ae37182ac47828d034ffcb36f8e8daca481d6c',
     'instructions': 'Responde en español natural, con una sola frase breve, cálida y tranquila. No uses inglés ni describas tu voz.'},
    {'id': 'pt', 'locale': 'pt-BR', 'bytes': 240854,
     'sha256': '1b9a1ce221bd44ce01f454dd5214415fa48b7d078dc92875b153f7baa96cf6ad',
     'instructions': 'Responda em português brasileiro natural, com uma única frase curta, acolhedora e calma. Não use inglês nem descreva a sua voz.'},
)
FUNCTION_SECONDS, WORKER_SECONDS, CLIENT_SECONDS = 600, 540, 675
CPU_SECONDS, CPU_CLIENT_SECONDS = 240, 315
STARTUP_SECONDS, REQUEST_SECONDS, HANDSHAKE_SECONDS = 360, 45, 15
RATE, PROCESSING_RATE, FRAME_SAMPLES = 24000, 16000, 4800
KILL_SIGNAL = getattr(signal, 'SIGKILL', 9)
MAX_PCM_BYTES = RATE * 2 * 31
SOCKET_URL = 'ws://127.0.0.1:8091/v1/realtime?duplex=1&model=' + urllib.parse.quote(native.MODEL, safe='')
SOURCE_FILES = ('qwen_live_audition.py', 'qwen_native_audition.py', 'qwen_native_assets.json')
STAGES = {'local_preflight', 'app_definition', 'cpu_runtime', 'cpu_imports', 'cpu_protocol',
          'cpu_delivery', 'cuda_guard', 'offline_cache_verification', 'server_startup',
          'native_ws_es', 'native_ws_pt', 'artifact_commit', 'artifact_download', 'cleanup',
          'cpu_pins', 'cpu_versions', 'cpu_model_config', 'cpu_registry', 'cpu_pipeline',
          'cpu_deploy', 'cpu_vad', 'cpu_cli', 'cpu_lock'}
OFFLINE = {'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'HF_HUB_DISABLE_IMPLICIT_TOKEN': '1',
           'TOKENIZERS_PARALLELISM': 'false', 'HF_HUB_DISABLE_PROGRESS_BARS': '1'}


def plan() -> dict:
    return {'status': 'prepared_not_dispatched', 'stage': 'engine_duplex_ws_native_audio',
        'model': native.MODEL, 'model_revision': native.MODEL_REVISION, 'omni_revision': OMNI_REVISION,
        'base_image': BASE_IMAGE, 'base_config': 'qwen3_omni_duplex.yaml', 'async_chunk': True,
        'gpu': 'H100:2', 'gpu_count': 2, 'function_seconds': FUNCTION_SECONDS,
        'worker_seconds': WORKER_SECONDS, 'client_seconds': CLIENT_SECONDS,
        'startup_seconds': STARTUP_SECONDS, 'request_seconds': REQUEST_SECONDS,
        'max_containers': 1, 'single_use_containers': True, 'retries': 0,
        'cpu_preparation_seconds': CPU_SECONDS, 'runtime_downloads': False,
        'model_volume': native.VOLUME_NAME, 'model_mount_read_only': True,
        'vad_revision': VAD_REVISION, 'vad_sha256': VAD_SHA256,
        'protocol': '/v1/realtime?duplex=1; JSON/base64 PCM16',
        'input_rate': RATE, 'model_processing_rate': PROCESSING_RATE, 'output_rate': RATE,
        'locales': [x['locale'] for x in FIXTURES], 'native_audio_turns': 2,
        'runtime_default_speaker': 'Chelsie', 'speaker_selection_supported': False,
        'dedicated_tts': False, 'browser': False, 'room_microphone': False, 'banking_access': False,
        'barge_in_qualified': False, 'human_voice_quality_verified': False,
        'cost_ceiling_usd': 2.50, 'allocation_600s_usd': 1.549776,
        'allocation_with_60s_startup_usd': 1.7047536,
        'cpu_build_storage_separate': True}


def source_hashes() -> dict:
    return {name: native.digest(Path(__file__).with_name(name).read_bytes()) for name in SOURCE_FILES}


def verify_fixture(value: bytes, sample: dict) -> bytes:
    if sample not in FIXTURES or len(value) != sample['bytes'] or native.digest(value) != sample['sha256']:
        raise ValueError('Exact public synthetic fixture required')
    native.audio_profile(value)
    with wave.open(io.BytesIO(value), 'rb') as audio:
        pcm = audio.readframes(audio.getnframes())
    if not 0 < len(pcm) <= RATE * 2 * 6 or len(pcm) % 2:
        raise ValueError('Bounded exact mono PCM input required')
    return pcm


def verify_local_fixtures() -> None:
    for sample in FIXTURES:
        path = FIXTURE_DIRECTORY / (sample['id'] + '.wav')
        if path.is_symlink() or not path.is_file() or path.stat().st_size != sample['bytes']:
            raise ValueError('Previously delivered public fixture required')
        verify_fixture(path.read_bytes(), sample)


def overlay() -> dict:
    return {'base_config': (REPO / 'vllm_omni/deploy/qwen3_omni_duplex.yaml').as_posix(),
        'async_chunk': True, 'duplex_session': {'max_sessions': 1, 'server_vad_model_path': VAD_FILE.as_posix()},
        'stages': [{'stage_id': 0, 'max_num_seqs': 1, 'default_sampling_params': {'max_tokens': 128}},
                   {'stage_id': 1, 'max_num_seqs': 1, 'default_sampling_params': {'max_tokens': 384}},
                   {'stage_id': 2, 'max_num_seqs': 1}]}


def server_command() -> list[str]:
    return ['vllm', 'serve', native.REMOTE_MODEL.as_posix(), '--omni', '--served-model-name', native.MODEL,
            '--host', '127.0.0.1', '--port', '8091', '--deploy-config', (WORK / 'deploy.json').as_posix()]


def session_update(sample: dict) -> dict:
    if sample not in FIXTURES: raise ValueError('Only fixed public locales are admitted')
    return {'type': 'session.update', 'session': {'model': native.MODEL,
        'instructions': sample['instructions'], 'max_output_tokens': 128, 'overlap_policy': 'barge_in_on_speech',
        'audio': {'input': {'format': {'type': 'audio/pcm', 'rate': RATE},
            'turn_detection': {'type': 'server_vad', 'threshold': .5, 'prefix_padding_ms': 300,
                'silence_duration_ms': 500, 'create_response': True, 'interrupt_response': True}},
            'output': {'format': {'type': 'audio/pcm', 'rate': RATE}}}}}


class StreamEvidence:
    """Measure decoded PCM deltas; terminal waveform return cannot pass."""
    def __init__(self):
        self.pcm = bytearray(); self.events = []; self.first_audio = None
        self.audio_done = None; self.done = None; self.speech_stopped = None
        self.caption = ''; self.response_id = None; self.unfinished_audio_observed = False
        self.caption_kind = None

    def accept(self, value: dict, elapsed: float) -> None:
        if not isinstance(value, dict) or not isinstance(value.get('type'), str): raise ValueError('JSON event required')
        kind = value['type']
        if kind == 'error': raise RuntimeError('Native protocol rejected the bounded request')
        if len(self.events) >= 2048: raise ValueError('Bounded event count exceeded')
        if kind in ('session.created', 'session.updated', 'input_audio_buffer.speech_started',
                    'input_audio_buffer.speech_stopped', 'response.created', 'response.output_audio.delta',
                    'response.output_audio.done', 'response.audio.done', 'response.done'):
            self.events.append({'type': kind, 'seconds': elapsed})
        if kind == 'input_audio_buffer.speech_stopped': self.speech_stopped = elapsed
        if kind == 'response.created':
            response_id = value.get('response', {}).get('id')
            if self.response_id is not None or not isinstance(response_id, str) or not 0 < len(response_id) <= 256:
                raise ValueError('One immutable created native response required')
            self.response_id = response_id
        if kind == 'response.output_audio.delta':
            if self.done is not None or self.audio_done is not None: raise ValueError('Audio after terminal event')
            if value.get('format') != 'pcm16' or value.get('sample_rate_hz') != RATE:
                raise ValueError('Actual event must declare raw PCM16 at24k')
            response_id = value.get('response_id')
            if not isinstance(response_id, str) or not 0 < len(response_id) <= 256 or \
                    self.response_id != response_id: raise ValueError('One bound created native response required')
            encoded = value.get('delta')
            if not isinstance(encoded, str) or not 0 < len(encoded) <= 2 * MAX_PCM_BYTES:
                raise ValueError('Bounded base64 PCM delta required')
            data = base64.b64decode(encoded, validate=True)
            if not data or len(data) % 2 or len(self.pcm) + len(data) > MAX_PCM_BYTES:
                raise ValueError('Bounded mono PCM16 delta required')
            samples = array.array('h', data)
            if sys.byteorder != 'little': samples.byteswap()
            rms = (sum(x * x for x in samples) / len(samples)) ** .5 / 32768
            if self.first_audio is None and rms > 0: self.first_audio = elapsed
            if rms > 0 and value.get('metadata', {}).get('end_of_turn') is False:
                self.unfinished_audio_observed = True
            self.events[-1]['samples'] = len(data) // 2
            self.events[-1]['rms'] = rms
            self.pcm.extend(data)
        if kind in ('response.output_text.delta', 'response.output_audio_transcript.delta', 'transcription.delta'):
            if self.caption_kind not in (None, kind): return
            self.caption_kind = kind
            delta = value.get('delta', '')
            if not isinstance(delta, str) or len(self.caption) + len(delta) > 4000: raise ValueError('Bounded native caption required')
            self.caption += delta
        if kind in ('response.output_audio.done', 'response.audio.done'):
            if self.response_id is None or value.get('response_id') != self.response_id:
                raise ValueError('Audio terminal must match the immutable native response')
            self.audio_done = elapsed
        if kind == 'response.done':
            if self.response_id is None or value.get('response', {}).get('id') != self.response_id:
                raise ValueError('Completed terminal must match the immutable native response')
            status = value.get('response', {}).get('status')
            if status != 'completed': raise RuntimeError('Native turn did not complete')
            self.done = elapsed

    def result(self) -> dict:
        deltas = [x for x in self.events if x['type'] == 'response.output_audio.delta']
        if len(deltas) < 2 or self.first_audio is None or self.done is None or self.first_audio >= self.done or \
                not self.unfinished_audio_observed or self.audio_done is None or self.audio_done > self.done:
            raise ValueError('Early multiple native audio deltas before turn completion required')
        if re.search(r'https?://|Bearer\s|sk-[A-Za-z0-9_-]+', self.caption): raise ValueError('Public bounded caption required')
        return {'first_audio_seconds_from_session_update': self.first_audio,
            'first_audio_seconds_from_server_speech_stop': None if self.speech_stopped is None else self.first_audio - self.speech_stopped,
            'done_seconds': self.done, 'decoded_audio_deltas': len(deltas), 'early_audio_before_done': True,
            'nonterminal_audio_observed': True,
            'caption': self.caption, 'caption_source': 'native model events; not independent ASR', 'events': self.events}


def validate_session_ready(value: dict) -> None:
    if value.get('type') != 'session.updated': raise ValueError('session.updated required before input')
    audio_input = value.get('session', {}).get('audio', {}).get('input', {})
    turn = audio_input.get('turn_detection', {})
    if audio_input.get('format') != {'type': 'audio/pcm', 'rate': RATE} or turn.get('type') != 'server_vad' or \
            turn.get('create_response') is not True or turn.get('interrupt_response') is not True:
        raise ValueError('Actual native input PCM/VAD ready acknowledgement required')


def wav_from_pcm(value: bytes) -> bytes:
    if not value or len(value) % 2 or len(value) > MAX_PCM_BYTES: raise ValueError('Bounded complete PCM16 required')
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(RATE); output.writeframes(value)
    result = buffer.getvalue(); native.audio_profile(result); return result


def check_cuda_metadata(driver: int, torch_cuda: str, devices: list[dict]) -> None:
    if driver < 13000 or not torch_cuda.startswith('13.') or len(devices) != 2 or \
        any('H100' not in x['name'] or tuple(x['capability']) != (9, 0) or not x['bf16'] for x in devices):
        raise ValueError('CUDA13 driver and exactly two BF16 H100 GPUs required before native load')


def cuda_guard() -> dict:
    import torch
    library = ctypes.CDLL('libcuda.so.1'); version = ctypes.c_int()
    if library.cuInit(0) or library.cuDriverGetVersion(ctypes.byref(version)):
        raise RuntimeError('CUDA driver initialization failed')
    devices = [{'name': torch.cuda.get_device_name(i), 'capability': list(torch.cuda.get_device_capability(i)),
                'bf16': torch.cuda.is_bf16_supported(including_emulation=False)} for i in range(torch.cuda.device_count())]
    check_cuda_metadata(version.value, torch.version.cuda or '', devices)
    return {'driver_api': version.value, 'torch_cuda': torch.version.cuda, 'devices': devices}


def safe_failure(error: Exception, stage: str) -> dict:
    result = native.safe_failure(error, stage if stage in STAGES else 'local_preflight')
    if type(error).__name__ in {'ImageBuildFailureError', 'ImageBuildError'}:
        result.update(code='cpu_image_build_failed', error_class=type(error).__name__)
    hints = {'unsupported_runtime': ('cuda13', 'vllm', 'architecture'),
             'invalid_stream': ('pcm', 'delta', 'protocol', 'terminal'),
             'missing_asset': ('fixture', 'silero', 'checksum', 'cached'),
             'loopback_unavailable': ('connection refused', 'network', 'websocket')}
    message = str(error).lower()
    result['reason_hints'] = [name for name, words in hints.items() if any(word in message for word in words)]
    return result


def progress(stage: str) -> None:
    if stage not in STAGES: raise ValueError('Finite diagnostic stage required')
    native.save_json(WORK / 'progress.json', {'stage': stage})
    print(json.dumps({'status': 'progress', 'stage': stage}), flush=True)


def server_reason_hints(path=WORK / 'server.log') -> list[str]:
    """Fixed diagnostic categories from bounded public startup logs, never raw text."""
    if not path.is_file(): return []
    with path.open('rb') as source:
        source.seek(max(0, path.stat().st_size - 256 * 1024))
        text = source.read(256 * 1024).decode('utf8', errors='replace').lower()
    mapping = {'gpu_memory_exhausted': ('out of memory', 'no available memory', 'not enough free memory'),
        'dependency_import_failed': ('modulenotfounderror', 'importerror', 'undefined symbol', 'cannot open shared object'),
        'invalid_cli': ('unrecognized arguments', 'no such option'),
        'invalid_configuration': ('validationerror', 'unsupported architecture', 'not supported for', 'invalid configuration'),
        'engine_initialization_failed': ('engine core initialization failed', 'failed to initialize'),
        'offline_asset_unavailable': ('offline mode', 'local files', 'filenotfounderror')}
    return [name for name, words in mapping.items() if any(word in text for word in words)]


def validate_deploy(deploy) -> None:
    if deploy.session_mode != 'duplex' or deploy.async_chunk is not True or \
            deploy.duplex_session.max_sessions != 1 or deploy.duplex_session.server_vad_model_path != VAD_FILE.as_posix():
        raise ValueError('Exact async engine-duplex session deployment required')
    stages = {stage.stage_id: stage for stage in deploy.stages}
    if set(stages) != {0, 1, 2}: raise ValueError('Exact three native stages required')
    for index, device, utilization in ((0, '0', .9), (1, '1', .6), (2, '1', .1)):
        stage = stages[index]
        if str(stage.devices) != device or stage.gpu_memory_utilization != utilization or stage.max_num_seqs != 1:
            raise ValueError('Exact two-H100 placement, memory allocation and sequence bounds required')
    if stages[0].default_sampling_params['max_tokens'] != 128 or stages[1].default_sampling_params['max_tokens'] != 384 or \
            stages[1].default_sampling_params['seed'] != 42:
        raise ValueError('Bounded native sampling with preserved Talker seed required')
    connector = (deploy.connectors or {}).get('connector_of_shared_memory', {})
    if connector.get('name') != 'SharedMemoryConnector' or connector.get('extra') != {
            'initial_codec_chunk_frames': 4, 'codec_chunk_frames': 25, 'codec_left_context_frames': 25}:
        raise ValueError('Pinned native streaming codec connector required')


def verify_source() -> None:
    result = subprocess.run(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=5, check=True)
    if result.stdout.strip() != OMNI_REVISION: raise ValueError('Pinned Omni source required')
    changed = subprocess.run(['git', '-C', str(REPO), 'diff', '--quiet'], timeout=5)
    if changed.returncode: raise ValueError('Unmodified pinned Omni source required')
    if VAD_FILE.is_symlink() or not VAD_FILE.is_file() or not 0 < VAD_FILE.stat().st_size <= 32 * 1024**2 or \
            native.digest(VAD_FILE.read_bytes()) != VAD_SHA256:
        raise ValueError('Pinned local Silero checksum required')
    for sample in FIXTURES: verify_fixture((PREP / (sample['id'] + '.wav')).read_bytes(), sample)


def cache_vad() -> None:
    PREP.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(VAD_URL, timeout=30) as response:
        value = response.read(32 * 1024**2 + 1)
    if not 0 < len(value) <= 32 * 1024**2 or native.digest(value) != VAD_SHA256:
        raise ValueError('Pinned public Silero artifact checksum required')
    VAD_FILE.write_bytes(value)


async def loopback_preflight() -> None:
    """Actual local transport under the same egress block, not fake native inference."""
    import websockets
    async def echo(socket):
        async for message in socket: await socket.send(message)
    async with websockets.serve(echo, '127.0.0.1', 0, max_size=2 * MAX_PCM_BYTES) as server:
        port = server.sockets[0].getsockname()[1]
        async with websockets.connect(f'ws://127.0.0.1:{port}/v1/realtime?duplex=1', open_timeout=3) as socket:
            await socket.send(json.dumps(session_update(FIXTURES[0])))
            if json.loads(await socket.recv()) != session_update(FIXTURES[0]): raise ValueError('Loopback WebSocket changed JSON')
            event = {'type': 'response.output_audio.delta', 'delta': base64.b64encode(b'\x10\x00' * 480).decode(),
                     'format': 'pcm16', 'sample_rate_hz': RATE, 'response_id': 'public-fixture',
                     'metadata': {'end_of_turn': False}}
            evidence = StreamEvidence()
            evidence.accept({'type': 'response.created', 'response': {'id': 'public-fixture'}}, .05)
            for elapsed in (.1, .2):
                await socket.send(json.dumps(event)); evidence.accept(json.loads(await socket.recv()), elapsed)
            evidence.accept({'type': 'response.output_audio.done', 'response_id': 'public-fixture'}, .25)
            evidence.accept({'type': 'response.done', 'response': {'id': 'public-fixture', 'status': 'completed'}}, .3)
            if not evidence.result()['early_audio_before_done']: raise ValueError('CPU PCM protocol fixture failed')


def cpu_runtime() -> dict:
    stage = 'cpu_pins'
    try:
        WORK.mkdir(exist_ok=True); progress(stage)
        verify_source()
        if os.environ.get('HF_TOKEN') or os.environ.get('HUGGING_FACE_HUB_TOKEN'): raise ValueError('No HF credentials allowed')
        stage = 'cpu_imports'; progress(stage)
        import torch
        import onnxruntime
        from transformers import AutoConfig
        from vllm_omni.model_executor.models.registry import OmniModelRegistry
        from vllm_omni.config.pipeline_registry import resolve_pipeline_config
        from vllm_omni.config.stage_config import load_deploy_config
        stage = 'cpu_versions'; progress(stage)
        if importlib.metadata.version('vllm') != '0.30.0': raise ValueError('Pinned vLLM0.30 required')
        stage = 'cpu_model_config'; progress(stage)
        config = AutoConfig.from_pretrained(str(native.REMOTE_MODEL), local_files_only=True, trust_remote_code=False)
        stage = 'cpu_registry'; progress(stage)
        if config.architectures != ['Qwen3OmniMoeForConditionalGeneration'] or \
                config.architectures[0] not in OmniModelRegistry.get_supported_archs():
            raise ValueError('Local Qwen HF architecture must resolve in Omni registry')
        stage = 'cpu_pipeline'; progress(stage)
        pipeline = resolve_pipeline_config('qwen3_omni_moe', hf_config=config)
        if pipeline.duplex_plugin != 'vllm_omni.model_executor.models.qwen3_omni.duplex.plugin.Qwen3OmniDuplexPlugin':
            raise ValueError('Pinned engine-duplex plugin must resolve on CPU')
        stage = 'cpu_deploy'; progress(stage)
        cpu_overlay = PREP / 'cpu-deploy.json'; cpu_overlay.write_text(json.dumps(overlay()), encoding='utf8')
        deploy = load_deploy_config(str(cpu_overlay))
        validate_deploy(deploy)
        if getattr(config, 'talker_config').speaker_id != {'chelsie': 2301, 'ethan': 2302, 'aiden': 2303}:
            raise ValueError('Pinned default speaker mapping required')
        stage = 'cpu_vad'; progress(stage)
        session = onnxruntime.InferenceSession(str(VAD_FILE), providers=['CPUExecutionProvider'])
        if not session.get_inputs(): raise ValueError('Local Silero must initialize on CPU')
        stage = 'cpu_cli'; progress(stage)
        cli = subprocess.run(['vllm', 'serve', '--omni', '--help'], capture_output=True, text=True, timeout=30, check=True)
        if '--deploy-config' not in cli.stdout or '--served-model-name' not in cli.stdout:
            raise ValueError('Pinned Omni CLI arguments required')
        stage = 'cpu_lock'; progress(stage)
        lock = subprocess.run([sys.executable, '-m', 'pip', 'freeze', '--all'], capture_output=True, timeout=30, check=True).stdout
        stage = 'cpu_protocol'; progress(stage); asyncio.run(asyncio.wait_for(loopback_preflight(), timeout=10))
        stage = 'cpu_delivery'; progress(stage); delivery = native.delivery_preflight()
        native.validate_delivery(delivery)
        return {'status': 'runtime_preflight_completed', 'model_revision': native.MODEL_REVISION,
            'omni_revision': OMNI_REVISION, 'base_image': BASE_IMAGE, 'vad_sha256': VAD_SHA256,
            'source_hashes': source_hashes(), 'lock_sha256': native.digest(lock),
            'versions': {name: importlib.metadata.version(name) for name in ('vllm', 'vllm-omni', 'torch', 'transformers', 'onnxruntime', 'websockets')},
            'torch_cuda': torch.version.cuda, 'loopback_websocket_verified': True,
            'local_registry_verified': True, 'vad_cpu_verified': True,
            'gpu': False, 'model_loaded': False, 'inference': False, 'delivery': delivery}
    except Exception as error:
        failure = safe_failure(error, stage); print(json.dumps(failure), flush=True); return failure


async def native_turn(sample: dict) -> tuple[bytes, dict]:
    import websockets
    evidence = StreamEvidence(); connect_began = time.monotonic()
    async with websockets.connect(SOCKET_URL, open_timeout=5, max_size=2 * MAX_PCM_BYTES, max_queue=32) as socket:
        began = time.monotonic()
        await socket.send(json.dumps(session_update(sample)))
        deadline = began + HANDSHAKE_SECONDS
        while time.monotonic() < deadline:
            value = json.loads(await asyncio.wait_for(socket.recv(), deadline - time.monotonic()))
            evidence.accept(value, time.monotonic() - began)
            if value['type'] == 'session.updated':
                validate_session_ready(value); break
        else: raise TimeoutError('Native session handshake expired')
        input_pcm = verify_fixture((PREP / (sample['id'] + '.wav')).read_bytes(), sample)
        input_timing = {}; appends = []; sent_fixture = bytearray()
        async def upload():
            # Ordinary 1x capture continues with zeros while the native reply streams.
            origin = time.monotonic()
            next_at = origin + FRAME_SAMPLES / RATE
            index = 0
            while True:
                # Each complete 200ms capture block is sent afterward; a blocked send never triggers burst catchup.
                await asyncio.sleep(max(0, next_at - time.monotonic()))
                sent_at = time.monotonic(); piece = input_pcm[index:index + FRAME_SAMPLES * 2]
                block = piece + bytes(FRAME_SAMPLES * 2 - len(piece))
                await socket.send(json.dumps({'type': 'input_audio_buffer.append',
                    'audio': base64.b64encode(block).decode('ascii')}))
                completed_at = time.monotonic()
                appends.append({'send_start_seconds': sent_at - began, 'send_completed_seconds': completed_at - began,
                    'fixture_samples': len(piece) // 2, 'zero_padding_samples': (len(block) - len(piece)) // 2,
                    'scheduler_delay_ms': max(0, sent_at - next_at) * 1000})
                sent_fixture.extend(piece)
                if index == 0: input_timing['first_append_send_completed_seconds'] = completed_at - began
                if index < len(input_pcm) <= index + FRAME_SAMPLES * 2:
                    input_timing['complete_fixture_upload_seconds'] = completed_at - began
                index += FRAME_SAMPLES * 2
                next_at = completed_at + FRAME_SAMPLES / RATE
        sender = asyncio.create_task(upload())
        try:
            while evidence.done is None:
                value = json.loads(await socket.recv()); evidence.accept(value, time.monotonic() - began)
            # Native generation terminal does not depend on playback ACK. No heard-history assertion is sent.
            await socket.send(json.dumps({'type': 'session.close'}))
        finally:
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
    value = wav_from_pcm(bytes(evidence.pcm)); result = evidence.result()
    result.update({'id': sample['id'], 'locale': sample['locale'], 'input_sha256': sample['sha256'],
        'input_audio_seconds': len(input_pcm) / (RATE * 2), 'input_pcm_sha256': native.digest(input_pcm),
        'input_replay_configured_rate': 1, 'input_packet_ms': 200,
        'input_pcm_sent_sha256': native.digest(bytes(sent_fixture)), 'input_pcm_sent_bytes': len(sent_fixture),
        'append_receipts': appends, 'audio': native.audio_profile(value), 'audible_playback_verified': False,
        'connection_to_session_update_send_seconds': began - connect_began, **input_timing})
    if 'complete_fixture_upload_seconds' not in input_timing or bytes(sent_fixture) != input_pcm:
        raise ValueError('Entire fixed fixture must be delivered before accepting its reply')
    result['first_audio_seconds_from_complete_fixture_upload'] = evidence.first_audio - input_timing['complete_fixture_upload_seconds']
    return value, result


async def wait_ready(process, deadline: float) -> None:
    import aiohttp
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2)) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None: raise RuntimeError('Native server exited during startup')
            try:
                async with client.get('http://127.0.0.1:8091/health') as response:
                    if response.status == 200: return
            except (aiohttp.ClientError, asyncio.TimeoutError): pass
            await asyncio.sleep(.5)
    raise TimeoutError('Native server startup deadline expired')


def stop_server(process) -> bool:
    if process.poll() is not None: return True
    os.killpg(process.pid, signal.SIGTERM)
    try: process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, KILL_SIGNAL)
        try: process.wait(timeout=3)
        except subprocess.TimeoutExpired: return False
    return process.poll() is not None


def validate_live_artifacts(values: dict) -> None:
    if set(values) != set(native.artifact_limits('native')): raise ValueError('Exact three live artifacts required')
    for name, value in values.items():
        if not isinstance(value, bytes) or not 0 < len(value) <= native.artifact_limits('native')[name]:
            raise ValueError('Bounded live artifacts required')
    report = json.loads(values['report.json'])
    expected = {'status': 'completed', 'model': native.MODEL, 'model_revision': native.MODEL_REVISION,
        'omni_revision': OMNI_REVISION, 'base_image': BASE_IMAGE, 'gpu': 'H100:2', 'gpu_count': 2,
        'base_config': 'qwen3_omni_duplex.yaml', 'async_chunk': True, 'native_audio_turns': 2,
        'runtime_downloads': False, 'banking_access': False, 'room_microphone': False, 'dedicated_tts': False,
        'browser': False, 'barge_in_qualified': False, 'human_voice_quality_verified': False,
        'server_exit_observed': True, 'speaker_selection_supported': False, 'runtime_default_speaker': 'Chelsie'}
    if any(report.get(key) != value for key, value in expected.items()) or len(report.get('samples', [])) != 2:
        raise ValueError('Exact native live Stage A report required')
    for sample, evidence in zip(FIXTURES, report['samples']):
        if evidence.get('id') != sample['id'] or evidence.get('locale') != sample['locale'] or \
            evidence.get('input_sha256') != sample['sha256'] or not evidence.get('early_audio_before_done') or \
            evidence.get('nonterminal_audio_observed') is not True or \
            evidence.get('decoded_audio_deltas', 0) < 2 or evidence.get('audible_playback_verified') is not False or \
            evidence.get('audio') != native.audio_profile(values[sample['id'] + '.wav']):
            raise ValueError('Exact early native delta and artifact hash evidence required')


def live_worker() -> None:
    process = None; began = time.monotonic(); deadline = began + WORKER_SECONDS
    if os.environ.get('HF_TOKEN') or os.environ.get('HUGGING_FACE_HUB_TOKEN'):
        raise ValueError('Runtime HF credentials are forbidden')
    progress('cuda_guard'); hardware = cuda_guard()
    progress('offline_cache_verification'); verify_source(); native.verify_assets(native.REMOTE_MODEL)
    (WORK / 'deploy.json').write_text(json.dumps(overlay()), encoding='utf8')
    progress('server_startup'); ready_deadline = min(deadline - 2 * REQUEST_SECONDS - 15, began + STARTUP_SECONDS)
    outputs = {}; samples = []; exited = False; failure_stage = None
    try:
        with (WORK / 'server.log').open('wb') as logs:
            process = subprocess.Popen(server_command(), stdout=logs, stderr=subprocess.STDOUT,
                start_new_session=True, cwd=str(REPO), env={**os.environ, **OFFLINE})
            native.save_json(WORK / 'server-pid.json', {'pid': process.pid})
            asyncio.run(wait_ready(process, ready_deadline)); ready_seconds = time.monotonic() - began
            for sample in FIXTURES:
                progress('native_ws_' + sample['id'])
                if deadline - time.monotonic() < REQUEST_SECONDS + 12: raise TimeoutError('No remaining native turn budget')
                audio, result = asyncio.run(asyncio.wait_for(native_turn(sample), timeout=REQUEST_SECONDS))
                outputs[sample['id'] + '.wav'] = audio; samples.append(result)
    except BaseException:
        failure_stage = json.loads((WORK / 'progress.json').read_text(encoding='utf8'))['stage']
        raise
    finally:
        progress('cleanup')
        if process is not None: exited = stop_server(process)
        if failure_stage is not None: progress(failure_stage)
    if not exited: raise RuntimeError('Native server exit was not observed')
    report = {**plan(), 'status': 'completed', 'server_ready_seconds': ready_seconds,
        'worker_seconds_measured': time.monotonic() - began, 'hardware': hardware,
        'server_exit_observed': True, 'samples': samples}
    outputs['report.json'] = json.dumps(report, ensure_ascii=False, indent=2).encode('utf8')
    validate_live_artifacts(outputs)
    for name, value in outputs.items(): (WORK / name).write_bytes(value)


def persist_live(values: dict, commit, root=native.REMOTE_OUTPUT) -> dict:
    validate_live_artifacts(values)
    run_id = secrets.token_hex(16); directory = Path(root) / run_id; directory.mkdir(exist_ok=False)
    for name, value in values.items():
        with (directory / name).open('xb') as output: output.write(value)
    commit()
    return native.validate_delivery({'status': 'artifacts_committed', 'kind': 'native',
        'output_volume': native.OUTPUT_VOLUME, 'model_revision': native.MODEL_REVISION, 'run_id': run_id,
        'files': {name: {'bytes': len(value), 'sha256': native.digest(value)} for name, value in values.items()}})


def kill_orphan_server() -> None:
    """Parent watchdog after child timeout; absolute Function timeout is the backstop."""
    file = WORK / 'server-pid.json'
    if not file.is_file() or file.stat().st_size > 128: return
    value = json.loads(file.read_text(encoding='utf8'))
    if set(value) != {'pid'} or type(value['pid']) is not int or value['pid'] <= 1:
        raise ValueError('Only the isolated child server process may be terminated')
    try: os.killpg(value['pid'], KILL_SIGNAL)
    except ProcessLookupError: pass


async def download_live(receipt: dict, volume=None, timeout=native.DOWNLOAD_SECONDS) -> dict:
    native.validate_delivery(receipt)
    if receipt['kind'] != 'native' or not 0 < timeout <= native.DOWNLOAD_SECONDS: raise ValueError('Bounded native delivery required')
    async def read():
        nonlocal volume
        if volume is None:
            import modal
            volume = modal.Volume.from_name(native.OUTPUT_VOLUME)
        outputs = {}
        for name, expected in receipt['files'].items():
            value = bytearray()
            async for block in volume.read_file.aio(receipt['run_id'] + '/' + name):
                if not isinstance(block, bytes) or len(value) + len(block) > expected['bytes']:
                    raise ValueError('Bounded exact live download required')
                value.extend(block)
            if len(value) != expected['bytes'] or native.digest(value) != expected['sha256']:
                raise ValueError('Exact live download size/hash required')
            outputs[name] = bytes(value)
        validate_live_artifacts(outputs); return outputs
    return await asyncio.wait_for(read(), timeout=timeout)


def gpu_live() -> dict:
    stage = 'local_preflight'; child_timed_out = False
    try:
        WORK.mkdir(exist_ok=False)
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker'],
            capture_output=True, timeout=WORKER_SECONDS, env={**os.environ, **OFFLINE})
        if result.returncode:
            failure = WORK / 'failure.json'
            if failure.is_file() and failure.stat().st_size <= 4096:
                value = json.loads(failure.read_text(encoding='utf8'))
                if set(value) <= {'status', 'stage', 'code', 'error_class', 'reason_hints', 'server_reason_hints'} and value.get('status') == 'failed': return value
            stage = json.loads((WORK / 'progress.json').read_text(encoding='utf8')).get('stage', stage)
            raise RuntimeError('Bounded native child failed')
        stage = 'artifact_commit'
        import modal
        return persist_live({name: (WORK / name).read_bytes() for name in native.artifact_limits('native')},
            modal.Volume.from_name(native.OUTPUT_VOLUME).commit)
    except Exception as error:
        child_timed_out = isinstance(error, subprocess.TimeoutExpired)
        try: stage = json.loads((WORK / 'progress.json').read_text(encoding='utf8')).get('stage', stage)
        except (OSError, ValueError): pass
        failure = {**safe_failure(error, stage), 'server_reason_hints': server_reason_hints()}
        print(json.dumps(failure), flush=True); return failure
    finally:
        try:
            if child_timed_out: kill_orphan_server()
        except (OSError, ValueError): pass


def build_runtime_image():
    import modal
    verify_local_fixtures()
    image = (modal.Image.from_registry(BASE_IMAGE).entrypoint([]).apt_install('git')
        .run_commands('timeout --signal=TERM --kill-after=10s 120s git clone --no-checkout https://github.com/vllm-project/vllm-omni.git /opt/vllm-omni',
                      f'timeout --signal=TERM --kill-after=5s 30s git -C /opt/vllm-omni checkout --detach {OMNI_REVISION}',
                      'cd /opt/vllm-omni && timeout --signal=TERM --kill-after=10s 1200s uv pip install --python "$(python3 -c \'import sys; print(sys.executable)\')" --no-cache-dir "."')
        .run_commands('timeout --signal=TERM --kill-after=5s 120s uv pip install --python "$(python3 -c \'import sys; print(sys.executable)\')" --no-cache-dir websockets==15.0.1')
        .add_local_python_source('qwen_live_audition', 'qwen_native_audition', copy=True)
        .add_local_file(str(native.ASSETS_FILE), '/root/qwen_native_assets.json', copy=True))
    for sample in FIXTURES:
        image = image.add_local_file(str(FIXTURE_DIRECTORY / (sample['id'] + '.wav')), (PREP / (sample['id'] + '.wav')).as_posix(), copy=True)
    return image.env({'HF_HUB_DISABLE_IMPLICIT_TOKEN': '1'}).run_commands(
        'timeout --signal=TERM --kill-after=5s 45s python3 /root/qwen_live_audition.py --cache-vad')


def require_python3_fix_provenance() -> dict:
    """Only the diagnosed failed CPU build admits one explicitly selected correction."""
    def read(path):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
            raise ValueError('Preserved bounded CPU failure provenance required')
        value = json.loads(path.read_text(encoding='utf8'))
        if not isinstance(value, dict): raise ValueError('Typed CPU failure provenance required')
        return value
    original = read(DIRECTORY / 'runtime-admitted.json')
    if original != {'status': 'spent_before_dispatch', 'model_revision': native.MODEL_REVISION, 'omni_revision': OMNI_REVISION}:
        raise ValueError('Original diagnosed runtime admission must remain spent')
    value = read(PYTHON3_PROVENANCE)
    expected = {'status': 'image_command_failure_confirmed', 'app_state': 'stopped', 'tasks': 0,
        'gpu_dispatched': False, 'cpu_function_dispatched': False, 'exit_code': 127,
        'reason': 'base_image_has_python3_without_python_alias',
        'failed_command': 'python -m pip install websockets==15.0.1'}
    if any(value.get(key) != wanted for key, wanted in expected.items()) or \
        value.get('gpu_dispatched') is not False or value.get('cpu_function_dispatched') is not False or \
        not re.fullmatch(r'ap-[A-Za-z0-9]+', value.get('app_id', '')) or \
        not re.fullmatch(r'[0-9]{8}-[0-9]{6}-[0-9]{16,24}/failure\.json', value.get('original_failure', '')):
        raise ValueError('Stopped non-GPU python-alias failure must be independently diagnosed')
    failure = read(DIRECTORY / value['original_failure'])
    if failure.get('status') != 'failed' or failure.get('stage') != 'cpu_runtime':
        raise ValueError('Preserved original CPU failure required')
    return {'original_app_id': value['app_id'], 'original_failure_sha256': native.digest(
        (DIRECTORY / value['original_failure']).read_bytes()), 'correction': 'python3_same_native_interpreter'}


def validate_runtime(value: dict, compare_sources=True) -> dict:
    expected = {'status': 'runtime_preflight_verified', 'model_revision': native.MODEL_REVISION,
        'omni_revision': OMNI_REVISION, 'base_image': BASE_IMAGE, 'vad_sha256': VAD_SHA256,
        'loopback_websocket_verified': True, 'local_registry_verified': True, 'vad_cpu_verified': True,
        'gpu': False, 'model_loaded': False, 'inference': False}
    if not isinstance(value, dict) or any(value.get(key) != wanted for key, wanted in expected.items()) or \
            not re.fullmatch(r'im-[A-Za-z0-9]+', value.get('image_id', '')) or \
            not re.fullmatch(r'[a-f0-9]{64}', value.get('lock_sha256', '')) or \
            not value.get('torch_cuda', '').startswith('13.') or value.get('versions', {}).get('vllm') != '0.30.0' or \
            set(value.get('source_hashes', {})) != set(SOURCE_FILES) or \
            any(not re.fullmatch(r'[a-f0-9]{64}', x) for x in value['source_hashes'].values()):
        raise ValueError('Exact pinned CPU runtime receipt required before GPU admission')
    if compare_sources and value['source_hashes'] != source_hashes(): raise ValueError('Prepared image source no longer matches')
    native.validate_delivery(value['delivery'])
    if value['delivery']['kind'] != 'delivery-preflight': raise ValueError('CPU delivery evidence required')
    return value


def require_runtime() -> dict:
    if RUNTIME_RECEIPT.is_symlink() or not RUNTIME_RECEIPT.is_file() or RUNTIME_RECEIPT.stat().st_size > 16384:
        raise ValueError('Reviewed CPU runtime receipt required')
    return validate_runtime(json.loads(RUNTIME_RECEIPT.read_text(encoding='utf8')))


def build_app(mode: str, runtime=None):
    if mode not in ('cpu', 'gpu') or gpu_live.__module__ != 'qwen_live_audition': raise ValueError('Canonical bounded source required')
    import modal
    image = build_runtime_image() if mode == 'cpu' else modal.Image.from_id(validate_runtime(runtime)['image_id'])
    app = modal.App('elsewhere-qwen-duplex-cpu-preflight' if mode == 'cpu' else 'elsewhere-qwen-duplex-stage-a')
    common = dict(image=image, volumes={'/cache': modal.Volume.from_name(native.VOLUME_NAME).read_only(),
        native.REMOTE_OUTPUT.as_posix(): modal.Volume.from_name(native.OUTPUT_VOLUME)},
        env=OFFLINE, block_network=True, max_containers=1, min_containers=0, buffer_containers=0,
        retries=0, scaledown_window=2, single_use_containers=True, serialized=False, include_source=True,
        startup_timeout=60)
    if mode == 'cpu': function = app.function(cpu=(2, 4), memory=(4096, 16384), timeout=CPU_SECONDS, **common)(cpu_runtime)
    else: function = app.function(gpu='H100:2', cpu=(4, 8), memory=(32768, 131072), timeout=FUNCTION_SECONDS, **common)(gpu_live)
    return app, function, image


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__); modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--plan', action='store_true'); modes.add_argument('--prepare-runtime', action='store_true')
    modes.add_argument('--prepare-runtime-python3-fix', action='store_true',
        help='One explicit CPU correction after the preserved diagnosed python-alias build failure')
    modes.add_argument('--execute', action='store_true'); modes.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    modes.add_argument('--cache-vad', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.cache_vad: cache_vad(); return 0
    if args.worker:
        try:
            if os.environ.get('HF_HUB_OFFLINE') != '1' or not WORK.is_dir(): raise ValueError('Offline isolated worker required')
            live_worker(); return 0
        except Exception as error:
            stage = 'local_preflight'
            try: stage = json.loads((WORK / 'progress.json').read_text(encoding='utf8'))['stage']
            except (OSError, ValueError, KeyError): pass
            failure = {**safe_failure(error, stage), 'server_reason_hints': server_reason_hints()}
            native.save_json(WORK / 'failure.json', failure); print(json.dumps(failure), flush=True); return 1
    cpu_mode = args.prepare_runtime or args.prepare_runtime_python3_fix
    if not cpu_mode and not args.execute:
        print(json.dumps(plan(), indent=2)); return 0
    stage = 'local_preflight'; destination = DIRECTORY / (time.strftime('%Y%m%d-%H%M%S') + '-' + str(time.time_ns()))
    try:
        native.require_cache_receipt(); verify_local_fixtures()
        runtime = require_runtime() if args.execute else None
        provenance = require_python3_fix_provenance() if args.prepare_runtime_python3_fix else {}
        marker = 'gpu-admitted.json' if args.execute else 'runtime-python3-fix-admitted.json' if args.prepare_runtime_python3_fix else 'runtime-admitted.json'
        native.save_json(DIRECTORY / marker,
            {'status': 'spent_before_dispatch', 'model_revision': native.MODEL_REVISION, 'omni_revision': OMNI_REVISION,
             **provenance}, exclusive=True)
        stage = 'app_definition'; app, function, image = build_app('gpu' if args.execute else 'cpu', runtime)
        stage = 'server_startup' if args.execute else 'cpu_runtime'
        budget = CLIENT_SECONDS if args.execute else CPU_CLIENT_SECONDS
        with app.run(detach=False):
            # Dependency image build has separate shell bounds; this deadline covers the admitted job and delivery.
            deadline = time.monotonic() + budget
            job = function.spawn()
            try: value = job.get(timeout=max(1, deadline - time.monotonic() - native.DOWNLOAD_SECONDS))
            finally:
                try: job.cancel(terminate_containers=True)
                except Exception: pass
            image_id = image.object_id
        if not isinstance(value, dict) or value.get('status') == 'failed':
            native.save_json(destination / 'failure.json', value if isinstance(value, dict) else safe_failure(ValueError(), stage))
            print(json.dumps(value)); return 1
        stage = 'artifact_download'; remaining = min(native.DOWNLOAD_SECONDS, deadline - time.monotonic())
        if cpu_mode:
            if value.get('status') != 'runtime_preflight_completed': raise ValueError('CPU preflight must pass completely')
            asyncio.run(native.download_artifacts(value['delivery'], timeout=remaining))
            value.update(status='runtime_preflight_verified', image_id=image_id)
            validate_runtime(value); native.save_json(RUNTIME_RECEIPT, value)
            print(json.dumps({'status': 'runtime_preflight_verified', 'image_id': image_id,
                'omni_revision': OMNI_REVISION, 'gpu': False, 'model_loaded': False, 'inference': False,
                'termination_verification_required': True})); return 0
        outputs = asyncio.run(download_live(value, timeout=remaining))
        destination.mkdir(parents=True, exist_ok=False)
        for name, data in outputs.items(): (destination / name).write_bytes(data)
        native.save_json(destination / 'delivery.json', value)
        print(json.dumps({'status': 'completed', 'output_directory': str(destination),
            'barge_in_qualified': False, 'human_voice_quality_verified': False,
            'termination_verification_required': True})); return 0
    except Exception as error:
        value = safe_failure(error, stage); native.save_json(destination / 'failure.json', value)
        print(json.dumps(value)); return 1


if __name__ == '__main__':
    from importlib import import_module
    raise SystemExit(import_module('qwen_live_audition').main())
