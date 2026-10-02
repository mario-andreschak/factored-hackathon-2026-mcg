"""Source-only initial adaptive-role qualification; no default cloud/model calls.

One fixed initial prompt, one NATM1 voice, <=3 independent synthetic episodes.
--prepare-fixtures is local System.Speech input generation, never room audio.
--execute and --verify-asr are separate explicit paid modes, with no retry.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import time
import urllib.request
import wave
from unittest.mock import patch

import personaplex_closed_result as closed
import personaplex_forced_result as prior
import personaplex_modal as pinned
from personaplex_browser import DEFAULT_CACHE, cache_reference
from personaplex_pcm_core import FRAME_BYTES, FRAME_SAMPLES
from personaplex_pcm_server import COMMON_BOUNDARY
from modal_diagnostic import diagnostic

EXPERIMENT = 'initial_adaptive_roles_native_v1'
ADAPTIVE_PROMPT = (
    'You enjoy having a good conversation. You are one companion with three named forms and one consistent natural voice. '
    'Choose the form that fits the user\'s tone, conversational pace, and expressed need. '
    'Moss is a gentle ancient turtle: calm, warm, slow, and brief when the user feels overwhelmed or wants to slow down. '
    'Orbit is an observatory companion: clear, thoughtful, practical, and concise when the user wants analysis or a plan. '
    'Spark is a playful roadside mechanic: brisk, energetic, and original when the user wants momentum or lively company. '
    'Listen when interrupted. Let the user\'s changing pace guide subsequent style naturally. '
    'When asked who you are, name the matching form. When the form changes, name it briefly once. '
    'Do not announce a classification process. ' + COMMON_BOUNDARY)
FIXTURE_SCRIPTS = (
    ('anxious', -1, 'I feel overwhelmed and need to slow down. Who are you, and can you help me take one small step?'),
    ('planning', 0, 'I want to plan tomorrow clearly. Who are you, and can we make a simple three step plan?'),
    ('energetic', 2, 'I am ready to go! Who are you? Let us do something fun and get moving.'),
    ('slow-again', -1, 'Wait, I feel overwhelmed. Who are you now? Please slow down and help me breathe.'),
)
# The third episode changes ordinary USER audio at12s. Its system prompt/cache
# stays unchanged throughout, so actual adaptation is a model hypothesis.
EPISODES = (
    {'id': 'anxious', 'frames': 300, 'expected_forms': ['moss'], 'clips': [(0, 'anxious')]},
    {'id': 'planning', 'frames': 300, 'expected_forms': ['orbit'], 'clips': [(0, 'planning')]},
    {'id': 'energetic-to-calm', 'frames': 400, 'expected_forms': ['spark', 'moss'],
     'clips': [(0, 'energetic'), (150, 'slow-again')]},
)
MAX_INPUT_FRAMES, MAX_EPISODE_FRAMES = 150, 400
MAX_TOTAL_FRAMES = sum(episode['frames'] for episode in EPISODES)
WORKER_SECONDS = 360
ROOT = Path(__file__).resolve().parent.parent
DIRECTORY = ROOT / '.local' / 'personaplex-adaptive-prompt'
FIXTURES = DIRECTORY / 'fixtures'
# Modal container paths must retain POSIX separators on a Windows launcher.
REMOTE_FIXTURES = PurePosixPath('/opt/personaplex-adaptive-fixtures')
WORK = Path('/tmp/personaplex-adaptive-prompt')
FIXTURE_GENERATOR = Path(__file__).with_name('personaplex_adaptive_fixtures.ps1')
SOURCE_MODULES = ('personaplex_adaptive_prompt', 'personaplex_closed_result', 'personaplex_forced_result',
                  'personaplex_pcm_core', 'personaplex_modal', 'personaplex_browser', 'personaplex_pcm_server', 'modal_diagnostic')
ARTIFACT_NAMES = frozenset({'report.json'} | {episode['id'] + ending for episode in EPISODES
                          for ending in ('-input.wav', '-output.wav', '-tokens.json')})


def digest(value: bytes) -> str: return hashlib.sha256(value).hexdigest()
PROMPT_SHA256 = digest(ADAPTIVE_PROMPT.encode('utf8'))
SCRIPT_SHA256 = digest(json.dumps(FIXTURE_SCRIPTS, separators=(',', ':')).encode('utf8'))


def plan() -> dict:
    return {**pinned.plan(), 'experiment': EXPERIMENT, 'voice': pinned.VOICE, 'initial_prompt_sha256': PROMPT_SHA256,
        'initial_prompt': ADAPTIVE_PROMPT, 'episodes': EPISODES, 'maximum_episodes': 3,
        'clock_seconds': MAX_TOTAL_FRAMES * .08, 'public_audio_seconds': MAX_TOTAL_FRAMES * .08, 'worker_seconds': WORKER_SECONDS,
        'prerequisite': 'Existing private image with the exact model/source pins; no runtime gated-model access step',
        'model_loads': 1, 'prompt_policy': 'Same fixed adaptive prompt before each independent episode only',
        'within_episode': 'Native free speech; no forced text, system updates, cache resets or re-prime',
        'input': 'Fixed local System.Speech en-US scripts only; four hashed PCM24k mono clips, no microphone',
        'cache': 'Existing private pinned image plus source/fixture COPY overlay; no weight rebuild/download fallback',
        'credential': 'Existing Modal profile only on explicit execution; no runtime HF token or provider key',
        'banking_access': False, 'production_enabled': False, 'browser_provider_changed': False,
        'adaptive_behavior_verified': False, 'human_style_verified': False,
        'asr': 'Separate explicit mode after all completed synthetic output hashes/profiles are verified; at most3 requests'}


def read_pcm(value: bytes, maximum_frames: int) -> tuple[bytes, dict]:
    if not isinstance(value, bytes) or len(value) > 3 * 1024 * 1024: raise ValueError('Bounded synthetic WAV required')
    try:
        with wave.open(io.BytesIO(value), 'rb') as audio:
            if (audio.getnchannels(), audio.getframerate(), audio.getsampwidth(), audio.getcomptype()) != (1, 24_000, 2, 'NONE') or \
                    not 0 < audio.getnframes() <= maximum_frames * FRAME_SAMPLES:
                raise ValueError('Synthetic input/output must be bounded PCM24k mono16')
            pcm = audio.readframes(audio.getnframes())
            if len(pcm) != audio.getnframes() * 2: raise ValueError('Synthetic WAV is incomplete')
            return pcm, {'sample_rate': 24_000, 'channels': 1, 'sample_width_bytes': 2,
                         'seconds': round(audio.getnframes() / 24_000, 3), 'sha256': digest(value)}
    except (wave.Error, EOFError):
        raise ValueError('Synthetic WAV is invalid') from None


def validate_fixtures(directory: Path = FIXTURES) -> tuple[dict, dict[str, bytes]]:
    directory = Path(directory)
    if directory.is_symlink(): raise ValueError('Synthetic fixture directory cannot be a symlink')
    manifest_path = directory / 'manifest.json'
    if manifest_path.is_symlink() or not manifest_path.is_file() or manifest_path.stat().st_size > 16_384:
        raise ValueError('Prepared fixed local synthetic fixtures are required')
    manifest = json.loads(manifest_path.read_text(encoding='utf8'))
    if not isinstance(manifest, dict) or manifest.get('experiment') != EXPERIMENT or \
            manifest.get('generator') != 'System.Speech local en-US' or manifest.get('culture') != 'en-US' or \
            manifest.get('microphone_used') is not False or manifest.get('provider_used') is not False or \
            not isinstance(manifest.get('voice'), str) or not 1 <= len(manifest['voice']) <= 100:
        raise ValueError('Fixture provenance must match the fixed local English generator')
    records = manifest.get('fixtures')
    if not isinstance(records, list) or len(records) != len(FIXTURE_SCRIPTS): raise ValueError('Four fixed scripts are required')
    pcm_by_id = {}; expected = {name: (rate, text) for name, rate, text in FIXTURE_SCRIPTS}
    for record in records:
        if not isinstance(record, dict) or record.get('id') not in expected or record['id'] in pcm_by_id:
            raise ValueError('Unknown or repeated synthetic fixture')
        name = record['id']; rate, text = expected[name]
        if record.get('text') != text or type(record.get('rate')) is not int or record['rate'] != rate or \
                not isinstance(record.get('sha256'), str) or not re.fullmatch(r'[a-f0-9]{64}', record['sha256']):
            raise ValueError('Synthetic script/rate/hash changed')
        path = directory / (name + '.wav')
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 3 * 1024 * 1024:
            raise ValueError('A bounded fixed fixture WAV is required')
        value = path.read_bytes()
        if digest(value) != record['sha256']: raise ValueError('Synthetic fixture hash changed')
        pcm_by_id[name], _profile = read_pcm(value, MAX_INPUT_FRAMES)
    return manifest, pcm_by_id


def prepare_fixtures() -> dict:
    if os.name != 'nt': raise ValueError('The fixed local English fixture generator requires Windows')
    process = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(FIXTURE_GENERATOR)],
        capture_output=True, timeout=45, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if process.returncode: raise RuntimeError('The local synthetic input generator failed')
    manifest, _pcm = validate_fixtures()
    return {'status': 'local_synthetic_fixtures_prepared', 'fixture_count': len(manifest['fixtures']),
            'microphone_used': False, 'provider_used': False}


def episode_input(episode: dict, fixtures: dict[str, bytes]) -> bytes:
    if episode not in EPISODES: raise ValueError('Only the three fixed independent episodes are accepted')
    pcm = bytearray(episode['frames'] * FRAME_BYTES); previous_end = 0
    for first, name in episode['clips']:
        value = fixtures[name]
        if not isinstance(value, bytes) or not 0 < len(value) <= MAX_INPUT_FRAMES * FRAME_BYTES or len(value) % 2:
            raise ValueError('Fixed synthetic clip exceeds its bound')
        offset = first * FRAME_BYTES
        if offset < previous_end or offset + len(value) > len(pcm): raise ValueError('Synthetic clips overlap or exceed the episode')
        pcm[offset:offset + len(value)] = value; previous_end = offset + len(value)
    return bytes(pcm)


def create_model():
    import personaplex_pcm_server as worker
    # Isolated single-owner experiment: reuse exact verified loading, restore the
    # module lookup immediately, and never mutate the production source file.
    with patch.dict(worker.PERSONAS, {'moss': ADAPTIVE_PROMPT}):
        return worker.NativeModel(worker.Settings('moss', pinned.VOICE, 'adaptive_synthetic_episode_epoch_1', 600))


def reset_between_episodes(model) -> None:
    # This is called only between separately named independent test episodes.
    # text_prompt_tokens stays fixed; there is no in-conversation update path.
    with model.torch.no_grad():
        model.mimi.reset_streaming(); model.other_mimi.reset_streaming(); model.lm_gen.reset_streaming()
        model.lm_gen.step_system_prompts(model.mimi); model.mimi.reset_streaming()
        model.torch.cuda.synchronize()
    model.stream_state = model.lm_gen._streaming_state
    model.cache_pointer = model.stream_state.cache.data_ptr()


def run_episode(model, episode: dict, pcm: bytes) -> dict:
    if episode not in EPISODES or not isinstance(pcm, bytes) or len(pcm) != episode['frames'] * FRAME_BYTES:
        raise ValueError('Fixed episode PCM/clock required')
    return run_native_episode(model, pcm, episode['frames'])


def run_native_episode(model, pcm: bytes, frames: int) -> dict:
    """Shared pure native-clock verifier; no initialization or prompt changes."""
    if type(frames) is not int or not 1 <= frames <= MAX_EPISODE_FRAMES or \
            not isinstance(pcm, bytes) or len(pcm) != frames * FRAME_BYTES:
        raise ValueError('Bounded complete native episode PCM/clock required')
    state = model.stream_state; pointer = state.cache.data_ptr(); start = state.offset
    initial_prompt = tuple(model.lm_gen.text_prompt_tokens)
    records, audio, caption = [], [], ''
    for index in range(frames):
        before = state.offset; began = time.perf_counter()
        frame = model.step(pcm[index * FRAME_BYTES:(index + 1) * FRAME_BYTES])
        if not isinstance(frame.pcm, bytes) or len(frame.pcm) != FRAME_BYTES or \
                type(frame.text_id) is not int or not 0 <= frame.text_id <= 32_000 or \
                not isinstance(frame.text_piece, str) or len(frame.text_piece) > 100 or \
                type(frame.rms) not in (int, float) or not 0 <= frame.rms <= 1 or \
                model.stream_state is not state or model.lm_gen._streaming_state is not state or \
                model.cache_pointer != pointer or state.cache.data_ptr() != pointer or state.offset != before + 1:
            raise ValueError('Native episode cache/frame contract changed')
        if tuple(model.lm_gen.text_prompt_tokens) != initial_prompt:
            raise ValueError('Native episode changed its initial prompt')
        caption += frame.text_piece
        if len(caption) > 8000: raise ValueError('Bounded synthetic caption exceeded')
        audio.append(frame.pcm)
        records.append({'frame': index, 'sample_index': index * FRAME_SAMPLES, 'text_id': frame.text_id,
                        'rms': round(frame.rms, 7), 'lm_offset_before': before, 'lm_offset_after': state.offset,
                        'compute_ms': round((time.perf_counter() - began) * 1000, 3)})
    return {'pcm': b''.join(audio), 'records': records, 'assistant_caption': caption.strip(),
            'lm_offset_start': start, 'lm_offset_end': state.offset, 'continuous_cache_preserved': True}


def run_worker(progress: dict) -> None:
    progress['stage'] = 'fixed_synthetic_fixtures'
    manifest, fixtures = validate_fixtures(REMOTE_FIXTURES)
    progress['stage'] = 'model_loading'; began = time.perf_counter(); model = create_model()
    loaded = time.perf_counter() - began
    original_prompt = tuple(model.lm_gen.text_prompt_tokens)
    outputs, hashes = [], {}
    for index, episode in enumerate(EPISODES):
        progress.update(stage='independent_episode', episode=index + 1)
        if index: reset_between_episodes(model)
        if tuple(model.lm_gen.text_prompt_tokens) != original_prompt: raise ValueError('Initial adaptive prompt changed')
        pcm = episode_input(episode, fixtures); result = run_episode(model, episode, pcm)
        if tuple(model.lm_gen.text_prompt_tokens) != original_prompt: raise ValueError('Adaptive episode changed its initial prompt')
        for ending, data in (('-input.wav', prior.wav_bytes(pcm)), ('-output.wav', prior.wav_bytes(result['pcm']))):
            name = episode['id'] + ending; (WORK / name).write_bytes(data); hashes[name] = digest(data)
        (WORK / (episode['id'] + '-tokens.json')).write_text(json.dumps({'caption_source': 'native_assistant_tokens_not_asr',
            'expected_forms': episode['expected_forms'], 'actual_caption': result['assistant_caption'], 'frames': result['records']}), encoding='utf8')
        metrics = [record['compute_ms'] for record in result['records']]
        outputs.append({'id': episode['id'], 'frames': episode['frames'], 'seconds': episode['frames'] * .08,
            'expected_forms': episode['expected_forms'], 'continuous_cache_preserved': True,
            'lm_offset_start': result['lm_offset_start'], 'lm_offset_end': result['lm_offset_end'],
            'audio_active_frames': sum(record['rms'] > .005 for record in result['records']),
            'mean_frame_compute_ms': round(sum(metrics) / len(metrics), 3), 'max_frame_compute_ms': max(metrics)})
    progress['stage'] = 'artifacts'
    report = {'status': 'completed', 'experiment': EXPERIMENT, 'source_revision': pinned.SOURCE_REVISION,
        'model_revision': pinned.MODEL_REVISION, 'voice': pinned.VOICE, 'initial_prompt_sha256': PROMPT_SHA256,
        'fixture_script_sha256': SCRIPT_SHA256, 'fixture_manifest': manifest, 'audio_sha256': hashes,
        'model_loads': 1, 'independent_episodes': 3, 'between_episode_resets': 2, 'within_episode_resets': 0,
        'within_episode_prompt_updates': 0, 'within_episode_forced_tokens': 0, 'clock_frames': MAX_TOTAL_FRAMES,
        'clock_seconds': MAX_TOTAL_FRAMES * .08, 'episodes': outputs, 'load_prompt_seconds': round(loaded, 3),
        'wall_clock_paced': False, 'banking_access': False, 'room_audio_used': False, 'runtime_downloads': False,
        'runtime_hf_credential': False, 'production_enabled': False, 'adaptive_behavior_verified': False,
        'human_style_verified': False, 'gpu_peak_allocated_bytes': model.torch.cuda.max_memory_allocated(0)}
    (WORK / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')


def gpu_adaptive_prompt() -> dict:
    stage = 'offline_cache'
    try:
        if os.environ.get('HF_TOKEN'): raise ValueError('Runtime HF credentials must not be mounted')
        WORK.mkdir(exist_ok=False); stage = 'adaptive_inference'
        child = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker'], cwd='/opt/personaplex',
            capture_output=True, timeout=WORKER_SECONDS, env={**os.environ, 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1'})
        if child.returncode:
            path = WORK / 'worker-failure.json'
            if path.is_file() and path.stat().st_size < 8192:
                value = json.loads(path.read_text(encoding='utf8'))
                if set(value) <= {'status', 'stage', 'failure_code', 'error_class', 'episode'} and value.get('status') == 'failed' and \
                        value.get('stage') in {'fixed_synthetic_fixtures', 'model_loading', 'independent_episode', 'artifacts'} and \
                        value.get('error_class') in {'ValueError', 'RuntimeError', 'ProtocolError', 'ModuleNotFoundError',
                            'FileNotFoundError', 'AttributeError', 'TypeError', 'OSError', 'UnclassifiedError'} and \
                        value.get('failure_code') in {'audition_failed', 'dependency_missing', 'gpu_memory_exhausted',
                            'transport_unavailable', 'client_adapter_mismatch'} and \
                        ('episode' not in value or type(value['episode']) is int and 1 <= value['episode'] <= 3):
                    return {**value, 'reason': 'The bounded adaptive synthetic qualification failed.'}
            raise RuntimeError('The bounded adaptive candidate failed')
        stage = 'artifacts'; artifacts = {}
        for name in ARTIFACT_NAMES:
            value = (WORK / name).read_bytes()
            if len(value) > 3 * 1024 * 1024: raise ValueError('Synthetic artifact exceeded its bound')
            if name.endswith('.wav'): read_pcm(value, MAX_EPISODE_FRAMES)
            else: json.loads(value)
            artifacts[name] = value
        return {'status': 'completed', 'artifacts': artifacts}
    except Exception as error:
        return {'status': 'failed', **diagnostic(error, stage), 'reason': 'The bounded adaptive synthetic qualification failed.'}


def build_app(reference: str):
    validate_fixtures()  # Refuse missing/changed audio before importing Modal.
    import modal
    if gpu_adaptive_prompt.__module__ != 'personaplex_adaptive_prompt': raise ValueError('Canonical source module identity required')
    image = modal.Image.from_id(reference).add_local_python_source(*SOURCE_MODULES, copy=True)
    for name in ('manifest.json', *(name + '.wav' for name, _rate, _text in FIXTURE_SCRIPTS)):
        image = image.add_local_file(str(FIXTURES / name), str(REMOTE_FIXTURES / name), copy=True)
    app = modal.App('elsewhere-personaplex-adaptive-qualification')
    function = app.function(image=image, gpu=pinned.GPU, cpu=(2, pinned.CPU_LIMIT), memory=(32768, pinned.MEMORY_LIMIT_GIB * 1024),
        timeout=600, startup_timeout=60, max_containers=1, min_containers=0, buffer_containers=0, retries=0,
        scaledown_window=2, single_use_containers=True, serialized=False, include_source=True)(gpu_adaptive_prompt)
    return app, function


def save_artifacts(value: dict) -> Path:
    if value.get('status') != 'completed' or set(value.get('artifacts', {})) != ARTIFACT_NAMES:
        raise ValueError('Exact adaptive synthetic artifacts required')
    destination = DIRECTORY / (time.strftime('%Y%m%d-%H%M%S') + '-' + str(time.time_ns())); destination.mkdir(parents=True, exist_ok=False)
    for name, data in value['artifacts'].items():
        if not isinstance(data, bytes) or len(data) > 3 * 1024 * 1024: raise ValueError('Bounded adaptive artifact required')
        if name.endswith('.wav'): read_pcm(data, MAX_EPISODE_FRAMES)
        else: json.loads(data)
        closed.private_bytes(destination / name, data)
    return destination


def save_failure(value: dict) -> None:
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    closed.private_bytes(DIRECTORY / ('failure-' + str(time.time_ns()) + '.json'), json.dumps(value, indent=2).encode('utf8'))


def validated_asr_outputs(directory: Path) -> list[tuple[dict, bytes]]:
    directory = Path(directory)
    if directory.is_symlink() or not directory.resolve().is_relative_to(DIRECTORY.resolve()):
        raise ValueError('ASR accepts only this ignored fixed synthetic experiment')
    path = directory / 'report.json'
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65_536: raise ValueError('Completed synthetic report required')
    report = json.loads(path.read_text(encoding='utf8'))
    required = {'status': 'completed', 'experiment': EXPERIMENT, 'source_revision': pinned.SOURCE_REVISION,
        'model_revision': pinned.MODEL_REVISION, 'voice': pinned.VOICE, 'initial_prompt_sha256': PROMPT_SHA256,
        'fixture_script_sha256': SCRIPT_SHA256, 'model_loads': 1, 'independent_episodes': 3,
        'between_episode_resets': 2, 'within_episode_resets': 0, 'within_episode_prompt_updates': 0,
        'within_episode_forced_tokens': 0, 'clock_frames': MAX_TOTAL_FRAMES, 'banking_access': False,
        'room_audio_used': False, 'runtime_downloads': False, 'runtime_hf_credential': False, 'production_enabled': False}
    if not isinstance(report, dict) or any(type(report.get(key)) is not type(value) or report.get(key) != value for key, value in required.items()):
        raise ValueError('Synthetic adaptive model/cache evidence is incomplete')
    hashes = report.get('audio_sha256'); outputs = []
    for episode in EPISODES:
        name = episode['id'] + '-output.wav'; path = directory / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 3 * 1024 * 1024:
            raise ValueError('Bounded completed synthetic output required')
        value = path.read_bytes(); pcm, _profile = read_pcm(value, MAX_EPISODE_FRAMES)
        if not isinstance(hashes, dict) or digest(value) != hashes.get(name) or len(pcm) != episode['frames'] * FRAME_BYTES:
            raise ValueError('Synthetic output hash/duration changed')
        outputs.append((episode, value))
    return outputs


def identity_observation(text: str, expected: list[str]) -> dict:
    if not isinstance(text, str) or not 0 < len(text) <= 8000: raise ValueError('Bounded synthetic ASR text required')
    forms = re.findall(r'\b(moss|orbit|spark)\b', text.lower())
    sequence = [form for index, form in enumerate(forms) if not index or form != forms[index - 1]]
    return {'expected_forms': expected, 'observed_named_forms': sequence, 'named_form_sequence_matched': sequence == expected,
            'bank_related_speech_requires_review': bool(re.search(r'\b(bank|account|dispute|refund|chargeback|balance|transaction)\b', text.lower())),
            'human_style_verified': False, 'bank_narration_enabled': False}


def verify_asr(directory: Path) -> dict:
    outputs = validated_asr_outputs(directory)  # All hashes first, before provider key access.
    receipt = Path(directory) / 'private-asr.json'
    admission = Path(directory) / 'private-asr-started.json'
    if any(path.exists() or path.is_symlink() for path in (receipt, admission)):
        raise ValueError('This experiment already has an ASR receipt; no automatic retry')
    key = closed.existing_openrouter_key(); observations = []
    closed.private_bytes(admission, json.dumps({'status': 'started', 'maximum_requests': 3}).encode('utf8'))
    try:
        for episode, audio in outputs:
            body = json.dumps({'model': closed.ASR_MODEL, 'input_audio': {'data': base64.b64encode(audio).decode('ascii'), 'format': 'wav'},
                              'response_format': 'json', 'temperature': 0, 'language': 'en'}).encode('utf8')
            request = urllib.request.Request(closed.ASR_ENDPOINT, data=body, method='POST',
                headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
            with urllib.request.build_opener(pinned.NoRedirect).open(request, timeout=45) as response:
                value = response.read(65_537)
                if response.status != 200 or len(value) > 65_536: raise ValueError('The independent synthetic ASR check failed')
            text = json.loads(value).get('text'); observation = identity_observation(text, episode['expected_forms'])
            observations.append({'id': episode['id'], 'transcript': text, **observation})
        closed.private_bytes(receipt, json.dumps({'status': 'completed', 'model': closed.ASR_MODEL, 'observations': observations}, indent=2).encode('utf8'))
    except Exception:
        closed.private_bytes(receipt, json.dumps({'status': 'failed_no_retry', 'observations': observations}).encode('utf8'))
        raise
    return {'status': 'synthetic_identity_observed', 'episodes': [{key: value for key, value in entry.items() if key != 'transcript'}
            for entry in observations], 'all_named_sequences_matched': all(entry['named_form_sequence_matched'] for entry in observations),
            'human_style_verified': False, 'production_enabled': False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__); mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--plan', action='store_true'); mode.add_argument('--prepare-fixtures', action='store_true')
    mode.add_argument('--execute', action='store_true'); mode.add_argument('--verify-asr', type=Path)
    mode.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--cache-file', type=Path, default=DEFAULT_CACHE); args = parser.parse_args(argv)
    if args.worker:
        if os.environ.get('HF_HUB_OFFLINE') != '1' or not WORK.is_dir(): parser.error('Prepared offline synthetic worker required')
        progress = {}
        try: run_worker(progress); return 0
        except Exception as error:
            safe_stage = progress.get('stage') if progress.get('stage') in {'fixed_synthetic_fixtures', 'model_loading', 'independent_episode', 'artifacts'} else 'model_loading'
            value = {'status': 'failed', **diagnostic(error, safe_stage)}
            if type(progress.get('episode')) is int and 1 <= progress['episode'] <= 3: value['episode'] = progress['episode']
            (WORK / 'worker-failure.json').write_text(json.dumps(value), encoding='utf8'); return 1
    if not args.prepare_fixtures and not args.execute and not args.verify_asr:
        print(json.dumps(plan(), indent=2)); return 0
    stage = 'local_fixtures' if args.prepare_fixtures else 'synthetic_asr' if args.verify_asr else 'fixed_synthetic_fixtures'
    try:
        if args.prepare_fixtures: print(json.dumps(prepare_fixtures())); return 0
        if args.verify_asr:
            value = verify_asr(args.verify_asr); print(json.dumps(value)); return 0 if value['all_named_sequences_matched'] else 1
        validate_fixtures(); stage = 'cached_image_reference'; reference = cache_reference(args.cache_file)
        stage = 'app_definition'; app, function = build_app(reference); stage = 'bounded_gpu_input'
        with app.run(detach=False):
            job = function.spawn()
            try: value = job.get(timeout=675)
            finally:
                try: job.cancel(terminate_containers=True)
                except Exception: pass
        if value.get('status') != 'completed': save_failure(value); print(json.dumps(value)); return 1
        directory = save_artifacts(value)
        print(json.dumps({'status': 'completed', 'output_directory': str(directory), 'adaptive_behavior_verified': False,
                          'human_style_verified': False, 'production_enabled': False, 'termination_verification_required': True})); return 0
    except Exception as error:
        value = {'status': 'failed', **diagnostic(error, stage), 'reason': 'The bounded adaptive synthetic qualification failed.'}
        save_failure(value); print(json.dumps(value)); return 1


if __name__ == '__main__':
    from importlib import import_module
    raise SystemExit(import_module('personaplex_adaptive_prompt').main())
