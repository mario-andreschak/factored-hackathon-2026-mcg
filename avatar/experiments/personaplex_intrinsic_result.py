"""Prepared-only intrinsic-paced, closed synthetic PersonaPlex qualification.

The original Moshi Appendix C algorithm preserves sampled PAD/EPAD between
words, replacing a lexical proposal with the next approved word. This is an
experimental source-pinned hook, not a stock PersonaPlex result/tool API.
--plan is inert; --execute and --verify-asr require separate explicit invocation.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import inspect
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import MethodType
import urllib.request
import wave

import personaplex_closed_result as closed
import personaplex_forced_result as prior
import personaplex_modal as pinned
from modal_diagnostic import diagnostic, GRPC_CODES, MODAL_CODES
from personaplex_browser import DEFAULT_CACHE, cache_reference
from personaplex_pcm_core import FRAME_BYTES, FRAME_SAMPLES

EXPERIMENT = 'intrinsic_paced_closed_synthetic_v4_anchor'
PUBLIC_REPLY = closed.PUBLIC_REPLY
PAD, EPAD = 3, 0
MIN_DRAIN_FRAMES, MAX_DRAIN_FRAMES = 25, 50
QUIET_FRAMES, QUIET_RMS = 8, .006
MAX_WAIT_FIRST_WORD = 64
MAX_REPLY_FRAMES = 256
MIN_TAIL_FRAMES, MAX_TAIL_FRAMES = 8, 64
POST_INPUT_FRAMES = 150
MAX_OUTPUT_DELAY = 16
MAX_CLOCK_FRAMES = MAX_DRAIN_FRAMES + MAX_WAIT_FIRST_WORD + MAX_REPLY_FRAMES + MAX_TAIL_FRAMES + MAX_OUTPUT_DELAY + POST_INPUT_FRAMES
ROOT = Path(__file__).resolve().parent.parent
DIRECTORY = ROOT / '.local' / 'personaplex-intrinsic-result'
WORK = Path('/tmp/personaplex-intrinsic-result')
ARTIFACT_NAMES = frozenset({'input.wav', 'intrinsic-result.wav', 'gated-timeline.wav', 'private-native-all.wav',
                           'private-discarded-continuation.wav', 'private-token-stream.json', 'public-caption.json', 'report.json'})
SOURCE_MODULES = ('personaplex_intrinsic_result', 'personaplex_closed_result', 'personaplex_forced_result',
                  'personaplex_pcm_core', 'personaplex_modal', 'personaplex_browser',
                  'personaplex_pcm_server', 'modal_diagnostic')
WORKER_STAGES = frozenset({'intrinsic_inference', 'model_loading', 'lexical_plan', 'sampling_hook', 'silent_drain',
                          'intrinsic_reply', 'quiet_tail', 'closed_flush', 'closed_next_public_input', 'artifacts'})
FIXED_FAILURE_REASONS = {
    'No bounded quiet acoustic boundary was observed': 'quiet_boundary_missing',
    'Acoustic boundary exceeded its fixed bound': 'acoustic_boundary_invalid',
    'The native model did not start the bounded approved reply': 'reply_start_deadline',
    'The intrinsic reply exceeded its clock budget': 'reply_clock_deadline',
    'The pinned native sampling hook contract changed': 'sampling_hook_incompatible',
    'An active intrinsic reply cannot also receive forced text': 'competing_text_forcing',
    'Invalid intrinsic text proposal': 'sampled_text_invalid',
    'Intrinsic text pacing exceeded its bound': 'sampling_clock_deadline',
    'Invalid pinned user frame': 'user_code_frame_invalid',
    'Primed model returned no native frame': 'native_frame_missing',
    'The native cache or PCM contract changed': 'native_cache_or_pcm_changed',
    'The native model frame or continuous cache changed': 'native_cache_or_frame_changed',
    'The native output clock is not continuous': 'output_clock_discontinuous',
    'Aligned output differs from the approved pacing ledger': 'aligned_text_mismatch',
    'The public output gate did not close': 'output_gate_unclosed',
    'The approved intrinsic lexical sequence did not complete exactly once': 'lexical_sequence_incomplete',
}
FAILURE_CLASSES = frozenset(MODAL_CODES) | {'GRPCError', 'InvalidError', 'RemoteError', 'AuthenticationError',
    'ExecutionError', 'FunctionTimeoutError', 'TimeoutError', 'TimeoutExpired', 'GatedRepoError',
    'HfHubHTTPError', 'RepositoryNotFoundError', 'EntryNotFoundError', 'RuntimeError', 'ModuleNotFoundError',
    'FileNotFoundError', 'CalledProcessError', 'OSError', 'ValueError', 'AttributeError', 'TypeError',
    'ConnectionError', 'CancelledError', 'UnclassifiedError'}
FAILURE_CODES = frozenset(GRPC_CODES.values()) | frozenset(MODAL_CODES.values()) | {
    'client_python_incompatible', 'model_access_denied', 'deadline_exceeded', 'gpu_memory_exhausted',
    'dependency_missing', 'image_build_failed', 'modal_auth_unavailable', 'audition_failed',
    'client_adapter_mismatch', 'operation_cancelled', 'transport_unavailable'}


def worker_failure(error: Exception, progress: dict) -> dict:
    """Project fixed internal categories, never a raw child/provider message."""
    stage = progress.get('stage')
    value = {'status': 'failed', **diagnostic(error, stage if stage in WORKER_STAGES else 'intrinsic_inference')}
    # Exact built-in messages are only matched to compile-time policy codes.
    # They are never copied, and arbitrary/custom exception arguments are ignored.
    if type(error) in (ValueError, RuntimeError) and len(error.args) == 1 and type(error.args[0]) is str:
        reason = FIXED_FAILURE_REASONS.get(error.args[0])
        if reason is not None: value['qualification_reason'] = reason
    frames = progress.get('clock_frames')
    if type(frames) is int and 0 <= frames <= MAX_CLOCK_FRAMES: value['clock_frames'] = frames
    rms = progress.get('last_frame_rms')
    if type(rms) in (int, float) and 0 <= rms <= 1: value['last_frame_rms'] = round(rms, 7)
    return value


def valid_worker_failure(value) -> bool:
    keys = {'status', 'stage', 'failure_code', 'error_class', 'qualification_reason',
            'clock_frames', 'last_frame_rms', 'grpc_status'}
    if not isinstance(value, dict) or not set(value) <= keys or value.get('status') != 'failed': return False
    for field, approved in (('stage', WORKER_STAGES), ('error_class', FAILURE_CLASSES), ('failure_code', FAILURE_CODES)):
        if type(value.get(field)) is not str or value[field] not in approved: return False
    for field, approved in (('qualification_reason', set(FIXED_FAILURE_REASONS.values())), ('grpc_status', set(GRPC_CODES))):
        if field in value and (type(value[field]) is not str or value[field] not in approved): return False
    return ('clock_frames' not in value or type(value['clock_frames']) is int and 0 <= value['clock_frames'] <= MAX_CLOCK_FRAMES) and \
        ('last_frame_rms' not in value or type(value['last_frame_rms']) in (float, int) and 0 <= value['last_frame_rms'] <= 1)


def plan() -> dict:
    value = pinned.plan()
    value.update({'experiment': EXPERIMENT, 'fixed_synthetic_reply': PUBLIC_REPLY,
        'credential': 'Existing Modal profile only on explicit execution; no runtime HF credential/access check',
        'prerequisite': 'An already built private cache with the exact source/model pins', 'public_audio_seconds': 12,
        'cache': 'Existing private pinned image plus source-only overlay; no download/build fallback',
        'algorithm': 'Anchor exactly the first approved word; then native PAD/EPAD and lexical proposals pace subsequent words with contiguous pieces',
        'first_word_anchored': True,
        'sampler_hook': 'Source-pinned process_transformer_output override before native depth audio; no global sampler patch',
        'prelude': 'No free conversation or user speech before the reply; decoded forced-silent agent-code drain',
        'drain': {'minimum_frames': MIN_DRAIN_FRAMES, 'maximum_frames': MAX_DRAIN_FRAMES,
                  'consecutive_quiet_frames': QUIET_FRAMES, 'rms_below': QUIET_RMS},
        'bounds': {'wait_first_word_frames': MAX_WAIT_FIRST_WORD, 'reply_frames': MAX_REPLY_FRAMES,
                   'tail_frames': MAX_TAIL_FRAMES, 'total_frames': MAX_CLOCK_FRAMES,
                   'total_audio_seconds': round(MAX_CLOCK_FRAMES * .08, 3), 'worker_seconds': 360},
        'alignment': 'Codebook output delay is verified; acoustic drain/tail quietness is measured separately',
        'gate': 'Closed before first approved lexical output, permanently closed after bounded quiet tail',
        'after_reply': 'Twelve seconds of fixed public fixture, same cache, all audio/captions discarded',
        'banking_access': False, 'runtime_downloads': False, 'production_enabled': False,
        'pronunciation_verified': False, 'asr': 'Explicit separate request on completed hashed synthetic audio only'})
    return value


def pcm_profile(value: bytes) -> dict:
    if len(value) > 3 * 1024 * 1024: raise ValueError('Oversized bounded experiment audio')
    with wave.open(io.BytesIO(value), 'rb') as audio:
        seconds = audio.getnframes() / audio.getframerate()
        if (audio.getnchannels(), audio.getframerate(), audio.getsampwidth()) != (1, 24_000, 2) or \
                not 0 < seconds <= MAX_CLOCK_FRAMES * .08 + .08:
            raise ValueError('Unexpected bounded PCM24k mono profile')
        return {'seconds': round(seconds, 3), 'sample_rate': 24_000, 'channels': 1,
                'sample_width_bytes': 2, 'bytes': len(value)}


def approved_words(encode_word) -> tuple[tuple[int, ...], ...]:
    words = tuple(tuple(encode_word(word)) for word in PUBLIC_REPLY.split())
    if not words or any(not word or any(type(token) is not int or not 4 <= token < 32_000 for token in word) for word in words):
        raise ValueError('The approved synthetic lexical sequence is invalid')
    if sum(map(len, words)) > MAX_REPLY_FRAMES:
        raise ValueError('The approved lexical sequence exceeds its bound')
    return words


class IntrinsicPacer:
    """Pure token policy. It never accepts caller result strings or new words."""

    def __init__(self, words: tuple[tuple[int, ...], ...], *, anchor_first_word: bool = False):
        if not words or any(not word or any(type(token) is not int or not 4 <= token < 32_000 for token in word) for word in words):
            raise ValueError('Invalid fixed lexical plan')
        if type(anchor_first_word) is not bool: raise ValueError('Invalid first-word anchor policy')
        self.words = words
        self.anchor_first_word = anchor_first_word
        self.word = self.piece = 0
        self.enabled = False
        self.decisions = []

    @property
    def complete(self): return self.word == len(self.words)

    def choose(self, proposal: int) -> int:
        if not self.enabled or type(proposal) is not int or not 0 <= proposal <= 32_000:
            raise ValueError('Invalid intrinsic text proposal')
        if len(self.decisions) >= MAX_WAIT_FIRST_WORD + MAX_REPLY_FRAMES + MAX_TAIL_FRAMES + MAX_OUTPUT_DELAY:
            raise ValueError('Intrinsic text pacing exceeded its bound')
        advance = False
        if self.complete:
            selected = proposal if proposal in (PAD, EPAD) else PAD
        elif self.piece or self.anchor_first_word and self.word == 0 or proposal not in (PAD, EPAD):
            selected = self.words[self.word][self.piece]
            advance = True
        else:
            selected = proposal
        self.decisions.append({'proposal': proposal, 'selected': selected,
                               'word': self.word, 'piece': self.piece,
                               'sampled_padding_preserved': not advance and proposal in (PAD, EPAD),
                               'first_word_anchored': advance and self.anchor_first_word and self.word == 0,
                               'unapproved_lexical_suppressed': self.complete and proposal not in (PAD, EPAD)})
        if advance:
            self.piece += 1
            if self.piece == len(self.words[self.word]): self.word += 1; self.piece = 0
        return selected


def install_intrinsic_hook(lm_gen, pacer: IntrinsicPacer, *, sample_text=None, tensor_api=None):
    """Use a fixed per-instance hook; keep the stock audio/cache method intact.

    The native text sampler runs exactly once. A one-hot logit tensor and
    temporary text-only greedy mode let the original method consume that chosen
    token without a second RNG draw. Audio temperature/top-k/sampling and graph
    state are never changed. Restore the text temperature even on failure.
    """
    original = lm_gen.process_transformer_output
    names = tuple(inspect.signature(original).parameters)
    if names != ('transformer_out', 'text_logits', 'provided_', 'target_', 'model_input_position', 'target_position') or \
            lm_gen.report_loss or lm_gen.return_logits or lm_gen.lm_model.delays[0] != 0:
        raise ValueError('The pinned native sampling hook contract changed')
    if sample_text is None:
        from moshi.utils.sampling import sample_token
        sample_text = sample_token
    if tensor_api is None:
        import torch
        tensor_api = torch

    def intrinsic(self, transformer_out, text_logits, provided_, target_, model_input_position, target_position):
        if not pacer.enabled:
            return original(transformer_out, text_logits, provided_, target_, model_input_position, target_position)
        if bool(provided_[:, 0, 0].any().item()):
            raise ValueError('An active intrinsic reply cannot also receive forced text')
        proposal = sample_text(text_logits.float(), self.use_sampling, self.temp_text, self.top_k_text)
        selected = pacer.choose(int(proposal.item()))
        chosen = tensor_api.full_like(text_logits, float('-inf'))
        chosen[:, :, :, selected] = 0
        temperature = self.temp_text
        self.temp_text = 0
        try:
            return original(transformer_out, chosen, provided_, target_, model_input_position, target_position)
        finally:
            self.temp_text = temperature
    lm_gen.process_transformer_output = MethodType(intrinsic, lm_gen)


class AcousticBoundary:
    def __init__(self, minimum: int, maximum: int):
        self.minimum, self.maximum = minimum, maximum
        self.frames = self.quiet = 0

    def add(self, rms: float) -> bool:
        if not isinstance(rms, (int, float)) or not 0 <= rms <= 1 or self.frames >= self.maximum:
            raise ValueError('Acoustic boundary exceeded its fixed bound')
        self.frames += 1
        self.quiet = self.quiet + 1 if rms < QUIET_RMS else 0
        if self.frames >= self.minimum and self.quiet >= QUIET_FRAMES: return True
        if self.frames == self.maximum: raise ValueError('No bounded quiet acoustic boundary was observed')
        return False


class ClosedGate:
    """Approval ledger uses aligned output tokens; it cannot reopen."""

    def __init__(self, first_input: int, delay: int):
        if type(delay) is not int or not 0 <= delay <= MAX_OUTPUT_DELAY:
            raise ValueError('Unsupported pinned output delay')
        self.delay, self.first_input = delay, first_input
        self.end_input = None
        self.closed = False
        self.last = -1

    def finish(self, end_input: int):
        if self.end_input is not None or type(end_input) is not int or end_input <= self.first_input:
            raise ValueError('The closed gate cannot be rescheduled')
        self.end_input = end_input

    def consider(self, frame: int, text_id: int, ledger: list[int]) -> bool:
        if frame != self.last + 1:
            self.closed = True; raise ValueError('The native output clock is not continuous')
        self.last = frame
        source = frame - self.delay
        if self.closed or source < self.first_input: return False
        if self.end_input is not None and source >= self.end_input:
            self.closed = True; return False
        if not 0 <= source < len(ledger) or text_id != ledger[source]:
            self.closed = True; raise ValueError('Aligned output differs from the approved pacing ledger')
        return True


def run_clock(pacer: IntrinsicPacer, delay: int, continuation: bytes, step_model, *, progress=None) -> dict:
    """Bounded continuous-clock policy, testable without Torch/Modal/audio APIs."""
    if type(delay) is not int or not 1 <= delay <= MAX_OUTPUT_DELAY or \
            not isinstance(continuation, bytes) or len(continuation) != POST_INPUT_FRAMES * FRAME_BYTES:
        raise ValueError('Invalid pinned delayed clock or public continuation')
    ledger, records, native, gated, reply, discarded, inputs = [], [], [], [], [], [], []
    zero = bytes(FRAME_BYTES); gate = None
    def step(raw: bytes, phase: str, *, silent_agent=False, padding=False):
        if len(records) >= MAX_CLOCK_FRAMES: raise ValueError('The qualification exceeded its total clock')
        if progress is not None: progress.update(stage=phase, clock_frames=len(records))
        result = dict(step_model(raw, silent_agent=silent_agent, padding=padding))
        audio = result.pop('pcm'); current = result['selected_input_text_id']; output_id = result['output_text_id']
        if not isinstance(audio, bytes) or len(audio) != FRAME_BYTES or result.get('continuous_cache_preserved') is not True or \
                type(current) is not int or not 0 <= current <= 32_000 or type(output_id) is not int:
            raise ValueError('The native model frame or continuous cache changed')
        ledger.append(current); index = len(records)
        allowed = gate.consider(index, output_id, ledger) if gate is not None else False
        native.append(audio); inputs.append(raw); gated.append(audio if allowed else zero)
        if allowed: reply.append(audio)
        elif gate is not None and gate.closed: discarded.append(audio)
        records.append({**result, 'frame': index, 'phase': phase, 'output_source_frame': index - delay,
                        'public_output': allowed})
        if progress is not None: progress.update(clock_frames=len(records), last_frame_rms=result['rms'])
        return result['rms']
    drain = AcousticBoundary(MIN_DRAIN_FRAMES, MAX_DRAIN_FRAMES)
    while not drain.add(step(zero, 'silent_drain', silent_agent=True)): pass
    pacer.enabled = True; first_lexical = last_lexical = tail_started = None
    tail = None; active_started = len(records)
    while True:
        rms = step(zero, 'quiet_tail' if tail is not None else 'intrinsic_reply'); index = len(records) - 1
        if first_lexical is None and ledger[-1] >= 4:
            first_lexical = index; gate = ClosedGate(first_lexical, delay); gate.last = index
        if first_lexical is None and len(records) - active_started >= MAX_WAIT_FIRST_WORD:
            raise ValueError('The native model did not start the bounded approved reply')
        if first_lexical is not None and index - first_lexical >= MAX_REPLY_FRAMES:
            raise ValueError('The intrinsic reply exceeded its clock budget')
        if pacer.complete:
            if last_lexical is None: last_lexical = index
            # Quiet frames before the last delayed lexical output cannot prove
            # its acoustic completion. Measure only on subsequent output frames.
            if index > last_lexical + delay:
                if tail is None:
                    tail = AcousticBoundary(MIN_TAIL_FRAMES, MAX_TAIL_FRAMES); tail_started = index
                if tail.add(rms): gate.finish(len(records)); break
    pacer.enabled = False
    for _ in range(delay + 1): step(zero, 'closed_flush', padding=True)
    if gate is None or not gate.closed: raise ValueError('The public output gate did not close')
    for index in range(POST_INPUT_FRAMES):
        step(continuation[index * FRAME_BYTES:(index + 1) * FRAME_BYTES], 'closed_next_public_input')
    lexical = [decision['selected'] for decision in pacer.decisions if decision['selected'] >= 4]
    expected = [token for word in pacer.words for token in word]
    if lexical != expected or not pacer.complete or not gate.closed or not reply:
        raise ValueError('The approved intrinsic lexical sequence did not complete exactly once')
    return {'ledger': ledger, 'records': records, 'native': native, 'gated': gated, 'reply': reply,
            'discarded': discarded, 'inputs': inputs, 'gate': gate, 'drain': drain, 'tail': tail,
            'first_lexical': first_lexical, 'last_lexical': last_lexical, 'tail_started': tail_started}


def run_worker(progress=None) -> None:
    from personaplex_pcm_server import NativeModel, Settings
    if progress is None: progress = {}
    progress['stage'] = 'model_loading'
    loading = time.perf_counter()
    model = NativeModel(Settings('moss', pinned.VOICE, 'synthetic_intrinsic_result_epoch_3', pinned.FUNCTION_SECONDS))
    loaded_seconds = time.perf_counter() - loading
    np, torch, lm_gen = model.np, model.torch, model.lm_gen
    progress['stage'] = 'lexical_plan'
    words = approved_words(model.tokenizer.encode)
    # Silent input has no response trigger: v3's 64-frame deadline observed only
    # PAD/EPAD. Anchor exactly the first approved word, then let the model pace
    # every subsequent word with its native padding. This is a v4 experiment.
    pacer = IntrinsicPacer(words, anchor_first_word=True)
    progress['stage'] = 'sampling_hook'
    install_intrinsic_hook(lm_gen, pacer)
    delay = lm_gen.max_delay
    if not 0 <= delay <= MAX_OUTPUT_DELAY: raise ValueError('The pinned output delay changed')
    state, cache_pointer = model.stream_state, model.cache_pointer
    offset_start = state.offset
    def step_model(raw: bytes, *, silent_agent=False, padding=False):
        started = time.perf_counter(); before = state.offset
        chunk = torch.from_numpy(np.frombuffer(raw, dtype='<i2').astype(np.float32) / 32768.0).to('cuda')[None, None]
        with torch.no_grad():
            codes = model.mimi.encode(chunk); _ = model.other_mimi.encode(chunk)
            if tuple(codes.shape) != (1, 8, 1): raise ValueError('Invalid pinned user frame')
            options = {}
            if silent_agent:
                options = {'moshi_tokens': lm_gen._encode_zero_frame(),
                           'text_token': torch.tensor([PAD], dtype=torch.long, device='cuda')}
            elif padding:
                options = {'text_token': torch.tensor([PAD], dtype=torch.long, device='cuda')}
            tokens = lm_gen.step(codes, **options)
            if tokens is None: raise ValueError('Primed model returned no native frame')
            # The current (not delayed) choice is the ledger's input text step.
            current = int(state.cache[0, 0, before % state.cache.shape[2]].item())
            pcm = model.decode(model.mimi, model.other_mimi, lm_gen, tokens)
            torch.cuda.synchronize()
        if pcm.shape != (FRAME_SAMPLES,) or not np.isfinite(pcm).all() or \
                lm_gen._streaming_state is not state or state.cache.data_ptr() != cache_pointer or state.offset != before + 1:
            raise ValueError('The native cache or PCM contract changed')
        rms = float(np.sqrt(np.mean(pcm * pcm)))
        audio = np.clip(np.rint(pcm * 32768), -32768, 32767).astype('<i2').tobytes()
        return {'pcm': audio, 'selected_input_text_id': current, 'output_text_id': int(tokens[0, 0, 0].item()),
            'rms': round(rms, 7), 'continuous_cache_preserved': True,
            'lm_offset_before': before, 'lm_offset_after': state.offset,
            'frame_total_ms': round((time.perf_counter() - started) * 1000, 3)}
    with wave.open(str(WORK / 'public.wav'), 'rb') as audio:
        if (audio.getnchannels(), audio.getframerate(), audio.getsampwidth()) != (1, 24_000, 2):
            raise ValueError('The fixed public continuation audio is invalid')
        continuation = audio.readframes(POST_INPUT_FRAMES * FRAME_SAMPLES)
    result = run_clock(pacer, delay, continuation, step_model, progress=progress)
    records, native, gated, reply = (result[key] for key in ('records', 'native', 'gated', 'reply'))
    discarded, inputs, gate, drain, tail, first_lexical = (result[key] for key in
        ('discarded', 'inputs', 'gate', 'drain', 'tail', 'first_lexical'))
    progress['stage'] = 'artifacts'
    waves = {'input.wav': b''.join(inputs), 'intrinsic-result.wav': b''.join(reply),
        'gated-timeline.wav': b''.join(gated), 'private-native-all.wav': b''.join(native),
        'private-discarded-continuation.wav': b''.join(discarded)}
    for name, pcm in waves.items(): (WORK / name).write_bytes(prior.wav_bytes(pcm))
    (WORK / 'private-token-stream.json').write_text(json.dumps({'decisions': pacer.decisions, 'frames': records}), encoding='utf8')
    (WORK / 'public-caption.json').write_text(json.dumps({'text': PUBLIC_REPLY, 'source': 'fixed_synthetic_reply', 'is_asr_proof': False}), encoding='utf8')
    timings = [record['frame_total_ms'] for record in records]
    report = {'status': 'completed', 'experiment': EXPERIMENT, 'source_revision': pinned.SOURCE_REVISION,
        'model_revision': pinned.MODEL_REVISION, 'synthetic_public_reply': PUBLIC_REPLY,
        'intrinsic_padding_policy': True, 'first_word_anchored': True, 'approved_lexical_order_exact': True,
        'approved_words': len(words), 'approved_lexical_pieces': sum(map(len, words)),
        'sampled_padding_frames_preserved': sum(decision['sampled_padding_preserved'] for decision in pacer.decisions),
        'post_lexical_proposals_suppressed': sum(decision['unapproved_lexical_suppressed'] for decision in pacer.decisions),
        'model_output_delay_frames': delay, 'drain_frames': drain.frames, 'drain_quiet_frames': drain.quiet,
        'quiet_rms_threshold': QUIET_RMS, 'tail_frames': tail.frames, 'tail_quiet_frames': tail.quiet,
        'last_approved_input_frame': result['last_lexical'], 'tail_first_output_frame': result['tail_started'],
        'first_approved_input_frame': first_lexical, 'public_end_input_frame_exclusive': gate.end_input,
        'public_audio_frames': len(reply), 'public_audio_sha256': hashlib.sha256((WORK / 'intrinsic-result.wav').read_bytes()).hexdigest(),
        'gate_permanently_closed': True, 'post_reply_public_audio_frames': 0, 'post_reply_public_caption_tokens': 0,
        'continuous_lm_cache_preserved': True, 'lm_offset_start': offset_start, 'lm_offset_end': state.offset,
        'load_prompt_seconds': round(loaded_seconds, 3), 'clock_frames': len(records), 'clock_seconds': round(len(records) * .08, 3),
        'wall_clock_paced': False, 'frame_timings_ms': {'mean': round(float(np.mean(timings)), 3),
            'p95': round(float(np.percentile(timings, 95)), 3), 'maximum': round(max(timings), 3)},
        'banking_access': False, 'runtime_downloads': False, 'runtime_hf_credential': False,
        'production_enabled': False, 'pronunciation_verified': False,
        'gpu': {'name': torch.cuda.get_device_name(0), 'peak_allocated_bytes': torch.cuda.max_memory_allocated(0)}}
    (WORK / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')


def gpu_intrinsic_result() -> dict:
    stage = 'offline_cache'
    try:
        if os.environ.get('HF_TOKEN'): raise ValueError('Runtime HF credentials must not be mounted')
        WORK.mkdir(exist_ok=False)
        stage = 'public_audio'
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i',
            '/opt/personaplex/assets/test/input_assistant.wav', '-t', '12', '-ar', '24000', '-ac', '1', '-c:a', 'pcm_s16le',
            str(WORK / 'public.wav')], check=True, capture_output=True, timeout=20)
        stage = 'intrinsic_inference'
        child = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker'], cwd='/opt/personaplex',
            capture_output=True, timeout=360, env={**os.environ, 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1'})
        if child.returncode:
            receipt = WORK / 'worker-failure.json'
            if receipt.is_file() and receipt.stat().st_size <= 8192:
                value = json.loads(receipt.read_text(encoding='utf8'))
                # Only the worker's already-sanitized fixed schema may leave its
                # process. A malformed receipt cannot project arbitrary content.
                if valid_worker_failure(value):
                    return {**value, 'child_exit_code': child.returncode,
                            'reason': 'The intrinsic synthetic qualification failed.'}
            raise RuntimeError('The bounded intrinsic candidate failed')
        stage = 'artifacts'
        artifacts = {}
        for name in ARTIFACT_NAMES:
            value = (WORK / name).read_bytes()
            if len(value) > 3 * 1024 * 1024: raise ValueError('Oversized bounded synthetic artifact')
            if name.endswith('.wav'): pcm_profile(value)
            else: json.loads(value)
            artifacts[name] = value
        return {'status': 'completed', 'artifacts': artifacts}
    except Exception as error:
        return {'status': 'failed', **diagnostic(error, stage), 'reason': 'The intrinsic synthetic qualification failed.'}


def build_app(reference: str):
    import modal
    if gpu_intrinsic_result.__module__ != 'personaplex_intrinsic_result': raise ValueError('Canonical source module identity is required')
    image = modal.Image.from_id(reference).add_local_python_source(*SOURCE_MODULES, copy=True)
    app = modal.App('elsewhere-personaplex-intrinsic-qualification')
    function = app.function(image=image, gpu=pinned.GPU, cpu=(2, pinned.CPU_LIMIT), memory=(32768, pinned.MEMORY_LIMIT_GIB * 1024),
        timeout=pinned.FUNCTION_SECONDS, startup_timeout=pinned.STARTUP_SECONDS, max_containers=1, min_containers=0,
        buffer_containers=0, scaledown_window=2, retries=0, single_use_containers=True,
        serialized=False, include_source=True)(gpu_intrinsic_result)
    return app, function


def save_artifacts(result: dict) -> Path:
    if result.get('status') != 'completed' or set(result.get('artifacts', {})) != ARTIFACT_NAMES:
        raise ValueError('Unexpected intrinsic experiment artifacts')
    destination = DIRECTORY / (time.strftime('%Y%m%d-%H%M%S') + '-' + str(time.time_ns()))
    destination.mkdir(parents=True, exist_ok=False)
    for name, value in result['artifacts'].items():
        if not isinstance(value, bytes) or len(value) > 3 * 1024 * 1024: raise ValueError('Oversized synthetic output')
        if name.endswith('.wav'): pcm_profile(value)
        else: json.loads(value)
        closed.private_bytes(destination / name, value)
    return destination


def save_failure(result: dict) -> Path:
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    destination = DIRECTORY / ('failure-' + str(time.time_ns()) + '.json')
    closed.private_bytes(destination, json.dumps(result, indent=2).encode('utf8'))
    return destination


def validated_asr_audio(directory: Path) -> bytes:
    directory = Path(directory)
    if directory.is_symlink() or not directory.resolve().is_relative_to(DIRECTORY.resolve()):
        raise ValueError('ASR accepts only this ignored synthetic experiment')
    report_path, audio_path = directory / 'report.json', directory / 'intrinsic-result.wav'
    if any(path.is_symlink() or not path.is_file() or path.stat().st_size > 3 * 1024 * 1024 for path in (report_path, audio_path)):
        raise ValueError('Completed bounded synthetic output is required')
    report = json.loads(report_path.read_text(encoding='utf8'))
    required = {'status': 'completed', 'experiment': EXPERIMENT, 'synthetic_public_reply': PUBLIC_REPLY,
        'source_revision': pinned.SOURCE_REVISION, 'model_revision': pinned.MODEL_REVISION,
        'intrinsic_padding_policy': True, 'first_word_anchored': True, 'approved_lexical_order_exact': True, 'gate_permanently_closed': True,
        'continuous_lm_cache_preserved': True, 'post_reply_public_audio_frames': 0,
        'post_reply_public_caption_tokens': 0, 'banking_access': False, 'production_enabled': False}
    if not isinstance(report, dict) or any(type(report.get(key)) is not type(value) or report.get(key) != value for key, value in required.items()):
        raise ValueError('Synthetic gate/model evidence is incomplete')
    audio = audio_path.read_bytes()
    if hashlib.sha256(audio).hexdigest() != report.get('public_audio_sha256'): raise ValueError('The approved audio hash changed')
    frames = report.get('public_audio_frames'); profile = pcm_profile(audio)
    if type(frames) is not int or not 1 <= frames <= MAX_REPLY_FRAMES + MAX_TAIL_FRAMES or abs(profile['seconds'] - frames * .08) > .001:
        raise ValueError('The approved synthetic duration changed')
    return audio


def verify_asr(directory: Path) -> dict:
    audio = validated_asr_audio(directory)
    receipt = Path(directory) / 'private-asr.json'
    if receipt.exists() or receipt.is_symlink(): raise ValueError('This synthetic output already has an ASR receipt')
    key = closed.existing_openrouter_key()
    body = json.dumps({'model': closed.ASR_MODEL, 'input_audio': {'data': base64.b64encode(audio).decode('ascii'), 'format': 'wav'},
                      'response_format': 'json', 'temperature': 0, 'language': 'en'}).encode('utf8')
    request = urllib.request.Request(closed.ASR_ENDPOINT, data=body, method='POST',
                                    headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    with urllib.request.build_opener(pinned.NoRedirect).open(request, timeout=45) as response:
        value = response.read(65_537)
        if response.status != 200 or len(value) > 65_536: raise ValueError('The independent synthetic ASR check failed')
    text = json.loads(value).get('text'); verdict = closed.asr_verdict(text)
    closed.private_bytes(receipt, json.dumps({'model': closed.ASR_MODEL, 'transcript': text, **verdict}, indent=2).encode('utf8'))
    return verdict


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--plan', action='store_true'); mode.add_argument('--execute', action='store_true')
    mode.add_argument('--verify-asr', type=Path); mode.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--cache-file', type=Path, default=DEFAULT_CACHE)
    options = parser.parse_args(argv)
    if options.worker:
        if os.environ.get('HF_HUB_OFFLINE') != '1' or not (WORK / 'public.wav').is_file():
            parser.error('Worker requires prepared offline model and fixed public fixture')
        progress = {}
        try: run_worker(progress); return 0
        except Exception as error:
            (WORK / 'worker-failure.json').write_text(json.dumps(worker_failure(error, progress)), encoding='utf8')
            return 1
    if not options.execute and not options.verify_asr: print(json.dumps(plan(), indent=2)); return 0
    stage = 'synthetic_asr' if options.verify_asr else 'cached_image_reference'
    try:
        if options.verify_asr:
            verdict = verify_asr(options.verify_asr); print(json.dumps(verdict))
            return 0 if verdict['exact_propositions_without_extra_text'] else 1
        reference = cache_reference(options.cache_file)
        stage = 'app_definition'; app, function = build_app(reference)
        stage = 'bounded_gpu_input'
        with app.run(detach=False):
            job = function.spawn()
            try: result = job.get(timeout=pinned.FUNCTION_SECONDS + pinned.STARTUP_SECONDS + 15)
            finally:
                try: job.cancel(terminate_containers=True)
                except Exception: pass
        if result.get('status') != 'completed':
            save_failure(result); print(json.dumps(result)); return 1
        destination = save_artifacts(result)
        print(json.dumps({'status': 'completed', 'output_directory': str(destination), 'persistent_service': False,
                          'pronunciation_verified': False, 'production_enabled': False, 'termination_verification_required': True}))
        return 0
    except Exception as error:
        failure = {'status': 'failed', **diagnostic(error, stage), 'reason': 'The intrinsic synthetic qualification failed.'}
        save_failure(failure); print(json.dumps(failure)); return 1


if __name__ == '__main__':
    from importlib import import_module
    raise SystemExit(import_module('personaplex_intrinsic_result').main())
