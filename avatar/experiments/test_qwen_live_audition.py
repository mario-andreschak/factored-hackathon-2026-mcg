"""Inert Stage A tests: no cloud, model, download, provider or microphone."""
import asyncio
import base64
import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import qwen_live_audition as experiment


def delta(data=b'\x10\x00' * 480, finished=False):
    return {'type': 'response.output_audio.delta', 'response_id': 'synthetic-response',
        'delta': base64.b64encode(data).decode(), 'format': 'pcm16',
        'sample_rate_hz': 24000, 'metadata': {'end_of_turn': finished}}


def completed_evidence():
    evidence = experiment.StreamEvidence()
    evidence.accept({'type': 'response.created', 'response': {'id': 'synthetic-response'}}, .1)
    evidence.accept(delta(), .2); evidence.accept(delta(), .4)
    evidence.accept({'type': 'response.output_audio.done', 'response_id': 'synthetic-response'}, .5)
    evidence.accept({'type': 'response.done', 'response': {'id': 'synthetic-response', 'status': 'completed'}}, .6)
    return evidence


class QwenLiveTests(unittest.TestCase):
    def test_runtime_build_targets_existing_python3_without_modal_python_alias_or_new_env(self):
        commands = []
        class Image:
            def entrypoint(self, *args): return self
            def apt_install(self, *args): return self
            def run_commands(self, *args): commands.extend(args); return self
            def pip_install(self, *args): raise AssertionError('Modal python alias is unavailable in this base')
            def add_local_python_source(self, *args, **kwargs): return self
            def add_local_file(self, *args, **kwargs): return self
            def env(self, *args): return self
        registry = Mock(return_value=Image())
        with patch.dict('sys.modules', {'modal': SimpleNamespace(Image=SimpleNamespace(from_registry=registry))}), \
                patch.object(experiment, 'verify_local_fixtures'):
            experiment.build_runtime_image()
        registry.assert_called_once_with(experiment.BASE_IMAGE)
        install = [command for command in commands if 'uv pip install' in command]
        self.assertEqual(len(install), 2)
        for command in install:
            self.assertIn('--python "$(python3 -c', command)
        self.assertTrue(any('45s python3 /root/qwen_live_audition.py --cache-vad' in command for command in commands))
        for command in commands:
            self.assertNotRegex(command, r'(?<![A-Za-z0-9_-])python(?:\s|$)')

    def test_explicit_python3_correction_requires_stopped_preserved_failure_and_old_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); provenance = root / 'runtime-python3-failure.json'
            marker = {'status': 'spent_before_dispatch', 'model_revision': experiment.native.MODEL_REVISION,
                'omni_revision': experiment.OMNI_REVISION}
            experiment.native.save_json(root / 'runtime-admitted.json', marker)
            original = root / '20261001-095041-1790866241039759700/failure.json'
            experiment.native.save_json(original, {'status': 'failed', 'stage': 'cpu_runtime'})
            value = {'status': 'image_command_failure_confirmed', 'app_id': 'ap-publicFixture', 'app_state': 'stopped',
                'tasks': 0, 'gpu_dispatched': False, 'cpu_function_dispatched': False, 'exit_code': 127,
                'reason': 'base_image_has_python3_without_python_alias',
                'failed_command': 'python -m pip install websockets==15.0.1',
                'original_failure': original.relative_to(root).as_posix()}
            experiment.native.save_json(provenance, value)
            with patch.object(experiment, 'DIRECTORY', root), patch.object(experiment, 'PYTHON3_PROVENANCE', provenance):
                self.assertEqual(experiment.require_python3_fix_provenance()['original_app_id'], 'ap-publicFixture')
                for changed in ({**value, 'gpu_dispatched': True}, {**value, 'tasks': 1},
                                {**value, 'original_failure': '../failure.json'}):
                    experiment.native.save_json(provenance, changed)
                    with self.assertRaises(ValueError): experiment.require_python3_fix_provenance()
                self.assertEqual(json.loads((root / 'runtime-admitted.json').read_text()), marker)

    def test_default_plan_never_reads_fixture_receipts_or_defines_cloud(self):
        with patch.dict('sys.modules', {'modal': None, 'torch': None, 'websockets': None}), \
            patch.object(experiment, 'build_app', side_effect=AssertionError('cloud definition')), \
            patch.object(experiment, 'require_runtime', side_effect=AssertionError('receipt read')), \
            patch.object(experiment, 'verify_local_fixtures', side_effect=AssertionError('fixture read')), \
            contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(experiment.main([]), 0)
        value = json.loads(output.getvalue())
        self.assertEqual(value['stage'], 'engine_duplex_ws_native_audio')
        self.assertEqual(value['gpu'], 'H100:2')
        self.assertEqual((value['function_seconds'], value['worker_seconds'], value['client_seconds']), (600, 540, 675))
        self.assertTrue(value['async_chunk']); self.assertFalse(value['runtime_downloads'])
        self.assertFalse(value['browser']); self.assertFalse(value['room_microphone'])
        self.assertLess(value['allocation_with_60s_startup_usd'], value['cost_ceiling_usd'])

    def test_exact_duplex_profile_and_paced_pcm_do_not_use_legacy_stt_or_sse(self):
        overlay = experiment.overlay()
        self.assertTrue(overlay['base_config'].endswith('/qwen3_omni_duplex.yaml'))
        self.assertTrue(overlay['async_chunk'])
        self.assertEqual(overlay['duplex_session']['max_sessions'], 1)
        self.assertEqual([stage['max_num_seqs'] for stage in overlay['stages']], [1, 1, 1])
        self.assertIn('--served-model-name', experiment.server_command())
        self.assertNotIn('--no-async-chunk', experiment.server_command())
        self.assertIn('duplex=1', experiment.SOCKET_URL)
        update = experiment.session_update(experiment.FIXTURES[0])
        self.assertEqual(update['session']['overlap_policy'], 'barge_in_on_speech')
        self.assertEqual(update['session']['audio']['input']['format'], {'type': 'audio/pcm', 'rate': 24000})
        self.assertEqual(experiment.FRAME_SAMPLES / experiment.RATE, .2)
        experiment.validate_session_ready({'type': 'session.updated', 'session': update['session']})
        for bad in ({'type': 'session.created', 'session': update['session']}, {'type': 'session.updated', 'session': {}}):
            with self.assertRaises(ValueError): experiment.validate_session_ready(bad)

    def test_hash_verified_existing_fixtures_are_raw_pcm_not_wav_headers(self):
        experiment.verify_local_fixtures()
        for sample in experiment.FIXTURES:
            value = (experiment.FIXTURE_DIRECTORY / (sample['id'] + '.wav')).read_bytes()
            pcm = experiment.verify_fixture(value, sample)
            self.assertEqual(pcm, value[44:])
            self.assertFalse(pcm.startswith(b'RIFF'))
            with self.assertRaises(ValueError): experiment.verify_fixture(value + b'extra', sample)
            changed = value[:100] + bytes([value[100] ^ 1]) + value[101:]
            with self.assertRaises(ValueError): experiment.verify_fixture(changed, sample)

    def test_terminal_whole_waveform_or_silent_deltas_cannot_pass_early_stream_gate(self):
        evidence = completed_evidence()
        result = evidence.result()
        self.assertTrue(result['nonterminal_audio_observed'])
        self.assertEqual(result['decoded_audio_deltas'], 2)
        for frames in ([delta()], [delta(finished=True), delta(finished=True)],
                       [delta(data=bytes(960)), delta(data=bytes(960))]):
            state = experiment.StreamEvidence()
            state.accept({'type': 'response.created', 'response': {'id': 'synthetic-response'}}, .01)
            for index, value in enumerate(frames): state.accept(value, .1 + index * .1)
            state.accept({'type': 'response.output_audio.done', 'response_id': 'synthetic-response'}, .4)
            state.accept({'type': 'response.done', 'response': {'id': 'synthetic-response', 'status': 'completed'}}, .5)
            with self.assertRaises(ValueError): state.result()
        for changed in ({**delta(), 'sample_rate_hz': 16000}, {**delta(), 'format': 'float32'},
                        {**delta(), 'delta': '!!!'}, delta(data=b'\x01'), {**delta(), 'response_id': None}):
            with self.assertRaises(ValueError): experiment.StreamEvidence().accept(changed, .1)
        with self.assertRaises(ValueError): evidence.accept(delta(), .7)

    def test_cuda13_and_two_real_bf16_h100_required_before_native_load(self):
        h100 = {'name': 'NVIDIA H100 80GB HBM3', 'capability': [9, 0], 'bf16': True}
        experiment.check_cuda_metadata(13000, '13.0', [h100, h100])
        for args in ((12080, '13.0', [h100, h100]), (13000, '12.8', [h100, h100]),
                     (13000, '13.0', [h100]), (13000, '13.0', [{**h100, 'name': 'A100'}, h100])):
            with self.assertRaises(ValueError): experiment.check_cuda_metadata(*args)

    def test_split_or_foreign_native_responses_cannot_supply_another_turn_terminal(self):
        state = experiment.StreamEvidence()
        state.accept({'type': 'response.created', 'response': {'id': 'synthetic-response'}}, .1)
        state.accept(delta(), .2)
        for value in ({'type': 'response.created', 'response': {'id': 'another-response'}},
                      {'type': 'response.output_audio.done', 'response_id': 'another-response'},
                      {'type': 'response.done', 'response': {'id': 'another-response', 'status': 'completed'}},
                      {**delta(), 'response_id': 'another-response'}):
            with self.assertRaises(ValueError): state.accept(value, .3)

    def test_cpu_deploy_guard_preserves_placement_sampling_seed_and_codec_windows(self):
        stages = [SimpleNamespace(stage_id=index, devices=device, gpu_memory_utilization=utilization,
            max_num_seqs=1, default_sampling_params={'max_tokens': tokens, 'seed': 42})
            for index, device, utilization, tokens in ((0, '0', .9, 128), (1, '1', .6, 384), (2, '1', .1, 65536))]
        deploy = SimpleNamespace(session_mode='duplex', async_chunk=True,
            duplex_session=SimpleNamespace(max_sessions=1, server_vad_model_path=experiment.VAD_FILE.as_posix()),
            stages=stages, connectors={'connector_of_shared_memory': {'name': 'SharedMemoryConnector', 'extra': {
                'initial_codec_chunk_frames': 4, 'codec_chunk_frames': 25, 'codec_left_context_frames': 25}}})
        experiment.validate_deploy(deploy)
        stages[1].default_sampling_params['seed'] = None
        with self.assertRaises(ValueError): experiment.validate_deploy(deploy)
        stages[1].default_sampling_params['seed'] = 42
        stages[1].devices = '0'
        with self.assertRaises(ValueError): experiment.validate_deploy(deploy)

    def test_live_gpu2_receipt_reuses_small_volume_manifest_without_old_gpu1_validator(self):
        values = self.artifacts()
        with tempfile.TemporaryDirectory() as directory:
            commit = Mock(); value = experiment.persist_live(values, commit, Path(directory))
            commit.assert_called_once(); self.assertLess(len(json.dumps(value)), 4096)
            self.assertEqual(set(value['files']), {'es.wav', 'pt.wav', 'report.json'})
            experiment.native.validate_delivery(value)
            with self.assertRaises(ValueError): experiment.native.validate_artifacts('native', values)
            report = json.loads(values['report.json']); report['gpu_count'] = 1
            with self.assertRaises(ValueError): experiment.validate_live_artifacts({**values, 'report.json': json.dumps(report).encode()})

    def test_download_has_true_async_deadline_and_exact_hash_size_cap(self):
        values = self.artifacts()
        with tempfile.TemporaryDirectory() as directory:
            receipt = experiment.persist_live(values, lambda: None, Path(directory))
        async def read(path):
            name = path.split('/')[-1]
            yield values[name]
        volume = SimpleNamespace(read_file=SimpleNamespace(aio=read))
        self.assertEqual(asyncio.run(experiment.download_live(receipt, volume)), values)
        async def stalled(path):
            await asyncio.sleep(2); yield b''
        with self.assertRaises(TimeoutError):
            asyncio.run(experiment.download_live(receipt, SimpleNamespace(read_file=SimpleNamespace(aio=stalled)), timeout=.01))
        async def oversized(path): yield values[path.split('/')[-1]] + b'overflow'
        with self.assertRaises(ValueError):
            asyncio.run(experiment.download_live(receipt, SimpleNamespace(read_file=SimpleNamespace(aio=oversized))))

    def test_new_one_use_marker_preserves_prior_native_admissions_and_sanitizes_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); old = root / 'gpu-delivery-fix-admitted.json'; old.write_text('historical')
            marker = root / 'qwen-live' / 'gpu-admitted.json'
            experiment.native.save_json(marker, {'status': 'spent_before_dispatch'}, exclusive=True)
            with self.assertRaises(FileExistsError): experiment.native.save_json(marker, {}, exclusive=True)
            self.assertEqual(old.read_text(), 'historical')
        failure = experiment.safe_failure(RuntimeError('Bearer private-key https://private CUDA13 protocol'), 'server_startup')
        self.assertNotIn('private', json.dumps(failure)); self.assertIn('unsupported_runtime', failure['reason_hints'])

    def test_cleanup_escalates_to_kill_and_requires_observed_process_exit(self):
        process = Mock(); process.pid = 4321
        process.poll.side_effect = [None, 0]
        process.wait.side_effect = [experiment.subprocess.TimeoutExpired('native', 8), 0]
        with patch.object(experiment.os, 'killpg', create=True) as kill:
            self.assertTrue(experiment.stop_server(process))
        self.assertEqual([call.args[1] for call in kill.call_args_list], [experiment.signal.SIGTERM, experiment.KILL_SIGNAL])

    def artifacts(self):
        audio = experiment.wav_from_pcm(b'\x10\x00' * 960)
        report = {**experiment.plan(), 'status': 'completed', 'server_exit_observed': True, 'samples': []}
        for sample in experiment.FIXTURES:
            report['samples'].append({**completed_evidence().result(), 'id': sample['id'], 'locale': sample['locale'],
                'input_sha256': sample['sha256'], 'audio': experiment.native.audio_profile(audio), 'audible_playback_verified': False})
        return {'es.wav': audio, 'pt.wav': audio, 'report.json': json.dumps(report).encode()}


if __name__ == '__main__': unittest.main()
