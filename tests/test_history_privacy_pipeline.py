"""Integration boundaries for Slack cache purging and local screened assets."""
import base64
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_dev_history as builder
from history_sources import media


CAPTURE = '2026-10-01T04:00:00Z'
PNG = b'\x89PNG\r\n\x1a\n' + b'fixture-raster-payload'


def slack_event(identity, channel_id, name, body, **metadata):
    return {'id': identity, 'source': 'slack', 'timestamp': '2026-10-01T03:00:00Z',
            'threadId': channel_id + ':1790823600.000001', 'actor': 'Gloria Yantas',
            'body': body, 'title': body, 'tags': [name],
            'metadata': {'channelId': channel_id, 'channel': name, **metadata}}


def mixed_snapshot():
    channels = [
        {'id': 'DPRIVATE', 'name': 'DM with Gloria', 'user': 'U123'},
        {'id': 'GPRIVATE', 'name': 'Private group', 'is_mpim': True},
        {'id': 'CFIND', 'name': 'find-a-team'}, {'id': 'CHELP', 'name': 'challenge-help'},
        {'id': 'CTECH', 'name': 'technical-help'},
        {'id': 'CTEAM', 'name': 'equipo-mario-gloria', 'channelType': 'private_channel'},
    ]
    events = [slack_event('event-' + channel['id'], channel['id'], channel['name'], 'EXCLUDED CONTENT ' + channel['id'],
                          **{'is_mpim': True} if channel.get('is_mpim') else {}) for channel in channels[:-1]]
    events.append(slack_event('included', 'CTEAM', 'equipo-mario-gloria',
                             'Mario and Gloria: gloria@example.test; WhatsApp +57 300 123 4567',
                             channelType='private_channel', threadId='technical-thread-id', messageTs='1790823600.000001'))
    return {'events': events, 'channels': channels, 'notes': [], 'status': 'ok', 'stats': {'messages': len(events), 'channels': len(channels)}}


