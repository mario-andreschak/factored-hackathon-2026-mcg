"""Local-only adaptive prompt, fixed input, native clock and ASR scope tests."""
import contextlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import personaplex_adaptive_prompt as experiment
import personaplex_pcm_server as worker


def fixtures_at(directory):
    manifest = {'experiment': experiment.EXPERIMENT, 'generator': 'System.Speech local en-US', 'culture': 'en-US',
                'voice': 'Local English Test Voice', 'microphone_used': False, 'provider_used': False, 'fixtures': []}
    pcm = b'\x02\x01' * experiment.FRAME_SAMPLES * 5
    for name, rate, text in experiment.FIXTURE_SCRIPTS:
        value = experiment.prior.wav_bytes(pcm)
        (directory / (name + '.wav')).write_bytes(value)
        manifest['fixtures'].append({'id': name, 'rate': rate, 'text': text, 'sha256': experiment.digest(value)})
    (directory / 'manifest.json').write_text(json.dumps(manifest))
    return manifest


class FakeModel:
    def __init__(self, failure=None):
        self.failure = failure; self.calls = 0; self.inputs = []
        self.stream_state = SimpleNamespace(offset=5, cache=SimpleNamespace(data_ptr=lambda: 12345))
        self.cache_pointer = 12345
        self.lm_gen = SimpleNamespace(_streaming_state=self.stream_state, text_prompt_tokens=[11, 12])
        self.lm_gen.reset_streaming = Mock(side_effect=lambda: setattr(self.stream_state, 'offset', 0))
        self.lm_gen.step_system_prompts = Mock(side_effect=lambda _mimi: setattr(self.stream_state, 'offset', 5))
        self.mimi = SimpleNamespace(reset_streaming=Mock())
        self.other_mimi = SimpleNamespace(reset_streaming=Mock())
        self.torch = SimpleNamespace(no_grad=lambda: contextlib.nullcontext(),
            cuda=SimpleNamespace(synchronize=Mock(), max_memory_allocated=lambda _index: 100))

    def step(self, pcm):
        self.calls += 1; self.inputs.append(pcm); self.stream_state.offset += 1
        if self.failure == 'cache': self.cache_pointer = 56789
        if self.failure == 'prompt': self.lm_gen.text_prompt_tokens = [99]
        return worker.ModelFrame(bytes(experiment.FRAME_BYTES - (2 if self.failure == 'pcm' else 0)),
                                 101, ' Moss', .001)


def output_report(directory):
    report = {'status': 'completed', 'experiment': experiment.EXPERIMENT, 'source_revision': experiment.pinned.SOURCE_REVISION,
        'model_revision': experiment.pinned.MODEL_REVISION, 'voice': experiment.pinned.VOICE,
        'initial_prompt_sha256': experiment.PROMPT_SHA256, 'fixture_script_sha256': experiment.SCRIPT_SHA256,
        'model_loads': 1, 'independent_episodes': 3, 'between_episode_resets': 2, 'within_episode_resets': 0,
        'within_episode_prompt_updates': 0, 'within_episode_forced_tokens': 0, 'clock_frames': experiment.MAX_TOTAL_FRAMES,
        'banking_access': False, 'room_audio_used': False, 'runtime_downloads': False,
        'runtime_hf_credential': False, 'production_enabled': False, 'audio_sha256': {}}
    for episode in experiment.EPISODES:
        name = episode['id'] + '-output.wav'
        value = experiment.prior.wav_bytes(bytes(episode['frames'] * experiment.FRAME_BYTES))
        (directory / name).write_bytes(value); report['audio_sha256'][name] = experiment.digest(value)
    (directory / 'report.json').write_text(json.dumps(report))
    return report


