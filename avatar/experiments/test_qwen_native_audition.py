"""Inert local checks for the two-sample native Qwen quality audition."""
import contextlib
import asyncio
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
import wave

import qwen_native_audition as experiment


def wav_bytes(rate=24_000, channels=1, seconds=.05):
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as output:
        output.setnchannels(channels); output.setsampwidth(2); output.setframerate(rate)
        output.writeframes(bytes(int(rate * seconds) * channels * 2))
    return buffer.getvalue()


class QwenNativeTests(unittest.TestCase):
    def test_default_plan_is_inert_and_one_native_gpu_job_is_bounded(self):
        with patch.dict('sys.modules', {'modal': None, 'torch': None, 'huggingface_hub': None}), \
                patch.object(experiment, 'build_app', side_effect=AssertionError('cloud definition')), \
                patch.object(experiment, 'require_cache_receipt', side_effect=AssertionError('cache read')), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(experiment.main([]), 0)
        value = json.loads(output.getvalue())
        self.assertEqual(value['native_generations'], 2)
        self.assertEqual(value['model_loads'], 1)
        self.assertEqual(value['gpu_count'], 1)
        self.assertEqual((value['function_seconds'], value['worker_seconds']), (600, 540))
        self.assertEqual(value['cpu_cache']['timeout_seconds'], 1800)
        self.assertFalse(value['runtime_downloads'])
        self.assertFalse(value['native_duplex_qualified'])
        self.assertEqual(value['locales'], ['es-CO', 'pt-BR'])

    def test_exact_public_cases_use_native_talker_with_small_generation_bounds(self):
        self.assertEqual(len(experiment.CASES), 2)
        for sample in experiment.CASES:
            messages = experiment.messages(sample)
            self.assertEqual(messages[-1]['content'][0]['text'], sample['text'])
        with self.assertRaises(ValueError):
            experiment.messages({'id': 'es', 'text': 'unapproved user input'})
        options = experiment.generation_options()
        self.assertTrue(options['return_audio'])
        self.assertEqual(options['speaker'], 'Chelsie')
        self.assertEqual((options['thinker_max_new_tokens'], options['talker_max_new_tokens']), (128, 384))

    def test_pinned_shards_and_checksums_reject_partial_or_changed_cache(self):
        manifest = experiment.assets()
        self.assertEqual(len([name for name in manifest if name.endswith('.safetensors')]), 15)
        self.assertGreaterEqual(sum(size for size, _ in manifest.values()), experiment.WEIGHT_BYTES)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'config.json').write_bytes(b'public')
            small = {'config.json': [6, experiment.digest(b'public')]}
            self.assertEqual(experiment.verify_assets(root, small)['files'], 1)
            (root / 'config.json').write_bytes(b'edited')
            with self.assertRaises(ValueError): experiment.verify_assets(root, small)
            (root / 'config.json').unlink()
            with self.assertRaises(ValueError): experiment.verify_assets(root, small)

    def test_audio_header_rate_and_duration_are_validated_instead_of_assumed(self):
        self.assertEqual(experiment.audio_profile(wav_bytes())['sample_rate'], 24_000)
        for value in (wav_bytes(16_000), wav_bytes(channels=2), wav_bytes(seconds=32), b'raw pcm'):
            with self.assertRaises((ValueError, wave.Error, EOFError)):
                experiment.audio_profile(value)

    def test_exact_cpu_cache_receipt_is_required_before_any_gpu_definition(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / 'cache.json'
            with patch.object(experiment, 'CACHE_RECEIPT', receipt):
                with self.assertRaises(ValueError): experiment.require_cache_receipt()
                manifest = experiment.assets()
                value = {'status': 'cache_verified', 'model_revision': experiment.MODEL_REVISION,
                    'volume': experiment.VOLUME_NAME, 'files': len(manifest),
                    'bytes': sum(v[0] for v in manifest.values()),
                    'manifest_sha256': experiment.digest(json.dumps(manifest, sort_keys=True).encode('utf8'))}
                receipt.write_text(json.dumps(value))
                self.assertEqual(experiment.require_cache_receipt(), value)
                value['model_revision'] = 'wrong pin'; receipt.write_text(json.dumps(value))
                with self.assertRaises(ValueError): experiment.require_cache_receipt()

    def test_failure_receipt_never_serializes_raw_exception_or_provider_body(self):
        error = RuntimeError('private-url Bearer private-value out of memory')
        value = experiment.safe_failure(error, 'native_generation')
        self.assertEqual(value['code'], 'gpu_memory_exhausted')
        self.assertNotIn('private', json.dumps(value))

    def test_committed_output_is_tiny_allowlisted_receipt_without_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            commit = Mock()
            value = experiment.persist_artifacts('delivery-preflight',
                {'delivery-fixture.bin': experiment.DELIVERY_FIXTURE}, commit, Path(directory))
            commit.assert_called_once()
            self.assertLess(len(json.dumps(value)), 4096)
            self.assertEqual((Path(directory) / value['run_id'] / 'delivery-fixture.bin').read_bytes(), experiment.DELIVERY_FIXTURE)
            self.assertNotIn('artifacts', value)
            for bad in ('../another-run', '/absolute', 'https://unapproved'):
                with self.assertRaises(ValueError): experiment.validate_delivery({**value, 'run_id': bad})
            changed = {**value, 'files': {'arbitrary.txt': value['files']['delivery-fixture.bin']}}
            with self.assertRaises(ValueError): experiment.validate_delivery(changed)

    def test_bounded_local_read_rejects_partial_changed_and_oversized_chunks(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = experiment.persist_artifacts('delivery-preflight',
                {'delivery-fixture.bin': experiment.DELIVERY_FIXTURE}, lambda: None, Path(directory))
            def volume_for(chunks):
                async def read(path):
                    self.assertEqual(path, receipt['run_id'] + '/delivery-fixture.bin')
                    for block in chunks: yield block
                return SimpleNamespace(read_file=SimpleNamespace(aio=read))
            chunks = [experiment.DELIVERY_FIXTURE[:100], experiment.DELIVERY_FIXTURE[100:]]
            self.assertEqual(asyncio.run(experiment.download_artifacts(receipt, volume_for(chunks))),
                {'delivery-fixture.bin': experiment.DELIVERY_FIXTURE})
            for chunks in ([b'partial'], [b'x' * len(experiment.DELIVERY_FIXTURE)], [experiment.DELIVERY_FIXTURE, b'extra']):
                with self.assertRaises(ValueError): asyncio.run(experiment.download_artifacts(receipt, volume_for(chunks)))

    def test_old_admission_is_preserved_and_delivery_fix_has_no_automatic_repeat(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); first = root / 'gpu-admitted.json'; original = {'status': 'spent_before_dispatch'}
            experiment.save_json(first, original, exclusive=True)
            corrected = root / 'gpu-delivery-fix-admitted.json'
            experiment.save_json(corrected, original, exclusive=True)
            with self.assertRaises(FileExistsError): experiment.save_json(corrected, original, exclusive=True)
            self.assertEqual(json.loads(first.read_text()), original)
            with patch.object(experiment, 'build_app', side_effect=AssertionError('cloud dispatch')), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(experiment.main(['--execute']), 1)


if __name__ == '__main__':
    unittest.main()
