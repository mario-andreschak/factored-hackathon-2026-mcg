"""Local-only unchanged fixed prompts, fresh episodes and bounded ASR tests."""
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

import personaplex_fixed_roles as experiment
from test_personaplex_adaptive_prompt import FakeModel, fixtures_at


class RoleModel(FakeModel):
    def __init__(self, failure=None):
        super().__init__(failure)
        self.prompts_seen = []
        self.tokenizer = SimpleNamespace(encode=Mock(side_effect=lambda text: [21] if 'Orbit' in text else [31]))

    def step(self, pcm):
        self.prompts_seen.append(tuple(self.lm_gen.text_prompt_tokens))
        return super().step(pcm)


def completed_report(directory):
    report = {'status': 'completed', 'experiment': experiment.EXPERIMENT,
        'source_revision': experiment.pinned.SOURCE_REVISION, 'model_revision': experiment.pinned.MODEL_REVISION,
        'voice': experiment.pinned.VOICE, 'production_prompt_sha256': experiment.PROMPT_SHA256,
        'production_prompts_unchanged': True, 'fixture_script_sha256': experiment.common.SCRIPT_SHA256,
        'model_loads': 1, 'independent_conversations': 3, 'between_conversation_resets': 2,
        'within_conversation_resets': 0, 'within_conversation_prompt_updates': 0,
        'within_conversation_forced_tokens': 0, 'clock_frames': 900,
        'banking_access': False, 'room_audio_used': False, 'runtime_downloads': False,
        'runtime_hf_credential': False, 'production_enabled': False, 'episodes': [], 'audio_sha256': {}}
    for episode in experiment.EPISODES:
        role = episode['avatar']; name = role + '-output.wav'
        value = experiment.prior.wav_bytes(bytes(experiment.FRAMES * experiment.FRAME_BYTES))
        (directory / name).write_bytes(value); report['audio_sha256'][name] = experiment.common.digest(value)
        report['episodes'].append({**episode, 'production_prompt_sha256': experiment.PROMPT_SHA256[role],
            'continuous_cache_preserved': True, 'lm_offset_start': 50, 'lm_offset_end': 350})
    (directory / 'report.json').write_text(json.dumps(report))
    return report


