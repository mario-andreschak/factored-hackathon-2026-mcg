"""Stdlib-only intrinsic text policy, hook, gate and credential scope tests."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import personaplex_intrinsic_result as experiment


class Scalar:
    def __init__(self, value): self.value = value
    def item(self): return self.value
    def any(self): return self
    def float(self): return self
    def __getitem__(self, _index): return self
    def __setitem__(self, index, _value): self.selected = index[-1]


def generator(*, failing=False):
    class Model:
        temp_text = .7; temp = .8; use_sampling = True; top_k = 250; top_k_text = 25
        report_loss = False; return_logits = False
        lm_model = SimpleNamespace(delays=[0, 0, 1])
        def process_transformer_output(self, transformer_out, text_logits, provided_, target_, model_input_position, target_position):
            self.observed = (self.temp_text, self.temp, self.use_sampling, self.top_k)
            if failing: raise RuntimeError('fixture')
            return getattr(text_logits, 'selected', 'stock')
    return Model()


def receipt(audio):
    return {'status': 'completed', 'experiment': experiment.EXPERIMENT,
        'synthetic_public_reply': experiment.PUBLIC_REPLY, 'source_revision': experiment.pinned.SOURCE_REVISION,
        'model_revision': experiment.pinned.MODEL_REVISION, 'intrinsic_padding_policy': True, 'first_word_anchored': True,
        'approved_lexical_order_exact': True, 'gate_permanently_closed': True,
        'continuous_lm_cache_preserved': True, 'post_reply_public_audio_frames': 0,
        'post_reply_public_caption_tokens': 0, 'banking_access': False, 'production_enabled': False,
        'public_audio_sha256': hashlib.sha256(audio).hexdigest(), 'public_audio_frames': 2}


class FakeClock:
    """One continuous model ledger with real delayed text/audio framing."""
    def __init__(self, pacer, delay=1, proposals=(3, 0, 900, 3, 3, 0, 900), *,
                 noisy_drain=False, noisy_tail=False, bad_cache=False, wrong_output=False):
        self.pacer, self.delay = pacer, delay
        self.proposals, self.proposal = proposals, 0
        self.ledger, self.calls = [], []
        self.noisy_drain, self.noisy_tail = noisy_drain, noisy_tail
        self.bad_cache, self.wrong_output = bad_cache, wrong_output

    def __call__(self, raw, *, silent_agent=False, padding=False):
        index = len(self.ledger)
        self.calls.append((raw, silent_agent, padding, self.pacer.enabled))
        if silent_agent or padding:
            selected = experiment.PAD
        elif self.pacer.enabled:
            selected = self.pacer.choose(self.proposals[min(self.proposal, len(self.proposals) - 1)])
            self.proposal += 1
        else:
            selected = 900  # Unapproved free conversation after the permanent close.
        self.ledger.append(selected)
        source = index - self.delay
        output = self.ledger[source] if source >= 0 else experiment.PAD
        if self.wrong_output and self.pacer.enabled and output >= 4: output = 901
        audible = output >= 4 or (silent_agent and self.noisy_drain) or \
            (self.pacer.enabled and self.pacer.complete and self.noisy_tail)
        return {'pcm': b'\x02\x01' * experiment.FRAME_SAMPLES if audible else bytes(experiment.FRAME_BYTES),
                'selected_input_text_id': selected, 'output_text_id': output,
                'rms': .05 if audible else 0, 'continuous_cache_preserved': not self.bad_cache,
                'lm_offset_before': index, 'lm_offset_after': index + 1}


class IntrinsicTests(unittest.TestCase):
    def test_default_plan_reads_no_cache_keys_model_sdk_or_network(self):
        with patch.object(experiment, 'cache_reference', side_effect=AssertionError('cache')), \
             patch.object(experiment.closed, 'existing_openrouter_key', side_effect=AssertionError('key')), \
             patch.object(experiment, 'build_app', side_effect=AssertionError('cloud')), \
             patch.dict('sys.modules', {'modal': None, 'torch': None}), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(experiment.main([]), 0)
        plan = json.loads(output.getvalue())
        self.assertEqual(plan['status'], 'prepared_not_dispatched')
        self.assertEqual(plan['timeout_seconds'], 600); self.assertEqual(plan['bounds']['worker_seconds'], 360)
        self.assertFalse(plan['production_enabled']); self.assertFalse(plan['pronunciation_verified'])
        self.assertEqual(plan['retries'], 0)

    def test_pacer_preserves_model_padding_and_contiguous_exact_word_pieces(self):
        pacer = experiment.IntrinsicPacer(((101, 102), (201,)))
        pacer.enabled = True
        proposals = [3, 0, 500, 3, 3, 0, 900, 800, 0]
        selected = [pacer.choose(proposal) for proposal in proposals]
        self.assertEqual(selected, [3, 0, 101, 102, 3, 0, 201, 3, 0])
        self.assertTrue(pacer.complete)
        self.assertEqual([token for token in selected if token >= 4], [101, 102, 201])
        self.assertTrue(pacer.decisions[-2]['unapproved_lexical_suppressed'])
        self.assertTrue(pacer.decisions[4]['sampled_padding_preserved'])
        self.assertFalse(pacer.decisions[3]['sampled_padding_preserved'])

    def test_anchor_starts_exact_first_word_then_preserves_every_native_padding_decision(self):
        pacer = experiment.IntrinsicPacer(((101, 102), (201,), (301,)), anchor_first_word=True)
        pacer.enabled = True
        proposals = [3, 0, 3, 0, 900, 3, 0, 900, 900]
        self.assertEqual([pacer.choose(proposal) for proposal in proposals], [101, 102, 3, 0, 201, 3, 0, 301, 3])
        self.assertEqual([row['first_word_anchored'] for row in pacer.decisions], [True, True, False, False, False, False, False, False, False])
        self.assertTrue(pacer.complete)
        self.assertTrue(pacer.decisions[-1]['unapproved_lexical_suppressed'])
        with self.assertRaises(ValueError): experiment.IntrinsicPacer(((101,),), anchor_first_word=1)

    def test_anchored_clock_cannot_hide_a_stalled_later_word_or_lose_the_first_delayed_output(self):
        continuation = bytes(experiment.POST_INPUT_FRAMES * experiment.FRAME_BYTES)
        for delay in (1, 2, experiment.MAX_OUTPUT_DELAY):
            pacer = experiment.IntrinsicPacer(((101, 102), (201,)), anchor_first_word=True)
            model = FakeClock(pacer, delay, proposals=(3, 0, 3, 0, 900))
            result = experiment.run_clock(pacer, delay, continuation, model)
            self.assertEqual(result['first_lexical'], experiment.MIN_DRAIN_FRAMES)
            public = [row for row in result['records'] if row['public_output']]
            self.assertEqual(public[0]['output_text_id'], 101)
            self.assertTrue(result['gate'].closed)
        pacer = experiment.IntrinsicPacer(((101,), (201,)), anchor_first_word=True)
        with self.assertRaisesRegex(ValueError, 'reply exceeded its clock budget'):
            experiment.run_clock(pacer, 1, continuation, FakeClock(pacer, proposals=(3,)))

    def test_policy_rejects_bad_tokens_empty_words_unbounded_clock_and_disabled_use(self):
        for words in ((), ((),), ((3,),), ((True,),), ((32000,),)):
            with self.assertRaises(ValueError): experiment.IntrinsicPacer(words)
        pacer = experiment.IntrinsicPacer(((101,),))
        with self.assertRaises(ValueError): pacer.choose(3)
        pacer.enabled = True
        for bad in (-1, 32001, True, '3'):
            with self.assertRaises(ValueError): pacer.choose(bad)
        for _ in range(experiment.MAX_WAIT_FIRST_WORD + experiment.MAX_REPLY_FRAMES + experiment.MAX_TAIL_FRAMES + experiment.MAX_OUTPUT_DELAY):
            pacer.choose(3)
        with self.assertRaises(ValueError): pacer.choose(3)

    def test_hook_keeps_native_audio_sampler_and_restores_text_temperature(self):
        model = generator(); pacer = experiment.IntrinsicPacer(((101,),)); pacer.enabled = True
        sample = Mock(return_value=Scalar(900))
        tensors = SimpleNamespace(full_like=lambda *_args: Scalar(0))
        experiment.install_intrinsic_hook(model, pacer, sample_text=sample, tensor_api=tensors)
        self.assertEqual(model.process_transformer_output(None, Scalar(0), Scalar(False), None, 0, 1), 101)
        sample.assert_called_once(); self.assertEqual(sample.call_args.args[1:], (True, .7, 25))
        self.assertEqual(model.observed, (0, .8, True, 250)); self.assertEqual(model.temp_text, .7)

    def test_hook_bypasses_startup_and_rejects_competing_forcing_or_api_changes(self):
        model = generator(); pacer = experiment.IntrinsicPacer(((101,),)); sample = Mock(return_value=Scalar(900))
        experiment.install_intrinsic_hook(model, pacer, sample_text=sample, tensor_api=SimpleNamespace(full_like=lambda *_args: Scalar(0)))
        self.assertEqual(model.process_transformer_output(None, Scalar(0), Scalar(True), None, 0, 1), 'stock')
        sample.assert_not_called(); pacer.enabled = True
        with self.assertRaises(ValueError): model.process_transformer_output(None, Scalar(0), Scalar(True), None, 0, 1)
        model = generator(); model.return_logits = True
        with self.assertRaises(ValueError): experiment.install_intrinsic_hook(model, pacer)

    def test_failed_stock_hook_restores_temperature_without_audio_parameter_changes(self):
        model = generator(failing=True); pacer = experiment.IntrinsicPacer(((101,),)); pacer.enabled = True
        experiment.install_intrinsic_hook(model, pacer, sample_text=lambda *_args: Scalar(1000),
                                          tensor_api=SimpleNamespace(full_like=lambda *_args: Scalar(0)))
        with self.assertRaises(RuntimeError): model.process_transformer_output(None, Scalar(0), Scalar(False), None, 0, 1)
        self.assertEqual(model.temp_text, .7); self.assertEqual(model.temp, .8); self.assertTrue(model.use_sampling)

    def test_acoustic_drain_requires_consecutive_quiet_frames_and_fails_at_bound(self):
        boundary = experiment.AcousticBoundary(10, 20)
        for _ in range(7): self.assertFalse(boundary.add(.001))
        self.assertFalse(boundary.add(.1))
        for _ in range(7): self.assertFalse(boundary.add(.001))
        self.assertTrue(boundary.add(.001))
        boundary = experiment.AcousticBoundary(10, 10)
        for _ in range(9): self.assertFalse(boundary.add(.2))
        with self.assertRaises(ValueError): boundary.add(.2)
        for rms in (float('nan'), float('inf'), -1, 2):
            with self.assertRaises(ValueError): experiment.AcousticBoundary(10, 20).add(rms)

    def test_dynamic_gate_aligns_approved_clock_and_cannot_reopen(self):
        ledger = [3, 3, 101, 3, 0, 201, 3, 3, 900, 900]
        gate = experiment.ClosedGate(2, 1); gate.finish(8)
        allowed = [gate.consider(index, ledger[index - 1] if index else 0, ledger) for index in range(10)]
        self.assertEqual(allowed, [False, False, False, True, True, True, True, True, True, False])
        self.assertTrue(gate.closed)
        self.assertFalse(gate.consider(10, 101, ledger))
        with self.assertRaises(ValueError): gate.finish(11)

    def test_gate_token_mismatch_and_clock_gaps_fail_closed(self):
        gate = experiment.ClosedGate(1, 1)
        gate.consider(0, 3, [3, 101]); gate.consider(1, 3, [3, 101])
        with self.assertRaises(ValueError): gate.consider(2, 900, [3, 101])
        self.assertTrue(gate.closed)
        gate = experiment.ClosedGate(1, 1)
        with self.assertRaises(ValueError): gate.consider(1, 3, [3, 101])
        self.assertTrue(gate.closed)

    def test_complete_native_clock_drains_preserves_padding_and_drops_all_later_conversation(self):
        for delay in (1, 2, experiment.MAX_OUTPUT_DELAY):
            with self.subTest(delay=delay):
                pacer = experiment.IntrinsicPacer(((101, 102), (201,)))
                model = FakeClock(pacer, delay)
                fixture = b'\x04\x03' * experiment.FRAME_SAMPLES * experiment.POST_INPUT_FRAMES
                result = experiment.run_clock(pacer, delay, fixture, model)
                self.assertEqual(result['drain'].frames, experiment.MIN_DRAIN_FRAMES)
                self.assertEqual([decision['selected'] for decision in pacer.decisions[:7]],
                                 [3, 0, 101, 102, 3, 0, 201])
                self.assertEqual(result['first_lexical'], experiment.MIN_DRAIN_FRAMES + 2)
                public = [record for record in result['records'] if record['public_output']]
                self.assertEqual(public[0]['frame'], result['first_lexical'] + delay)
                self.assertEqual(public[-1]['output_source_frame'], result['gate'].end_input - 1)
                self.assertGreaterEqual(result['tail'].quiet, experiment.QUIET_FRAMES)
                self.assertGreater(result['tail_started'], result['last_lexical'] + delay)
                self.assertEqual(result['tail_started'], result['last_lexical'] + delay + 1)
                self.assertTrue(result['gate'].closed); self.assertFalse(pacer.enabled)
                post = [record for record in result['records'] if record['phase'] == 'closed_next_public_input']
                self.assertEqual(len(post), experiment.POST_INPUT_FRAMES)
                self.assertTrue(all(not record['public_output'] for record in post))
                self.assertTrue(any(any(frame) for frame in result['discarded']))
                self.assertTrue(all(not any(frame) for frame in result['gated'][-experiment.POST_INPUT_FRAMES:]))
                self.assertEqual(b''.join(result['inputs'][-experiment.POST_INPUT_FRAMES:]), fixture)
                self.assertTrue(all(not any(raw) for raw in result['inputs'][:-experiment.POST_INPUT_FRAMES]))
                self.assertEqual([record['lm_offset_after'] for record in result['records']],
                                 list(range(1, len(result['records']) + 1)))
                self.assertTrue(all(silent and not enabled for _raw, silent, _padding, enabled
                                    in model.calls[:experiment.MIN_DRAIN_FRAMES]))

    def test_whole_clock_fails_closed_if_drain_or_model_lexical_start_never_arrives(self):
        continuation = bytes(experiment.POST_INPUT_FRAMES * experiment.FRAME_BYTES)
        pacer = experiment.IntrinsicPacer(((101,),)); model = FakeClock(pacer, noisy_drain=True)
        with self.assertRaisesRegex(ValueError, 'quiet acoustic boundary'):
            experiment.run_clock(pacer, 1, continuation, model)
        self.assertEqual(len(model.calls), experiment.MAX_DRAIN_FRAMES)
        self.assertFalse(pacer.enabled); self.assertFalse(pacer.decisions)
        pacer = experiment.IntrinsicPacer(((101,),)); model = FakeClock(pacer, proposals=(3, 0))
        with self.assertRaisesRegex(ValueError, 'did not start'):
            experiment.run_clock(pacer, 1, continuation, model)
        self.assertEqual(len(model.calls), experiment.MIN_DRAIN_FRAMES + experiment.MAX_WAIT_FIRST_WORD)
        self.assertTrue(all(not any(raw) for raw, *_flags in model.calls))

    def test_whole_clock_rejects_nonquiet_tail_changed_cache_or_unapproved_output(self):
        continuation = bytes(experiment.POST_INPUT_FRAMES * experiment.FRAME_BYTES)
        for mode, expected in (('noisy_tail', 'quiet acoustic boundary'),
                               ('bad_cache', 'continuous cache'), ('wrong_output', 'approved pacing ledger')):
            with self.subTest(mode=mode):
                pacer = experiment.IntrinsicPacer(((101,),))
                model = FakeClock(pacer, **{mode: True})
                with self.assertRaisesRegex(ValueError, expected):
                    experiment.run_clock(pacer, 1, continuation, model)
                self.assertTrue(all(not any(raw) for raw, *_flags in model.calls))

    def test_reply_that_never_advances_to_its_second_word_stops_at_clock_budget(self):
        pacer = experiment.IntrinsicPacer(((101,), (201,)))
        model = FakeClock(pacer, proposals=(900, 3))
        with self.assertRaisesRegex(ValueError, 'reply exceeded its clock budget'):
            experiment.run_clock(pacer, 1, bytes(experiment.POST_INPUT_FRAMES * experiment.FRAME_BYTES), model)
        self.assertEqual(len(model.calls), experiment.MIN_DRAIN_FRAMES + experiment.MAX_REPLY_FRAMES + 1)
        self.assertEqual([choice['selected'] for choice in pacer.decisions if choice['selected'] >= 4], [101])
        self.assertTrue(all(not any(raw) for raw, *_flags in model.calls))

    def test_source_only_app_layers_over_existing_image_and_preserves_one_input_bounds(self):
        image = Mock(); image.add_local_python_source.return_value = image
        app = Mock(); app.function.return_value = lambda function: function
        sdk = SimpleNamespace(Image=SimpleNamespace(from_id=Mock(return_value=image)), App=Mock(return_value=app))
        with patch.dict('sys.modules', {'modal': sdk}), \
                patch.object(experiment.pinned, 'existing_token', side_effect=AssertionError('HF read')), \
                patch.object(experiment.pinned, 'build_image', side_effect=AssertionError('heavy image chain')):
            returned_app, function = experiment.build_app('im-existing-private-cache')
        self.assertIs(returned_app, app); self.assertIs(function, experiment.gpu_intrinsic_result)
        sdk.Image.from_id.assert_called_once_with('im-existing-private-cache')
        image.add_local_python_source.assert_called_once_with(*experiment.SOURCE_MODULES, copy=True)
        parameters = app.function.call_args.kwargs
        self.assertEqual(parameters['gpu'], 'A100-80GB'); self.assertEqual(parameters['timeout'], 600)
        self.assertEqual(parameters['startup_timeout'], 60); self.assertEqual(parameters['retries'], 0)
        self.assertEqual(parameters['max_containers'], 1); self.assertEqual(parameters['min_containers'], 0)
        self.assertEqual(parameters['buffer_containers'], 0); self.assertTrue(parameters['single_use_containers'])
        self.assertFalse(parameters['serialized']); self.assertTrue(parameters['include_source'])
        self.assertNotIn('secrets', parameters)

    def test_source_overlay_imports_from_unrelated_directory_without_checkout(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as unrelated:
            for module in experiment.SOURCE_MODULES:
                shutil.copyfile(Path(experiment.__file__).with_name(module + '.py'), Path(directory) / (module + '.py'))
            process = subprocess.run([sys.executable, str(Path(directory) / 'personaplex_intrinsic_result.py'), '--plan'],
                cwd=unrelated, capture_output=True, text=True, timeout=5, env={k: v for k, v in os.environ.items() if k != 'PYTHONPATH'})
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout)['experiment'], experiment.EXPERIMENT)

    def test_bounded_input_is_cancelled_after_client_failure_without_hf_access(self):
        job = Mock(); job.get.side_effect = TimeoutError('private-sentinel')
        function = Mock(); function.spawn.return_value = job
        app = Mock(); app.run.return_value = contextlib.nullcontext()
        with patch.object(experiment, 'cache_reference', return_value='im-existing'), \
                patch.object(experiment, 'build_app', return_value=(app, function)), \
                patch.object(experiment.pinned, 'existing_token', side_effect=AssertionError('HF read')), \
                patch.object(experiment, 'save_failure') as save_failure, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(experiment.main(['--execute']), 1)
        function.spawn.assert_called_once(); job.get.assert_called_once_with(timeout=675)
        job.cancel.assert_called_once_with(terminate_containers=True); app.run.assert_called_once_with(detach=False)
        self.assertNotIn('private', output.getvalue())
        save_failure.assert_called_once()

    def test_worker_failure_projects_fixed_policy_and_phase_without_exception_text(self):
        progress = {'stage': 'silent_drain', 'clock_frames': 50, 'last_frame_rms': .03123456789}
        value = experiment.worker_failure(ValueError('No bounded quiet acoustic boundary was observed'), progress)
        self.assertEqual(value['qualification_reason'], 'quiet_boundary_missing')
        self.assertEqual(value['stage'], 'silent_drain'); self.assertEqual(value['clock_frames'], 50)
        self.assertEqual(value['last_frame_rms'], .0312346); self.assertTrue(experiment.valid_worker_failure(value))
        private = experiment.worker_failure(RuntimeError('private-key-and-provider-url-sentinel'), progress)
        self.assertNotIn('qualification_reason', private)
        self.assertNotIn('sentinel', json.dumps(private)); self.assertTrue(experiment.valid_worker_failure(private))
        progress['stage'] = 'private-stage-sentinel'; progress['last_frame_rms'] = float('nan')
        value = experiment.worker_failure(ValueError('private'), progress)
        self.assertEqual(value['stage'], 'intrinsic_inference'); self.assertNotIn('last_frame_rms', value)

    def test_malformed_worker_receipt_cannot_project_unknown_strings_or_numbers(self):
        value = experiment.worker_failure(RuntimeError('private'), {'stage': 'sampling_hook'})
        for key, bad in (('stage', 'private-path'), ('error_class', 'private-key'), ('failure_code', 'private-url'),
                         ('qualification_reason', 'private-text'), ('grpc_status', 'private-token'),
                         ('clock_frames', True), ('clock_frames', 601), ('last_frame_rms', float('inf'))):
            with self.subTest(key=key, bad=bad): self.assertFalse(experiment.valid_worker_failure({**value, key: bad}))
        self.assertFalse(experiment.valid_worker_failure({**value, 'stderr': 'private'}))
        self.assertFalse(experiment.valid_worker_failure({**value, 'stage': []}))
        self.assertFalse(experiment.valid_worker_failure({**value, 'qualification_reason': {}}))

    def test_worker_command_persists_only_safe_failure_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory); (work / 'public.wav').touch()
            def fail(progress):
                progress.update(stage='intrinsic_reply', clock_frames=89, last_frame_rms=0)
                raise ValueError('The native model did not start the bounded approved reply')
            with patch.object(experiment, 'WORK', work), patch.object(experiment, 'run_worker', side_effect=fail), \
                    patch.dict(os.environ, {'HF_HUB_OFFLINE': '1'}):
                self.assertEqual(experiment.main(['--worker']), 1)
            value = json.loads((work / 'worker-failure.json').read_text())
        self.assertEqual(value['qualification_reason'], 'reply_start_deadline')
        self.assertEqual(value['clock_frames'], 89); self.assertTrue(experiment.valid_worker_failure(value))

    def test_outer_function_returns_retained_worker_phase_instead_of_generic_runtime_error(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory) / 'new'
            value = experiment.worker_failure(ValueError('The intrinsic reply exceeded its clock budget'),
                                              {'stage': 'intrinsic_reply', 'clock_frames': 281})
            def run(command, **_options):
                if command[0] != 'ffmpeg':
                    (work / 'worker-failure.json').write_text(json.dumps(value))
                    return SimpleNamespace(returncode=1, stderr=b'private-key-sentinel', stdout=b'private-url-sentinel')
                return SimpleNamespace(returncode=0)
            with patch.object(experiment, 'WORK', work), patch.object(experiment.subprocess, 'run', side_effect=run), \
                    patch.dict(os.environ, {}, clear=True):
                result = experiment.gpu_intrinsic_result()
        self.assertEqual(result['qualification_reason'], 'reply_clock_deadline')
        self.assertEqual(result['stage'], 'intrinsic_reply'); self.assertEqual(result['child_exit_code'], 1)
        self.assertNotIn('private', json.dumps(result))

    def test_asr_accepts_only_completed_hashed_ignored_synthetic_output_before_key_read(self):
        audio = experiment.prior.wav_bytes(bytes(experiment.FRAME_BYTES * 2))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); result = root / 'fixed'; result.mkdir()
            (result / 'intrinsic-result.wav').write_bytes(audio)
            (result / 'report.json').write_text(json.dumps(receipt(audio)))
            with patch.object(experiment, 'DIRECTORY', root):
                self.assertEqual(experiment.validated_asr_audio(result), audio)
                (result / 'intrinsic-result.wav').write_bytes(audio + b'tampered')
                with patch.object(experiment.closed, 'existing_openrouter_key', side_effect=AssertionError('credential read')):
                    with self.assertRaises(ValueError): experiment.verify_asr(result)
                with self.assertRaises(ValueError): experiment.validated_asr_audio(root.parent)

    def test_independent_asr_verdict_still_rejects_missing_words_and_extra_promises(self):
        self.assertTrue(experiment.closed.asr_verdict(experiment.PUBLIC_REPLY)['exact_propositions_without_extra_text'])
        for text in ('doing, the payment want is $42.17. There is no app dispute. No action was taken.',
                     experiment.PUBLIC_REPLY + ' No action will be taken.'):
            self.assertFalse(experiment.closed.asr_verdict(text)['exact_propositions_without_extra_text'])


if __name__ == '__main__': unittest.main()
