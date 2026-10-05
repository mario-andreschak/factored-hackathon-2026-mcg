"""Local HTTP/WS and cleanup checks; never create a provider job."""
import asyncio
import contextlib
import http.server
import io
import json
import socket
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import urllib.error
import urllib.request

import modal_transport_probe as probe


def fixture_sdk():
    sandbox = SimpleNamespace(_is_v2=False,
        wait_until_ready=SimpleNamespace(aio=AsyncMock()),
        create_connect_token=SimpleNamespace(aio=AsyncMock(return_value=SimpleNamespace(
            url='https://fixture.modal.host', token='private-token-sentinel'))),
        terminate=SimpleNamespace(aio=AsyncMock()))
    sdk = SimpleNamespace(Sandbox=SimpleNamespace(create=SimpleNamespace(aio=AsyncMock(return_value=sandbox))),
                          Probe=SimpleNamespace(with_exec=Mock(return_value='fixed-probe')))
    return sdk, sandbox


class ProbeTests(unittest.TestCase):
    def test_default_plan_does_not_import_sdk_or_read_operator_files(self):
        with patch.dict('sys.modules', {'modal': None}), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(probe.main([]), 0)
        value = json.loads(output.getvalue())
        self.assertFalse(value['gpu']); self.assertEqual(value['sandbox_lifetime_seconds'], 30)
        self.assertFalse(value['model_download']); self.assertFalse(value['automatic_retry'])
        self.assertLess(value['maximum_sandbox_runtime_estimate_usd'], .001)

    def test_authenticated_fixed_http_and_real_websocket_echo_on_local_provider_fixture(self):
        epoch = 'x' * 43; token = 'private-fixture-token'
        class ProviderFixture(probe.handler_for(epoch)):
            def do_GET(self):
                if self.headers.get('Authorization') == 'Bearer ' + token:
                    self.headers['X-Verified-User-Data'] = json.dumps({'leaseEpoch': epoch})
                super().do_GET()
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), ProviderFixture)
        server.daemon_threads = True; server.admitted = False; server.admission_lock = threading.Lock()
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        address = ('127.0.0.1', server.server_port)
        try:
            with self.assertRaises(urllib.error.HTTPError) as result:
                urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/healthz', timeout=2)
            self.assertEqual(result.exception.code, 403)
            request = urllib.request.Request(f'http://127.0.0.1:{server.server_port}/healthz',
                                             headers={'Authorization': 'Bearer ' + token})
            with urllib.request.urlopen(request, timeout=2) as response:
                self.assertEqual(json.loads(response.read()), probe.HEALTH)
            factory = lambda _host: socket.create_connection(address, timeout=2)
            self.assertTrue(probe.probe_ws('https://fixture.modal.host', token, connection_factory=factory))
            self.assertFalse(probe.probe_ws('https://fixture.modal.host', token, connection_factory=factory))
        finally: server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_one_cpu_job_fixed_metadata_and_always_termination_without_credentials_in_report(self):
        async def run():
            sdk, sandbox = fixture_sdk(); http = Mock(return_value=True); websocket = Mock(return_value=True)
            report = await probe.run_probe(sdk, 'app', 'small-python-image', http_check=http, ws_check=websocket)
            self.assertEqual(report['status'], 'completed'); self.assertTrue(report['httpVerified'])
            self.assertTrue(report['websocketVerified']); self.assertTrue(report['terminationConfirmed'])
            self.assertFalse(report['backendV2'])
            args, kwargs = sdk.Sandbox.create.aio.call_args
            self.assertEqual(args, ('python', '/root/modal_transport_probe.py', '--worker'))
            self.assertNotIn('gpu', kwargs); self.assertNotIn('secrets', kwargs)
            self.assertEqual(kwargs['timeout'], 30); self.assertTrue(kwargs['block_network'])
            self.assertEqual(kwargs['encrypted_ports'], []); self.assertEqual(kwargs['unencrypted_ports'], [])
            metadata = sandbox.create_connect_token.aio.call_args.kwargs['user_metadata']
            self.assertEqual(metadata, {'leaseEpoch': kwargs['env']['MODAL_PROBE_EPOCH']})
            sandbox.terminate.aio.assert_awaited_once_with(wait=True)
            sdk.Sandbox.create.aio.assert_awaited_once()
            self.assertNotIn('private-token', json.dumps(report)); self.assertNotIn('modal.host', json.dumps(report))
        asyncio.run(run())

    def test_connect_token_api_failure_exposes_only_status_enum_and_terminates_once(self):
        GRPCError = type('GRPCError', (Exception,), {})
        error = GRPCError('private-token https://provider.example/error')
        error.status = SimpleNamespace(name='FAILED_PRECONDITION')
        async def run():
            sdk, sandbox = fixture_sdk(); sandbox.create_connect_token.aio.side_effect = error
            report = await probe.run_probe(sdk, 'app', 'image', http_check=Mock(), ws_check=Mock())
            self.assertEqual(report['stage'], 'connect_token')
            self.assertEqual(report['grpc_status'], 'FAILED_PRECONDITION')
            self.assertEqual(report['failure_code'], 'modal_precondition_failed')
            self.assertTrue(report['terminationConfirmed'])
            self.assertFalse(report['httpVerified']); self.assertFalse(report['websocketVerified'])
            self.assertNotIn('private', json.dumps(report)); self.assertNotIn('provider', json.dumps(report))
            sandbox.terminate.aio.assert_awaited_once_with(wait=True)
        asyncio.run(run())

    def test_actual_echo_failure_cannot_claim_transport_acceptance(self):
        async def run():
            sdk, sandbox = fixture_sdk()
            report = await probe.run_probe(sdk, 'app', 'image', http_check=lambda *_: True, ws_check=lambda *_: False)
            self.assertEqual(report['status'], 'failed')
            self.assertEqual(report['stage'], 'authenticated_websocket')
            self.assertTrue(report['httpVerified']); self.assertFalse(report['websocketVerified'])
            self.assertTrue(report['terminationConfirmed'])
        asyncio.run(run())

    def test_alternative_network_policy_is_only_fixed_loopback_without_block_network(self):
        async def run():
            sdk, sandbox = fixture_sdk()
            report = await probe.run_probe(sdk, 'app', 'image', policy='loopback-only',
                                           http_check=lambda *_: True, ws_check=lambda *_: True)
            kwargs = sdk.Sandbox.create.aio.call_args.kwargs
            self.assertEqual(kwargs['outbound_cidr_allowlist'], ['127.0.0.0/8'])
            self.assertNotIn('block_network', kwargs)
            self.assertEqual(report['egressPolicy'], 'loopback-only')
            sdk, _ = fixture_sdk()
            with self.assertRaises(ValueError): await probe.run_probe(sdk, 'app', 'image', policy='unrestricted')
            sdk.Sandbox.create.aio.assert_not_awaited()
        asyncio.run(run())

    def test_malformed_masked_frames_are_rejected_before_echo(self):
        for value in (b'\x01\x80\x00\x00\x00\x00', b'\x81\x00', b'\x81\xff'):
            with self.assertRaises(ValueError): probe.receive_frame(io.BytesIO(value), masked=True)


if __name__ == '__main__': unittest.main()