class AdaptiveTests(unittest.TestCase):
    def test_default_plan_is_inert_and_carries_one_fixed_prompt_voice_and_bounded_episodes(self):
        with patch.object(experiment, 'validate_fixtures', side_effect=AssertionError('private fixture read')), \
                patch.object(experiment, 'cache_reference', side_effect=AssertionError('private cache read')), \
                patch.object(experiment.closed, 'existing_openrouter_key', side_effect=AssertionError('key read')), \
                patch.dict('sys.modules', {'modal': None, 'torch': None}), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(experiment.main([]), 0)
        plan = json.loads(output.getvalue())
        self.assertEqual(plan['maximum_episodes'], 3); self.assertEqual(plan['model_loads'], 1)
        self.assertEqual(plan['voice'], 'NATM1.pt'); self.assertEqual(plan['worker_seconds'], 360)
        self.assertEqual(plan['clock_seconds'], 80); self.assertEqual(plan['retries'], 0)
        self.assertFalse(plan['production_enabled']); self.assertFalse(plan['adaptive_behavior_verified'])
        self.assertIn(worker.COMMON_BOUNDARY, plan['initial_prompt'])
        for form in ('Moss', 'Orbit', 'Spark'): self.assertIn(form, plan['initial_prompt'])

    def test_local_fixture_generator_is_fixed_english_and_contains_no_microphone_or_provider_flow(self):
        script = experiment.FIXTURE_GENERATOR.read_text()
        for _name, _rate, text in experiment.FIXTURE_SCRIPTS: self.assertIn(text, script)
        self.assertIn("Culture.Name -eq 'en-US'", script); self.assertIn('SetOutputToWaveFile', script)
        self.assertNotIn('SpeechRecognition', script); self.assertNotIn('https://', script)
        self.assertNotIn('Get-Credential', script); self.assertNotIn('ExecutionPolicy', script)
        self.assertNotIn('Get-FileHash', script)  # Host PowerShell5 lacks this cmdlet; use .NET SHA256.

    def test_fixture_validation_rejects_script_hash_culture_provenance_and_duration_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder); original = fixtures_at(directory)
            self.assertEqual(set(experiment.validate_fixtures(directory)[1]), {name for name, *_rest in experiment.FIXTURE_SCRIPTS})
            for key, bad in (('culture', 'de-DE'), ('microphone_used', True), ('provider_used', True)):
                manifest = {**original, key: bad}; (directory / 'manifest.json').write_text(json.dumps(manifest))
                with self.assertRaises(ValueError): experiment.validate_fixtures(directory)
            original['fixtures'][0]['text'] = 'private-user-audio'
            (directory / 'manifest.json').write_text(json.dumps(original))
            with self.assertRaises(ValueError): experiment.validate_fixtures(directory)
            fixtures_at(directory); (directory / 'anxious.wav').write_bytes(b'changed')
            with self.assertRaises(ValueError): experiment.validate_fixtures(directory)
        with self.assertRaises(ValueError): experiment.read_pcm(experiment.prior.wav_bytes(bytes(151 * experiment.FRAME_BYTES)), 150)

    def test_exact_episode_pcm_preserves_public_clips_and_midconversation_pace_change(self):
        fixtures = {name: bytes([index + 1, 0]) * experiment.FRAME_SAMPLES * 5
                    for index, (name, *_rest) in enumerate(experiment.FIXTURE_SCRIPTS)}
        for episode in experiment.EPISODES:
            pcm = experiment.episode_input(episode, fixtures)
            self.assertEqual(len(pcm), episode['frames'] * experiment.FRAME_BYTES)
            for first, name in episode['clips']:
                offset = first * experiment.FRAME_BYTES
                self.assertEqual(pcm[offset:offset + len(fixtures[name])], fixtures[name])
            if len(episode['clips']) == 2:
                self.assertTrue(all(value == 0 for value in pcm[len(fixtures['energetic']):150 * experiment.FRAME_BYTES]))
        with self.assertRaises(ValueError): experiment.episode_input({'id': 'custom', 'frames': 900}, fixtures)

    def test_model_initializer_uses_one_candidate_prompt_and_restores_original_mapping(self):
        old = dict(worker.PERSONAS)
        def load(settings):
            self.assertEqual(settings.voice, 'NATM1.pt'); self.assertEqual(worker.PERSONAS['moss'], experiment.ADAPTIVE_PROMPT)
            return 'one model'
        with patch.object(worker, 'NativeModel', side_effect=load) as initializer:
            self.assertEqual(experiment.create_model(), 'one model')
        initializer.assert_called_once(); self.assertEqual(worker.PERSONAS, old)
        with patch.object(worker, 'NativeModel', side_effect=RuntimeError('fixture')):
            with self.assertRaises(RuntimeError): experiment.create_model()
        self.assertEqual(worker.PERSONAS, old)

    def test_native_episode_keeps_prompt_cache_and_global_clock_without_resets(self):
        episode = experiment.EPISODES[2]; pcm = bytes(episode['frames'] * experiment.FRAME_BYTES); model = FakeModel()
        result = experiment.run_episode(model, episode, pcm)
        self.assertEqual(model.calls, 400); self.assertEqual(len(result['pcm']), len(pcm))
        self.assertEqual(result['lm_offset_end'] - result['lm_offset_start'], 400)
        self.assertEqual(result['records'][-1]['sample_index'], 399 * experiment.FRAME_SAMPLES)
        self.assertEqual(model.lm_gen.text_prompt_tokens, [11, 12])
        model.lm_gen.reset_streaming.assert_not_called(); model.lm_gen.step_system_prompts.assert_not_called()
        model.mimi.reset_streaming.assert_not_called(); model.other_mimi.reset_streaming.assert_not_called()

    def test_episode_refuses_changed_cache_prompt_or_malformed_native_frame(self):
        episode = experiment.EPISODES[0]; pcm = bytes(episode['frames'] * experiment.FRAME_BYTES)
        for failure in ('cache', 'prompt', 'pcm'):
            with self.subTest(failure=failure), self.assertRaises(ValueError):
                experiment.run_episode(FakeModel(failure), episode, pcm)

    def test_between_episode_reset_uses_stock_priming_and_refreshes_state_only_at_boundary(self):
        model = FakeModel(); experiment.reset_between_episodes(model)
        self.assertEqual(model.lm_gen.text_prompt_tokens, [11, 12]); self.assertEqual(model.stream_state.offset, 5)
        model.lm_gen.reset_streaming.assert_called_once(); model.lm_gen.step_system_prompts.assert_called_once_with(model.mimi)
        self.assertEqual(model.mimi.reset_streaming.call_count, 2); model.other_mimi.reset_streaming.assert_called_once()
        self.assertEqual(model.cache_pointer, model.stream_state.cache.data_ptr())

    def test_whole_worker_loads_once_and_has_only_two_independent_boundary_resets(self):
        fixtures = {name: bytes(experiment.FRAME_BYTES * 5) for name, *_rest in experiment.FIXTURE_SCRIPTS}
        model = FakeModel()
        with tempfile.TemporaryDirectory() as folder, patch.object(experiment, 'WORK', Path(folder)), \
                patch.object(experiment, 'validate_fixtures', return_value=({'generator': 'synthetic unit fixture'}, fixtures)), \
                patch.object(experiment, 'create_model', return_value=model) as initializer, \
                patch.object(experiment, 'reset_between_episodes', wraps=experiment.reset_between_episodes) as resets:
            experiment.run_worker({}); report = json.loads((Path(folder) / 'report.json').read_text())
            self.assertEqual({path.name for path in Path(folder).iterdir()}, experiment.ARTIFACT_NAMES)
        initializer.assert_called_once(); self.assertEqual(resets.call_count, 2); self.assertEqual(model.calls, 1000)
        self.assertEqual(report['within_episode_resets'], 0); self.assertEqual(report['within_episode_prompt_updates'], 0)
        self.assertFalse(report['adaptive_behavior_verified']); self.assertFalse(report['production_enabled'])

    def test_cached_image_copies_only_source_and_fixed_fixtures_with_no_hf_or_heavy_builder(self):
        image = Mock(); image.add_local_python_source.return_value = image; image.add_local_file.return_value = image
        app = Mock(); app.function.return_value = lambda function: function
        sdk = SimpleNamespace(Image=SimpleNamespace(from_id=Mock(return_value=image)), App=Mock(return_value=app))
        with patch.dict('sys.modules', {'modal': sdk}), patch.object(experiment, 'validate_fixtures'), \
                patch.object(experiment.pinned, 'existing_token', side_effect=AssertionError('HF read')), \
                patch.object(experiment.pinned, 'build_image', side_effect=AssertionError('heavy build')):
            experiment.build_app('im-existing')
        sdk.Image.from_id.assert_called_once_with('im-existing'); self.assertEqual(image.add_local_file.call_count, 5)
        image.add_local_python_source.assert_called_once_with(*experiment.SOURCE_MODULES, copy=True)
        for call in image.add_local_file.call_args_list:
            self.assertTrue(call.kwargs['copy'])
            self.assertTrue(PurePosixPath(call.args[1]).is_absolute())
            self.assertNotIn('\\', call.args[1])
        parameters = app.function.call_args.kwargs
        self.assertEqual(parameters['timeout'], 600); self.assertEqual(parameters['startup_timeout'], 60)
        self.assertEqual(parameters['max_containers'], 1); self.assertEqual(parameters['retries'], 0)
        self.assertEqual(parameters['min_containers'], 0); self.assertTrue(parameters['single_use_containers'])
        self.assertFalse(parameters['serialized']); self.assertNotIn('secrets', parameters)

    def test_installed_modal_accepts_local_app_definition_with_posix_fixture_paths_without_dispatch(self):
        try: import modal
        except ImportError: self.skipTest('Optional Modal SDK is not installed')
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder); fixtures_at(directory)
            with patch.object(experiment, 'FIXTURES', directory), \
                    patch.object(modal.App, 'run', side_effect=AssertionError('cloud lifecycle')), \
                    patch.object(modal.Function, 'spawn', side_effect=AssertionError('cloud dispatch')), \
                    patch.object(experiment.pinned, 'existing_token', side_effect=AssertionError('HF credential')):
                app, function = experiment.build_app('im-local-definition-only')
        self.assertIsInstance(app, modal.App)
        self.assertIsInstance(function, modal.Function)

    def test_source_overlay_imports_in_unrelated_directory_without_checkout_or_sdk(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as unrelated:
            for module in experiment.SOURCE_MODULES:
                shutil.copyfile(Path(experiment.__file__).with_name(module + '.py'), Path(folder) / (module + '.py'))
            result = subprocess.run([sys.executable, str(Path(folder) / 'personaplex_adaptive_prompt.py'), '--plan'],
                cwd=unrelated, capture_output=True, text=True, timeout=5, env={k:v for k,v in os.environ.items() if k!='PYTHONPATH'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['experiment'], experiment.EXPERIMENT)

    def test_missing_or_changed_fixtures_refuse_dispatch_before_cache_key_or_sdk_access(self):
        with patch.object(experiment, 'validate_fixtures', side_effect=ValueError('private-sentinel')), \
                patch.object(experiment, 'cache_reference', side_effect=AssertionError('cache read')) as cache, \
                patch.object(experiment, 'build_app', side_effect=AssertionError('dispatch')) as build, \
                patch.object(experiment, 'save_failure'), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(experiment.main(['--execute']), 1)
        cache.assert_not_called(); build.assert_not_called(); self.assertNotIn('sentinel', output.getvalue())

    def test_client_failure_cancels_one_input_and_container_without_retry(self):
        job = Mock(); job.get.side_effect = TimeoutError('private-sentinel')
        function = Mock(); function.spawn.return_value = job
        app = Mock(); app.run.return_value = contextlib.nullcontext()
        with patch.object(experiment, 'validate_fixtures'), patch.object(experiment, 'cache_reference', return_value='im-existing'), \
                patch.object(experiment, 'build_app', return_value=(app, function)), patch.object(experiment, 'save_failure'), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(experiment.main(['--execute']), 1)
        function.spawn.assert_called_once(); job.get.assert_called_once_with(timeout=675)
        job.cancel.assert_called_once_with(terminate_containers=True); self.assertNotIn('sentinel', output.getvalue())

    def test_asr_validates_every_output_hash_duration_and_scope_before_any_key_read(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); result = root / 'fixed'; result.mkdir(); output_report(result)
            with patch.object(experiment, 'DIRECTORY', root):
                self.assertEqual(len(experiment.validated_asr_outputs(result)), 3)
                path = result / (experiment.EPISODES[2]['id'] + '-output.wav'); path.write_bytes(path.read_bytes() + b'changed')
                with patch.object(experiment.closed, 'existing_openrouter_key', side_effect=AssertionError('key read')) as key:
                    with self.assertRaises(ValueError): experiment.verify_asr(result)
                key.assert_not_called()
                with self.assertRaises(ValueError): experiment.validated_asr_outputs(root.parent)

    def test_asr_named_form_observation_is_distinct_from_human_style_or_bank_authority(self):
        self.assertTrue(experiment.identity_observation('I am Spark. Now I am Moss.', ['spark', 'moss'])['named_form_sequence_matched'])
        self.assertFalse(experiment.identity_observation('I am Moss.', ['orbit'])['named_form_sequence_matched'])
        value = experiment.identity_observation('I am Moss. I checked your bank account.', ['moss'])
        self.assertTrue(value['bank_related_speech_requires_review']); self.assertFalse(value['human_style_verified'])
        self.assertFalse(value['bank_narration_enabled'])

    def test_separate_asr_mode_makes_only_three_fixed_requests_after_all_hash_checks(self):
        transcripts = ['I am Moss. Take one small step.', 'I am Orbit. Let us make a plan.',
                       'I am Spark. Let us go! Now I am Moss. Let us slow down.']
        responses = []
        for text in transcripts:
            response = Mock(status=200); response.read.return_value = json.dumps({'text': text}).encode('utf8')
            responses.append(contextlib.nullcontext(response))
        opener = Mock(); opener.open.side_effect = responses
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); result = root / 'fixed'; result.mkdir(); output_report(result)
            with patch.object(experiment, 'DIRECTORY', root), \
                    patch.object(experiment.closed, 'existing_openrouter_key', return_value='unit-test-placeholder') as key, \
                    patch.object(experiment.urllib.request, 'build_opener', return_value=opener):
                observation = experiment.verify_asr(result)
                with self.assertRaises(ValueError): experiment.verify_asr(result)
            receipt = json.loads((result / 'private-asr.json').read_text())
        key.assert_called_once(); self.assertEqual(opener.open.call_count, 3)
        self.assertTrue(observation['all_named_sequences_matched']); self.assertFalse(observation['human_style_verified'])
        self.assertEqual(receipt['status'], 'completed')
        self.assertNotIn('transcript', observation['episodes'][0])
        for call in opener.open.call_args_list:
            request = call.args[0]; body = json.loads(request.data)
            self.assertEqual(request.full_url, experiment.closed.ASR_ENDPOINT)
            self.assertEqual(body['model'], experiment.closed.ASR_MODEL); self.assertEqual(body['language'], 'en')
            self.assertEqual(call.kwargs['timeout'], 45)

    def test_partial_asr_failure_retains_no_retry_receipt_and_does_not_restart_provider_batch(self):
        response = Mock(status=200); response.read.return_value = json.dumps({'text': 'I am Moss.'}).encode('utf8')
        opener = Mock(); opener.open.side_effect = [contextlib.nullcontext(response), RuntimeError('private-provider-url')]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); result = root / 'fixed'; result.mkdir(); output_report(result)
            with patch.object(experiment, 'DIRECTORY', root), \
                    patch.object(experiment.closed, 'existing_openrouter_key', return_value='unit-test-placeholder') as key, \
                    patch.object(experiment.urllib.request, 'build_opener', return_value=opener):
                with self.assertRaises(RuntimeError): experiment.verify_asr(result)
                with self.assertRaises(ValueError): experiment.verify_asr(result)
            receipt = json.loads((result / 'private-asr.json').read_text())
        key.assert_called_once(); self.assertEqual(opener.open.call_count, 2)
        self.assertEqual(receipt['status'], 'failed_no_retry'); self.assertEqual(len(receipt['observations']), 1)
        self.assertNotIn('private-provider-url', json.dumps(receipt))

    def test_offline_child_has_hard_360_second_bound_without_runtime_hf_or_retry(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(experiment, 'WORK', Path(folder) / 'new'), \
                patch.dict(os.environ, {}, clear=True), \
                patch.object(experiment.subprocess, 'run', side_effect=subprocess.TimeoutExpired('fixed-child', 360)) as process:
            value = experiment.gpu_adaptive_prompt()
        process.assert_called_once(); self.assertEqual(process.call_args.kwargs['timeout'], 360)
        self.assertEqual(process.call_args.kwargs['env']['HF_HUB_OFFLINE'], '1')
        self.assertEqual(process.call_args.kwargs['env']['TRANSFORMERS_OFFLINE'], '1')
        self.assertEqual(value['failure_code'], 'deadline_exceeded')
        with patch.dict(os.environ, {'HF_TOKEN': 'unit-test-placeholder'}), patch.object(experiment.subprocess, 'run') as process:
            self.assertEqual(experiment.gpu_adaptive_prompt()['status'], 'failed')
        process.assert_not_called()

    def test_worker_failure_keeps_only_fixed_stage_and_episode_without_raw_message(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            def fail(progress):
                progress.update(stage='independent_episode', episode=2)
                raise ValueError('private-key-and-provider-url')
            with patch.object(experiment, 'WORK', directory), patch.dict(os.environ, {'HF_HUB_OFFLINE': '1'}), \
                    patch.object(experiment, 'run_worker', side_effect=fail):
                self.assertEqual(experiment.main(['--worker']), 1)
            value = json.loads((directory / 'worker-failure.json').read_text())
        self.assertEqual(value['stage'], 'independent_episode'); self.assertEqual(value['episode'], 2)
        self.assertEqual(value['error_class'], 'ValueError'); self.assertNotIn('private', json.dumps(value))


if __name__ == '__main__': unittest.main()