class FixedRolesTests(unittest.TestCase):
    def test_default_plan_reads_no_fixtures_cache_credentials_or_sdk(self):
        with patch.object(experiment.common, 'validate_fixtures', side_effect=AssertionError('fixture read')), \
                patch.object(experiment.common, 'cache_reference', side_effect=AssertionError('cache read')), \
                patch.object(experiment.closed, 'existing_openrouter_key', side_effect=AssertionError('key read')), \
                patch.dict('sys.modules', {'modal': None, 'torch': None}), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(experiment.main([]), 0)
        value = json.loads(output.getvalue())
        self.assertEqual(value['model_loads'], 1); self.assertEqual(value['clock_frames'], 900)
        self.assertEqual(value['clock_seconds'], 72); self.assertEqual(value['worker_seconds'], 360)
        self.assertEqual(value['function_seconds'], 600); self.assertEqual(value['client_seconds'], 675)
        self.assertTrue(value['production_prompts_unchanged']); self.assertFalse(value['production_enabled'])

    def test_first_model_uses_exact_unchanged_production_moss_constructor_and_nat_m1(self):
        original = dict(experiment.worker.PERSONAS)
        with patch.object(experiment.worker, 'NativeModel', return_value='one weights load') as constructor:
            self.assertEqual(experiment.create_model(), 'one weights load')
        constructor.assert_called_once()
        settings = constructor.call_args.args[0]
        self.assertEqual(settings.avatar, 'moss'); self.assertEqual(settings.voice, 'NATM1.pt')
        self.assertEqual(settings.deadline_seconds, 600); self.assertEqual(experiment.worker.PERSONAS, original)

    def test_initial_tokens_use_exact_production_string_stock_wrapper_and_tokenizer(self):
        tokenizer = SimpleNamespace(encode=Mock(return_value=[11, 12])); wrapper = Mock(side_effect=lambda text: '<stock>' + text)
        for role in experiment.ROLES:
            self.assertEqual(experiment.initial_prompt_tokens(tokenizer, role, wrapper), [11, 12])
            wrapper.assert_called_with(experiment.worker.PERSONAS[role])
            tokenizer.encode.assert_called_with('<stock>' + experiment.worker.PERSONAS[role])
        for role in ('adaptive', 'custom', 'Moss'):
            with self.assertRaises(ValueError): experiment.initial_prompt_tokens(tokenizer, role, wrapper)
        for tokens in ([], [True], [-1], [32_001], [1] * 513):
            tokenizer.encode.return_value = tokens
            with self.assertRaises(ValueError): experiment.initial_prompt_tokens(tokenizer, 'orbit', wrapper)

    def test_later_episode_assigns_prompt_before_stock_voice_replay_and_refreshes_cache_reference(self):
        model = RoleModel(); order = []
        model.tokenizer.encode.side_effect = lambda text: order.append(('encode', text)) or [21]
        model.lm_gen.step_system_prompts.side_effect = lambda _mimi: order.append(('prime', tuple(model.lm_gen.text_prompt_tokens)))
        experiment.prime_next_episode(model, 'orbit', lambda text: '<stock>' + text)
        self.assertEqual(order, [('encode', '<stock>' + experiment.worker.PERSONAS['orbit']), ('prime', (21,))])
        model.lm_gen.reset_streaming.assert_called_once(); self.assertEqual(model.mimi.reset_streaming.call_count, 2)
        model.other_mimi.reset_streaming.assert_called_once(); self.assertEqual(model.cache_pointer, model.stream_state.cache.data_ptr())
        with self.assertRaises(ValueError): experiment.prime_next_episode(model, 'moss', lambda text: text)

    def test_only_original_first_clips_are_streamed_once_and_silence_fills_24_seconds(self):
        fixtures = {name: bytes([index + 1, 0]) * experiment.FRAME_SAMPLES * 5
                    for index, (name, *_rest) in enumerate(experiment.common.FIXTURE_SCRIPTS)}
        for episode in experiment.EPISODES:
            value = experiment.episode_input(episode, fixtures); clip = fixtures[episode['fixture']]
            self.assertEqual(value[:len(clip)], clip); self.assertFalse(any(value[len(clip):]))
            self.assertEqual(len(value), 300 * experiment.FRAME_BYTES)
        self.assertNotIn('slow-again', [episode['fixture'] for episode in experiment.EPISODES])
        with self.assertRaises(ValueError): experiment.episode_input({'avatar': 'custom'}, fixtures)

    def test_whole_worker_loads_once_runs_three_fresh_roles_and_never_reprimes_within_episode(self):
        model = RoleModel(); fixtures = {name: bytes(5 * experiment.FRAME_BYTES) for name, *_rest in experiment.common.FIXTURE_SCRIPTS}
        stock_prime = experiment.prime_next_episode
        def prime_role(instance, role):
            stock_prime(instance, role, lambda text: '<stock>' + text)
        original = dict(experiment.worker.PERSONAS)
        with tempfile.TemporaryDirectory() as folder, patch.object(experiment, 'WORK', Path(folder)), \
                patch.object(experiment.common, 'validate_fixtures', return_value=({'provenance': 'unit synthetic'}, fixtures)), \
                patch.object(experiment, 'create_model', return_value=model) as initializer, \
                patch.object(experiment, 'prime_next_episode', side_effect=prime_role) as primes:
            experiment.run_worker({})
            report = json.loads((Path(folder) / 'report.json').read_text())
            self.assertEqual({path.name for path in Path(folder).iterdir()}, experiment.ARTIFACT_NAMES)
        initializer.assert_called_once(); self.assertEqual([call.args[1] for call in primes.call_args_list], ['orbit', 'spark'])
        self.assertEqual(model.calls, 900); self.assertEqual(model.lm_gen.reset_streaming.call_count, 2)
        self.assertEqual(model.prompts_seen[:300], [(11, 12)] * 300)
        self.assertEqual(model.prompts_seen[300:600], [(21,)] * 300); self.assertEqual(model.prompts_seen[600:], [(31,)] * 300)
        self.assertEqual(report['model_loads'], 1); self.assertEqual(report['between_conversation_resets'], 2)
        self.assertEqual(report['within_conversation_prompt_updates'], 0); self.assertEqual(report['within_conversation_forced_tokens'], 0)
        self.assertEqual(report['production_prompt_sha256'], experiment.PROMPT_SHA256)
        self.assertEqual(experiment.worker.PERSONAS, original); self.assertFalse(report['fixed_role_behavior_verified'])

    def test_native_verifier_refuses_changed_prompt_cache_or_pcm_inside_a_role(self):
        for failure in ('prompt', 'cache', 'pcm'):
            with self.subTest(failure=failure), self.assertRaises(ValueError):
                experiment.common.run_native_episode(RoleModel(failure), bytes(300 * experiment.FRAME_BYTES), 300)
        for frames in (True, 0, 401):
            with self.assertRaises(ValueError): experiment.common.run_native_episode(RoleModel(), bytes(300 * experiment.FRAME_BYTES), frames)

    def test_source_fixture_copy_preserves_pins_and_job_bounds_without_hf_or_weight_builder(self):
        image = Mock(); image.add_local_python_source.return_value = image; image.add_local_file.return_value = image
        app = Mock(); app.function.return_value = lambda function: function
        sdk = SimpleNamespace(Image=SimpleNamespace(from_id=Mock(return_value=image)), App=Mock(return_value=app))
        with patch.dict('sys.modules', {'modal': sdk}), patch.object(experiment.common, 'validate_fixtures'), \
                patch.object(experiment.pinned, 'existing_token', side_effect=AssertionError('HF read')), \
                patch.object(experiment.pinned, 'build_image', side_effect=AssertionError('weight build')):
            experiment.build_app('im-existing')
        sdk.Image.from_id.assert_called_once_with('im-existing'); self.assertEqual(image.add_local_file.call_count, 5)
        image.add_local_python_source.assert_called_once_with(*experiment.SOURCE_MODULES, copy=True)
        for call in image.add_local_file.call_args_list:
            self.assertTrue(call.kwargs['copy']); self.assertTrue(PurePosixPath(call.args[1]).is_absolute())
            self.assertNotIn('\\', call.args[1])
        values = app.function.call_args.kwargs
        self.assertEqual(values['timeout'], 600); self.assertEqual(values['startup_timeout'], 60)
        self.assertEqual(values['retries'], 0); self.assertEqual(values['max_containers'], 1)
        self.assertTrue(values['single_use_containers']); self.assertFalse(values['serialized']); self.assertNotIn('secrets', values)

    def test_installed_sdk_accepts_definition_without_running_or_spawning(self):
        try: import modal
        except ImportError: self.skipTest('Optional Modal SDK not installed')
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder); fixtures_at(directory)
            with patch.object(experiment.common, 'FIXTURES', directory), \
                    patch.object(modal.App, 'run', side_effect=AssertionError('cloud lifecycle')), \
                    patch.object(modal.Function, 'spawn', side_effect=AssertionError('cloud dispatch')):
                app, function = experiment.build_app('im-local-definition-only')
        self.assertIsInstance(app, modal.App); self.assertIsInstance(function, modal.Function)

    def test_source_overlay_runs_in_unrelated_working_directory_without_checkout_or_sdk(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as unrelated:
            for module in experiment.SOURCE_MODULES:
                shutil.copyfile(Path(experiment.__file__).with_name(module + '.py'), Path(folder) / (module + '.py'))
            result = subprocess.run([sys.executable, str(Path(folder) / 'personaplex_fixed_roles.py'), '--plan'],
                cwd=unrelated, capture_output=True, text=True, timeout=5, env={key:value for key,value in os.environ.items() if key!='PYTHONPATH'})
        self.assertEqual(result.returncode, 0, result.stderr); self.assertEqual(json.loads(result.stdout)['experiment'], experiment.EXPERIMENT)

    def test_invalid_fixture_fails_before_cache_sdk_or_any_job(self):
        with patch.object(experiment.common, 'validate_fixtures', side_effect=ValueError('private-sentinel')), \
                patch.object(experiment.common, 'cache_reference', side_effect=AssertionError('cache read')) as cache, \
                patch.object(experiment, 'build_app', side_effect=AssertionError('job dispatch')) as build, \
                patch.object(experiment, 'save_failure'), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(experiment.main(['--execute']), 1)
        cache.assert_not_called(); build.assert_not_called(); self.assertNotIn('sentinel', output.getvalue())

    def test_one_input_timeout_cancels_container_without_retry_or_raw_exception(self):
        job = Mock(); job.get.side_effect = TimeoutError('private-sentinel'); function = Mock(); function.spawn.return_value = job
        app = Mock(); app.run.return_value = contextlib.nullcontext()
        with patch.object(experiment.common, 'validate_fixtures'), patch.object(experiment.common, 'cache_reference', return_value='im-existing'), \
                patch.object(experiment, 'build_app', return_value=(app, function)), patch.object(experiment, 'save_failure'), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(experiment.main(['--execute']), 1)
        function.spawn.assert_called_once(); job.get.assert_called_once_with(timeout=675)
        job.cancel.assert_called_once_with(terminate_containers=True); self.assertNotIn('sentinel', output.getvalue())

    def test_child_hard_bound_offline_flags_and_runtime_hf_rejection(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(experiment, 'WORK', Path(folder) / 'new'), \
                patch.dict(os.environ, {}, clear=True), patch.object(experiment.subprocess, 'run', side_effect=subprocess.TimeoutExpired('child', 360)) as child:
            value = experiment.gpu_fixed_roles()
        child.assert_called_once(); self.assertEqual(child.call_args.kwargs['timeout'], 360)
        self.assertEqual(child.call_args.kwargs['env']['HF_HUB_OFFLINE'], '1'); self.assertEqual(value['failure_code'], 'deadline_exceeded')
        with patch.dict(os.environ, {'HF_TOKEN': 'unit-placeholder'}), patch.object(experiment.subprocess, 'run') as child:
            self.assertEqual(experiment.gpu_fixed_roles()['status'], 'failed')
        child.assert_not_called()

    def test_safe_child_failure_preserves_only_fixed_phase_class_and_episode(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            def fail(progress):
                progress.update(stage='initial_role_prompt', episode=3); raise ValueError('private-provider-url')
            with patch.object(experiment, 'WORK', directory), patch.dict(os.environ, {'HF_HUB_OFFLINE': '1'}), \
                    patch.object(experiment, 'run_worker', side_effect=fail):
                self.assertEqual(experiment.main(['--worker']), 1)
            value = experiment.safe_worker_failure(json.loads((directory / 'worker-failure.json').read_text()))
        self.assertEqual(value['stage'], 'initial_role_prompt'); self.assertEqual(value['episode'], 3)
        self.assertNotIn('private', json.dumps(value))
        with self.assertRaises(ValueError): experiment.safe_worker_failure({**value, 'raw': 'private'})

    def test_all_output_hashes_prompt_and_per_role_clock_are_verified_before_key_read(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); directory = root / 'completed'; directory.mkdir(); original = completed_report(directory)
            with patch.object(experiment, 'DIRECTORY', root):
                self.assertEqual(len(experiment.validated_asr_outputs(directory)), 3)
                for key, bad in (('production_prompts_unchanged', False), ('within_conversation_prompt_updates', 1), ('model_loads', True)):
                    (directory/'report.json').write_text(json.dumps({**original, key:bad}))
                    with patch.object(experiment.closed, 'existing_openrouter_key', side_effect=AssertionError('key read')) as key_read:
                        with self.assertRaises(ValueError): experiment.verify_asr(directory)
                    key_read.assert_not_called()
                (directory/'report.json').write_text(json.dumps(original)); (directory/'spark-output.wav').write_bytes(b'changed')
                with patch.object(experiment.closed, 'existing_openrouter_key', side_effect=AssertionError('key read')) as key_read:
                    with self.assertRaises(ValueError): experiment.verify_asr(directory)
                key_read.assert_not_called()

    def test_separate_asr_makes_three_fixed_requests_once_and_does_not_claim_style(self):
        texts = ['I am Moss.', 'I am Orbit.', 'I am Spark.']; responses = []
        for text in texts:
            response = Mock(status=200); response.read.return_value = json.dumps({'text':text}).encode()
            responses.append(contextlib.nullcontext(response))
        opener = Mock(); opener.open.side_effect = responses
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); directory = root/'completed'; directory.mkdir(); completed_report(directory)
            with patch.object(experiment, 'DIRECTORY', root), patch.object(experiment.closed, 'existing_openrouter_key', return_value='unit-placeholder') as key_read, \
                    patch.object(experiment.urllib.request, 'build_opener', return_value=opener):
                result = experiment.verify_asr(directory)
                with self.assertRaises(ValueError): experiment.verify_asr(directory)
        key_read.assert_called_once(); self.assertEqual(opener.open.call_count, 3)
        self.assertTrue(result['all_named_sequences_matched']); self.assertFalse(result['human_style_verified'])
        self.assertFalse(result['production_enabled']); self.assertNotIn('transcript', result['roles'][0])
        for call in opener.open.call_args_list:
            request=call.args[0]; body=json.loads(request.data)
            self.assertEqual(request.full_url, experiment.closed.ASR_ENDPOINT)
            self.assertEqual(body['model'], experiment.closed.ASR_MODEL); self.assertEqual(body['language'], 'en')
            self.assertEqual(call.kwargs['timeout'], 45)

    def test_partial_asr_failure_keeps_admission_and_does_not_repeat_batch(self):
        response = Mock(status=200); response.read.return_value = json.dumps({'text':'I am Moss.'}).encode()
        opener = Mock(); opener.open.side_effect = [contextlib.nullcontext(response), RuntimeError('private-provider-message')]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); directory=root/'completed'; directory.mkdir(); completed_report(directory)
            with patch.object(experiment, 'DIRECTORY', root), patch.object(experiment.closed, 'existing_openrouter_key', return_value='unit-placeholder') as key_read, \
                    patch.object(experiment.urllib.request, 'build_opener', return_value=opener):
                with self.assertRaises(RuntimeError): experiment.verify_asr(directory)
                with self.assertRaises(ValueError): experiment.verify_asr(directory)
            receipt=json.loads((directory/'private-asr.json').read_text())
        key_read.assert_called_once(); self.assertEqual(opener.open.call_count, 2)
        self.assertEqual(receipt['status'], 'failed_no_retry'); self.assertEqual(len(receipt['observations']), 1)
        self.assertNotIn('private-provider-message', json.dumps(receipt))


if __name__ == '__main__': unittest.main()