class PrivacyPipelineTests(unittest.TestCase):
    def cache(self, root, result=None):
        cache = root / 'cache'
        builder.atomic_json(cache / 'slack.json', {'collectedAt': CAPTURE, 'result': result or mixed_snapshot()})
        return cache

    def assert_only_permitted_and_redacted(self, result):
        self.assertEqual([event['id'] for event in result['events']], ['included'])
        self.assertEqual([channel['id'] for channel in result['channels']], ['CTEAM'])
        event = result['events'][0]
        self.assertEqual(event['actor'], 'Gloria Yantas')
        self.assertIn('Mario and Gloria', event['body'])
        self.assertEqual(event['metadata']['messageTs'], '1790823600.000001')
        self.assertNotIn('gloria@example.test', json.dumps(result))
        self.assertNotIn('+57 300 123 4567', json.dumps(result))
        self.assertNotIn('EXCLUDED CONTENT', json.dumps(result))
        self.assertEqual(result['stats']['messages'], 1)
        self.assertEqual(result['stats']['channels'], 1)

    def test_private_result_and_offline_cache_purge_keep_original_capture_and_team_names(self):
        direct = builder.private_result('slack', mixed_snapshot(), {})
        self.assert_only_permitted_and_redacted(direct)
        self.assertEqual(direct['stats']['privacyExcludedEvents'], 5)
        with tempfile.TemporaryDirectory() as directory:
            cache = self.cache(Path(directory))
            file = cache / 'slack.json'
            with patch.object(builder.importlib, 'import_module', side_effect=AssertionError('Offline cache must not access a live source')):
                result = builder.source_result('slack', {}, cache, True)
            self.assert_only_permitted_and_redacted(result)
            self.assertEqual(result['cachedAt'], CAPTURE)
            persisted = json.loads(file.read_text(encoding='utf-8'))
            self.assertEqual(persisted['collectedAt'], CAPTURE)
            self.assert_only_permitted_and_redacted(persisted['result'])
            clean_bytes = file.read_bytes()
            # Privacy filtering is idempotent; repeated offline reads neither
            # increase exclusion counts nor turn redaction into a new capture.
            reread = builder.read_private_cache(file, 'slack', {})
            self.assertEqual(reread['result']['stats']['privacyExcludedEvents'], 5)
            self.assertEqual(file.read_bytes(), clean_bytes)

    def test_live_failure_purges_old_private_content_without_new_observation(self):
        fake = SimpleNamespace(collect=lambda *_: {'events': [], 'status': 'unavailable', 'notes': ['Connector unavailable']})
        with tempfile.TemporaryDirectory() as directory:
            cache = self.cache(Path(directory))
            with patch.object(builder.importlib, 'import_module', return_value=fake):
                result = builder.source_result('slack', {}, cache, False)
            self.assert_only_permitted_and_redacted(result)
            self.assertEqual(result['status'], 'partial')
            self.assertEqual(result['cachedAt'], CAPTURE)
            persisted = json.loads((cache / 'slack.json').read_text(encoding='utf-8'))
            self.assertEqual(persisted['collectedAt'], CAPTURE)
            self.assert_only_permitted_and_redacted(persisted['result'])

    def test_retention_cannot_resurrect_excluded_channels_from_old_or_new_results(self):
        fresh = {'events': [slack_event('fresh-team', 'CTEAM', 'equipo-mario-gloria', 'New team work'),
                            slack_event('fresh-dm', 'DNEW', 'DM with Mario', 'NEW PRIVATE CONTENT'),
                            slack_event('fresh-help', 'CNEW', 'technical-help', 'NEW EXCLUDED CONTENT')],
                 'status': 'ok', 'notes': []}
        fake = SimpleNamespace(collect=lambda *_: copy.deepcopy(fresh))
        with tempfile.TemporaryDirectory() as directory:
            cache = self.cache(Path(directory))
            with patch.object(builder.importlib, 'import_module', return_value=fake):
                result = builder.source_result('slack', {}, cache, False)
            self.assertEqual(set(event['id'] for event in result['events']), {'included', 'fresh-team'})
            retained = next(event for event in result['events'] if event['id'] == 'included')
            self.assertTrue(retained['metadata']['retainedFromPriorCapture'])
            self.assertEqual(retained['metadata']['lastCapturedAt'], CAPTURE)
            self.assertEqual(result['stats']['retainedEvents'], 1)
            persisted = (cache / 'slack.json').read_text(encoding='utf-8')
            for forbidden in ('PRIVATE CONTENT', 'EXCLUDED CONTENT', 'gloria@example.test', '+57 300 123 4567'):
                self.assertNotIn(forbidden, persisted)

    def image_result(self, *identities, **file_metadata):
        return {'events': [{'id': 'team-message', 'metadata': {'files': [
            {'id': identity, 'name': 'Screenshot', 'mimeType': 'image/png', 'isImage': True, **file_metadata} for identity in identities],
            'reactions': [{'name': 'eyes', 'count': 2}]}}], 'notes': [], 'stats': {}}

    def test_media_exports_only_screened_pixels_and_removes_unused_generated_assets(self):
        calls = []
        class FakeClient:
            def __init__(self, *_):
                pass
            def call(self, tool, arguments):
                calls.append((tool, arguments))
                return {'content': [{'type': 'image', 'mimeType': 'image/png', 'data': base64.b64encode(PNG).decode()}]}
        clean_pixels = PNG + b'-metadata-stripped'
        screened = [(clean_pixels, {'status': 'available', 'width': 64, 'height': 48, 'mimeType': 'image/png', 'privacyScreen': media.POLICY}),
                    (None, {'status': 'withheld', 'reason': 'Contact details found; original pixels withheld.'})]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output, cache = root / 'output', root / 'cache'
            assets = output / 'media'
            assets.mkdir(parents=True)
            stale = assets / 'slack-FSTALE-0123456789abcdef.png'
            stale.write_bytes(b'old-generated-pixels')
            unrelated = assets / 'user-owned.png'
            unrelated.write_bytes(b'unrelated-file')
            result = self.image_result('FSAFE', 'FPRIVATE', thumbnailUrl='https://files.slack.com/private')
            with patch.object(media, 'configured_endpoint', return_value=('http://local-read-only-mcp', {})), patch.object(media, 'Client', FakeClient), patch.object(media, 'screen_image', side_effect=screened):
                exported = media.collect_assets(result, output, cache, {}, False)
            safe, withheld = exported['events'][0]['metadata']['images']
            self.assertEqual(safe['status'], 'available')
            self.assertEqual((assets / safe['assetName']).read_bytes(), clean_pixels)
            self.assertEqual(safe['src'], 'data/media/' + safe['assetName'])
            self.assertEqual(withheld['status'], 'withheld')
            self.assertNotIn('src', withheld)
            self.assertNotIn('assetName', withheld)
            self.assertFalse(stale.exists())
            self.assertEqual(unrelated.read_bytes(), b'unrelated-file')
            self.assertEqual(list(assets.glob('slack-FPRIVATE-*.png')), [])
            self.assertEqual(exported['stats']['images'], {'available': 1, 'withheld': 1, 'unavailable': 0})
            self.assertEqual(calls, [('slack_read_file', {'file_id': 'FSAFE'}), ('slack_read_file', {'file_id': 'FPRIVATE'})])
            manifest = (cache / 'slack-media.json').read_text(encoding='utf-8')
            self.assertNotIn(base64.b64encode(PNG).decode(), manifest)
            self.assertNotIn('thumbnailUrl', json.dumps(exported))

    def test_offline_missing_media_fails_closed_without_mcp_or_ocr(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.image_result('FMISSING')
            with patch.object(media, 'configured_endpoint', side_effect=AssertionError('No network offline')), patch.object(media, 'screen_image', side_effect=AssertionError('No OCR offline')):
                exported = media.collect_assets(result, root / 'output', root / 'cache', {}, True)
            image = exported['events'][0]['metadata']['images'][0]
            self.assertEqual(image['status'], 'unavailable')
            self.assertNotIn('src', image)
            self.assertEqual(list((root / 'output/media').glob('*.png')), [])
            self.assertEqual(exported['stats']['images']['unavailable'], 1)

    def test_offline_reuses_only_existing_assets_screened_under_current_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output, cache = root / 'output', root / 'cache'
            assets = output / 'media'
            assets.mkdir(parents=True)
            name = 'slack-FSAFE-0123456789abcdef.png'
            (assets / name).write_bytes(PNG)
            builder.atomic_json(cache / 'slack-media.json', {'FSAFE': {'assetName': name, 'src': 'data/media/' + name, 'status': 'available', 'privacyScreen': media.POLICY}})
            with patch.object(media, 'configured_endpoint', side_effect=AssertionError('No network offline')), patch.object(media, 'screen_image', side_effect=AssertionError('Cached screened pixels must not be reprocessed offline')):
                result = media.collect_assets(self.image_result('FSAFE'), output, cache, {}, True)
            image = result['events'][0]['metadata']['images'][0]
            self.assertEqual(image['status'], 'available')
            self.assertEqual(image['src'], 'data/media/' + name)
            self.assertEqual((assets / name).read_bytes(), PNG)
            self.assertEqual(result['stats']['images']['available'], 1)

    def test_ocr_failure_exports_no_pixels_or_private_connector_error_text(self):
        fake = SimpleNamespace(call=lambda *_: {'content': [{'type': 'image', 'mimeType': 'image/png', 'data': base64.b64encode(PNG).decode()}]})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(media, 'configured_endpoint', return_value=('http://local-mcp', {})), patch.object(media, 'Client', return_value=fake), patch.object(media, 'screen_image', side_effect=RuntimeError('PRIVATE email secret@example.test')):
                result = media.collect_assets(self.image_result('FERROR'), root / 'output', root / 'cache', {}, False)
            image = result['events'][0]['metadata']['images'][0]
            self.assertEqual(image['status'], 'unavailable')
            self.assertEqual(image['errorType'], 'RuntimeError')
            self.assertNotIn('secret@example.test', json.dumps(result))
            self.assertEqual(list((root / 'output/media').glob('*.png')), [])

    def test_stale_asset_links_are_cleared_when_pixels_are_withheld_or_offline_unavailable(self):
        for offline in (False, True):
            with self.subTest(offline=offline), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                output, cache = root / 'output', root / 'cache'
                assets = output / 'media'
                assets.mkdir(parents=True)
                name = 'slack-FPRIVATE-0123456789abcdef.png'
                (assets / name).write_bytes(b'previously-exported-pixels')
                builder.atomic_json(cache / 'slack-media.json', {'FPRIVATE': {'assetName': name, 'src': 'data/media/' + name, 'status': 'available', 'privacyScreen': 'older-policy'}})
                result = self.image_result('FPRIVATE', assetName=name, src='data/media/' + name, status='available', privacyScreen='older-policy')
                fake = SimpleNamespace(call=lambda *_: {'content': [{'type': 'image', 'mimeType': 'image/png', 'data': base64.b64encode(PNG).decode()}]})
                with patch.object(media, 'configured_endpoint', return_value=('http://local-mcp', {})), patch.object(media, 'Client', return_value=fake), patch.object(media, 'screen_image', return_value=(None, {'status': 'withheld', 'reason': 'Private contact pixels detected'})):
                    result = media.collect_assets(result, output, cache, {}, offline)
                image = result['events'][0]['metadata']['images'][0]
                self.assertEqual(image['status'], 'unavailable' if offline else 'withheld')
                self.assertFalse((assets / name).exists())
                self.assertNotIn('src', image, 'A withheld/unavailable image must not retain an earlier exported pixel URL')
                self.assertNotIn('assetName', image)


if __name__ == '__main__':
    unittest.main()
