"""Three independent fixed production-role qualifications; default is inert.

One weights load, exact production prompts/NATM1, 3x24s fixed synthetic input.
--execute and --verify-asr are separate explicit paid modes with no retry.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import time
import urllib.request

import personaplex_adaptive_prompt as common
import personaplex_pcm_server as worker
from modal_diagnostic import diagnostic

pinned, closed, prior = common.pinned, common.closed, common.prior
FRAME_BYTES, FRAME_SAMPLES = common.FRAME_BYTES, common.FRAME_SAMPLES
EXPERIMENT = 'fixed_three_roles_native_v1'
EPISODES = (
    {'avatar': 'moss', 'fixture': 'anxious', 'frames': 300},
    {'avatar': 'orbit', 'fixture': 'planning', 'frames': 300},
    {'avatar': 'spark', 'fixture': 'energetic', 'frames': 300},
)
ROLES = tuple(episode['avatar'] for episode in EPISODES)
PROMPT_SHA256 = {role: common.digest(worker.PERSONAS[role].encode('utf8')) for role in ROLES}
FRAMES = 300
TOTAL_FRAMES = 900
WORKER_SECONDS = 360
DIRECTORY = common.ROOT / '.local' / 'personaplex-fixed-roles'
REMOTE_FIXTURES = PurePosixPath('/opt/personaplex-fixed-role-fixtures')
WORK = Path('/tmp/personaplex-fixed-roles')
SOURCE_MODULES = ('personaplex_fixed_roles', *common.SOURCE_MODULES)
ARTIFACT_NAMES = frozenset({'report.json'} | {role + ending for role in ROLES
                         for ending in ('-input.wav', '-output.wav', '-tokens.json')})
WORKER_STAGES = frozenset({'fixed_synthetic_fixtures', 'model_loading', 'initial_role_prompt', 'independent_episode', 'artifacts'})


def plan() -> dict:
    return {**pinned.plan(), 'experiment': EXPERIMENT, 'voice': pinned.VOICE, 'episodes': EPISODES,
        'production_prompt_sha256': PROMPT_SHA256, 'production_prompts_unchanged': True,
        'model_loads': 1, 'independent_conversations': 3, 'clock_frames': TOTAL_FRAMES, 'clock_seconds': 72,
        'public_audio_seconds': 72,
        'worker_seconds': WORKER_SECONDS, 'function_seconds': 600, 'client_seconds': 675,
        'initialization': 'Exact production NativeModel Moss constructor; stock voice/prompt replay before each later independent role',
        'within_conversation': 'No prompt mutation, forced tokens, cache reset or re-prime',
        'input': 'Existing hashed local en-US synthetic anxious/planning/energetic clips; no microphone',
        'cache': 'Existing private pinned image plus source/fixture COPY only; no HF token/download/rebuild fallback',
        'credential': 'Existing Modal profile only on explicit execution; no runtime HF token or provider key',
        'prerequisite': 'Already built private image with the exact model/source pins; no new gated-model access step',
        'banking_access': False, 'production_enabled': False, 'browser_provider_changed': False,
        'fixed_role_behavior_verified': False, 'human_style_verified': False,
        'asr': 'Separate explicit hash-validated three-request batch; exclusive receipt prevents repeats'}


def create_model():
    # Production constructor is used unchanged. It loads and primes Moss/NATM1.
    return worker.NativeModel(worker.Settings('moss', pinned.VOICE, 'fixed_role_synthetic_epoch_1', 600))


def initial_prompt_tokens(tokenizer, role: str, wrapper) -> list[int]:
    """Use the same production string, wrapper and tokenizer before an episode."""
    if role not in ROLES:
        raise ValueError('Only the three unchanged production roles are accepted')
    tokens = tokenizer.encode(wrapper(worker.PERSONAS[role]))
    if not isinstance(tokens, list) or not 0 < len(tokens) <= 512 or \
            any(type(value) is not int or not 0 <= value <= 32_000 for value in tokens):
        raise ValueError('Bounded stock initial role tokens required')
    return tokens


def prime_next_episode(model, role: str, wrapper=None) -> None:
    if role not in ('orbit', 'spark'):
        raise ValueError('Only the later independent conversations may be primed here')
    if wrapper is None:
        from moshi.offline import wrap_with_system_tags
        wrapper = wrap_with_system_tags
    # This is an episode boundary, never an update to a live conversation.
    model.lm_gen.text_prompt_tokens = initial_prompt_tokens(model.tokenizer, role, wrapper)
    common.reset_between_episodes(model)


def episode_input(episode: dict, fixtures: dict[str, bytes]) -> bytes:
    if episode not in EPISODES:
        raise ValueError('Only the three fixed production-role episodes are accepted')
    clip = fixtures[episode['fixture']]
    if not isinstance(clip, bytes) or not 0 < len(clip) <= common.MAX_INPUT_FRAMES * FRAME_BYTES or len(clip) % 2:
        raise ValueError('Bounded fixed synthetic clip required')
    return clip + bytes(FRAMES * FRAME_BYTES - len(clip))


def run_worker(progress: dict) -> None:
    progress['stage'] = 'fixed_synthetic_fixtures'
    manifest, fixtures = common.validate_fixtures(REMOTE_FIXTURES)
    progress['stage'] = 'model_loading'; began = time.perf_counter(); model = create_model()
    loaded = time.perf_counter() - began
    hashes, outputs = {}, []
    for index, episode in enumerate(EPISODES):
        role = episode['avatar']; progress.update(stage='initial_role_prompt', episode=index + 1)
        if index:
            prime_next_episode(model, role)
        prompt = tuple(model.lm_gen.text_prompt_tokens)
        if not prompt:
            raise ValueError('Production role was not primed before conversation')
        progress['stage'] = 'independent_episode'
        pcm = episode_input(episode, fixtures)
        result = common.run_native_episode(model, pcm, FRAMES)
        if tuple(model.lm_gen.text_prompt_tokens) != prompt:
            raise ValueError('Fixed production role prompt changed during conversation')
        for ending, data in (('-input.wav', prior.wav_bytes(pcm)), ('-output.wav', prior.wav_bytes(result['pcm']))):
            name = role + ending; (WORK / name).write_bytes(data); hashes[name] = common.digest(data)
        (WORK / (role + '-tokens.json')).write_text(json.dumps({
            'caption_source': 'native_assistant_tokens_not_asr', 'expected_named_form': role,
            'actual_caption': result['assistant_caption'], 'frames': result['records']}), encoding='utf8')
        metrics = [record['compute_ms'] for record in result['records']]
        outputs.append({'avatar': role, 'fixture': episode['fixture'], 'frames': FRAMES, 'seconds': 24,
            'production_prompt_sha256': PROMPT_SHA256[role],
            'initial_prompt_tokens_sha256': common.digest(json.dumps(prompt, separators=(',', ':')).encode('utf8')),
            'continuous_cache_preserved': True, 'lm_offset_start': result['lm_offset_start'], 'lm_offset_end': result['lm_offset_end'],
            'audio_active_frames': sum(record['rms'] > .005 for record in result['records']),
            'mean_frame_compute_ms': round(sum(metrics) / len(metrics), 3), 'max_frame_compute_ms': max(metrics)})
    progress['stage'] = 'artifacts'
    report = {'status': 'completed', 'experiment': EXPERIMENT,
        'source_revision': pinned.SOURCE_REVISION, 'model_revision': pinned.MODEL_REVISION, 'voice': pinned.VOICE,
        'production_prompt_sha256': PROMPT_SHA256, 'production_prompts_unchanged': True,
        'fixture_script_sha256': common.SCRIPT_SHA256, 'fixture_manifest': manifest, 'audio_sha256': hashes,
        'model_loads': 1, 'independent_conversations': 3, 'between_conversation_resets': 2,
        'within_conversation_resets': 0, 'within_conversation_prompt_updates': 0, 'within_conversation_forced_tokens': 0,
        'clock_frames': TOTAL_FRAMES, 'clock_seconds': 72, 'episodes': outputs,
        'load_prompt_seconds': round(loaded, 3), 'wall_clock_paced': False,
        'banking_access': False, 'room_audio_used': False, 'runtime_downloads': False, 'runtime_hf_credential': False,
        'production_enabled': False, 'fixed_role_behavior_verified': False, 'human_style_verified': False,
        'gpu_peak_allocated_bytes': model.torch.cuda.max_memory_allocated(0)}
    (WORK / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')


def safe_worker_failure(value) -> dict:
    if not isinstance(value, dict) or value.get('status') != 'failed' or \
            set(value) - {'status', 'stage', 'failure_code', 'error_class', 'episode'} or value.get('stage') not in WORKER_STAGES or \
            value.get('error_class') not in {'ValueError', 'RuntimeError', 'ProtocolError', 'ModuleNotFoundError',
                'FileNotFoundError', 'AttributeError', 'TypeError', 'OSError', 'UnclassifiedError'} or \
            value.get('failure_code') not in {'audition_failed', 'dependency_missing', 'gpu_memory_exhausted',
                'transport_unavailable', 'client_adapter_mismatch'} or \
            ('episode' in value and (type(value['episode']) is not int or not 1 <= value['episode'] <= 3)):
        raise ValueError('Invalid bounded worker failure receipt')
    return value


def gpu_fixed_roles() -> dict:
    stage = 'offline_cache'
    try:
        if os.environ.get('HF_TOKEN'):
            raise ValueError('Runtime HF credentials must not be mounted')
        WORK.mkdir(exist_ok=False); stage = 'fixed_role_inference'
        child = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker'], cwd='/opt/personaplex',
            capture_output=True, timeout=WORKER_SECONDS, env={**os.environ, 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1'})
        if child.returncode:
            path = WORK / 'worker-failure.json'
            if path.is_file() and path.stat().st_size < 8192:
                value = safe_worker_failure(json.loads(path.read_text(encoding='utf8')))
                return {**value, 'reason': 'The bounded fixed-role qualification failed.'}
            raise RuntimeError('The bounded fixed-role worker failed')
        stage = 'artifacts'; artifacts = {}
        for name in ARTIFACT_NAMES:
            value = (WORK / name).read_bytes()
            if len(value) > 3 * 1024 * 1024:
                raise ValueError('Synthetic artifact exceeded its bound')
            if name.endswith('.wav'): common.read_pcm(value, FRAMES)
            else: json.loads(value)
            artifacts[name] = value
        return {'status': 'completed', 'artifacts': artifacts}
    except Exception as error:
        return {'status': 'failed', **diagnostic(error, stage), 'reason': 'The bounded fixed-role qualification failed.'}


def build_app(reference: str):
    common.validate_fixtures()  # Existing fixed provenance/hashes before SDK access.
    import modal
    if gpu_fixed_roles.__module__ != 'personaplex_fixed_roles':
        raise ValueError('Canonical source module identity required')
    image = modal.Image.from_id(reference).add_local_python_source(*SOURCE_MODULES, copy=True)
    # The original four-file manifest is preserved exactly. The fourth clip is
    # provenance-only and never selected as input by this three-episode runner.
    for name in ('manifest.json', *(name + '.wav' for name, _rate, _text in common.FIXTURE_SCRIPTS)):
        image = image.add_local_file(str(common.FIXTURES / name), str(REMOTE_FIXTURES / name), copy=True)
    app = modal.App('elsewhere-personaplex-fixed-roles-qualification')
    function = app.function(image=image, gpu=pinned.GPU, cpu=(2, pinned.CPU_LIMIT),
        memory=(32768, pinned.MEMORY_LIMIT_GIB * 1024), timeout=600, startup_timeout=60,
        max_containers=1, min_containers=0, buffer_containers=0, retries=0, scaledown_window=2,
        single_use_containers=True, serialized=False, include_source=True)(gpu_fixed_roles)
    return app, function


def save_artifacts(value: dict) -> Path:
    if value.get('status') != 'completed' or set(value.get('artifacts', {})) != ARTIFACT_NAMES:
        raise ValueError('Exact fixed-role synthetic artifacts required')
    destination = DIRECTORY / (time.strftime('%Y%m%d-%H%M%S') + '-' + str(time.time_ns()))
    destination.mkdir(parents=True, exist_ok=False)
    for name, data in value['artifacts'].items():
        if not isinstance(data, bytes) or len(data) > 3 * 1024 * 1024:
            raise ValueError('Bounded fixed-role artifact required')
        if name.endswith('.wav'): common.read_pcm(data, FRAMES)
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
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65_536:
        raise ValueError('Completed fixed-role synthetic report required')
    report = json.loads(path.read_text(encoding='utf8'))
    required = {'status': 'completed', 'experiment': EXPERIMENT, 'source_revision': pinned.SOURCE_REVISION,
        'model_revision': pinned.MODEL_REVISION, 'voice': pinned.VOICE, 'production_prompt_sha256': PROMPT_SHA256,
        'production_prompts_unchanged': True, 'fixture_script_sha256': common.SCRIPT_SHA256,
        'model_loads': 1, 'independent_conversations': 3, 'between_conversation_resets': 2,
        'within_conversation_resets': 0, 'within_conversation_prompt_updates': 0, 'within_conversation_forced_tokens': 0,
        'clock_frames': TOTAL_FRAMES, 'banking_access': False, 'room_audio_used': False,
        'runtime_downloads': False, 'runtime_hf_credential': False, 'production_enabled': False}
    if not isinstance(report, dict) or any(type(report.get(key)) is not type(value) or report.get(key) != value
                                         for key, value in required.items()):
        raise ValueError('Fixed-role model/prompt/cache evidence is incomplete')
    episodes = report.get('episodes')
    if not isinstance(episodes, list) or len(episodes) != 3:
        raise ValueError('Three completed fixed-role conversations required')
    hashes = report.get('audio_sha256'); outputs = []
    for expected, actual in zip(EPISODES, episodes):
        role = expected['avatar']
        if not isinstance(actual, dict) or actual.get('avatar') != role or actual.get('fixture') != expected['fixture'] or \
                type(actual.get('frames')) is not int or actual['frames'] != FRAMES or \
                actual.get('production_prompt_sha256') != PROMPT_SHA256[role] or actual.get('continuous_cache_preserved') is not True or \
                type(actual.get('lm_offset_start')) is not int or type(actual.get('lm_offset_end')) is not int or \
                actual['lm_offset_end'] - actual['lm_offset_start'] != FRAMES:
            raise ValueError('Completed per-role clock/prompt evidence is incomplete')
        path = directory / (role + '-output.wav')
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 3 * 1024 * 1024:
            raise ValueError('Bounded completed fixed-role WAV required')
        value = path.read_bytes(); pcm, _profile = common.read_pcm(value, FRAMES)
        if not isinstance(hashes, dict) or common.digest(value) != hashes.get(path.name) or len(pcm) != FRAMES * FRAME_BYTES:
            raise ValueError('Fixed-role output hash/duration changed')
        outputs.append((expected, value))
    return outputs


def verify_asr(directory: Path) -> dict:
    outputs = validated_asr_outputs(directory)  # Every hash/pin/clock before key access.
    receipt = Path(directory) / 'private-asr.json'; admission = Path(directory) / 'private-asr-started.json'
    if any(path.exists() or path.is_symlink() for path in (receipt, admission)):
        raise ValueError('This fixed experiment already admitted ASR; no automatic retry')
    key = closed.existing_openrouter_key(); observations = []
    closed.private_bytes(admission, json.dumps({'status': 'started', 'maximum_requests': 3}).encode('utf8'))
    try:
        for episode, audio in outputs:
            body = json.dumps({'model': closed.ASR_MODEL,
                'input_audio': {'data': base64.b64encode(audio).decode('ascii'), 'format': 'wav'},
                'response_format': 'json', 'temperature': 0, 'language': 'en'}).encode('utf8')
            request = urllib.request.Request(closed.ASR_ENDPOINT, data=body, method='POST',
                headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
            with urllib.request.build_opener(pinned.NoRedirect).open(request, timeout=45) as response:
                value = response.read(65_537)
                if response.status != 200 or len(value) > 65_536:
                    raise ValueError('The separate fixed-role synthetic ASR check failed')
            text = json.loads(value).get('text')
            observations.append({'avatar': episode['avatar'], 'transcript': text,
                **common.identity_observation(text, [episode['avatar']])})
        closed.private_bytes(receipt, json.dumps({'status': 'completed', 'model': closed.ASR_MODEL,
            'observations': observations}, indent=2).encode('utf8'))
    except Exception:
        closed.private_bytes(receipt, json.dumps({'status': 'failed_no_retry', 'observations': observations}).encode('utf8'))
        raise
    return {'status': 'fixed_role_names_observed', 'roles': [{key: value for key, value in entry.items() if key != 'transcript'}
            for entry in observations], 'all_named_sequences_matched': all(entry['named_form_sequence_matched'] for entry in observations),
        'human_style_verified': False, 'production_enabled': False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__); mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--plan', action='store_true'); mode.add_argument('--execute', action='store_true')
    mode.add_argument('--verify-asr', type=Path); mode.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--cache-file', type=Path, default=common.DEFAULT_CACHE); args = parser.parse_args(argv)
    if args.worker:
        if os.environ.get('HF_HUB_OFFLINE') != '1' or not WORK.is_dir():
            parser.error('Prepared offline synthetic worker required')
        progress = {}
        try: run_worker(progress); return 0
        except Exception as error:
            stage = progress.get('stage') if progress.get('stage') in WORKER_STAGES else 'model_loading'
            value = {'status': 'failed', **diagnostic(error, stage)}
            if type(progress.get('episode')) is int and 1 <= progress['episode'] <= 3:
                value['episode'] = progress['episode']
            (WORK / 'worker-failure.json').write_text(json.dumps(value), encoding='utf8'); return 1
    if not args.execute and not args.verify_asr:
        print(json.dumps(plan(), indent=2)); return 0
    stage = 'synthetic_asr' if args.verify_asr else 'fixed_synthetic_fixtures'
    try:
        if args.verify_asr:
            value = verify_asr(args.verify_asr); print(json.dumps(value)); return 0 if value['all_named_sequences_matched'] else 1
        common.validate_fixtures(); stage = 'cached_image_reference'; reference = common.cache_reference(args.cache_file)
        stage = 'app_definition'; app, function = build_app(reference); stage = 'bounded_gpu_input'
        with app.run(detach=False):
            job = function.spawn()
            try: value = job.get(timeout=675)
            finally:
                try: job.cancel(terminate_containers=True)
                except Exception: pass
        if value.get('status') != 'completed': save_failure(value); print(json.dumps(value)); return 1
        directory = save_artifacts(value)
        print(json.dumps({'status': 'completed', 'output_directory': str(directory), 'fixed_role_behavior_verified': False,
            'human_style_verified': False, 'production_enabled': False, 'termination_verification_required': True})); return 0
    except Exception as error:
        value = {'status': 'failed', **diagnostic(error, stage), 'reason': 'The bounded fixed-role qualification failed.'}
        save_failure(value); print(json.dumps(value)); return 1


if __name__ == '__main__':
    from importlib import import_module
    raise SystemExit(import_module('personaplex_fixed_roles').main())
