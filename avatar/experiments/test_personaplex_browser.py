"""Local cache, Sandbox lifecycle and credential-projection checks. No cloud calls."""
import asyncio
import contextlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import personaplex_browser as browser
import personaplex_cache as cache
from personaplex_modal import MODEL_FILES, MODEL_REVISION, SOURCE_REVISION, VOICE


def fake_sdk():
    sandbox = SimpleNamespace(
        object_id='sb-fixture-only', wait_until_ready=SimpleNamespace(aio=AsyncMock()),
        create_connect_token=SimpleNamespace(aio=AsyncMock(return_value=SimpleNamespace(
            url='https://fixture.modal.host', token='private-connect-sentinel'))),
        poll=SimpleNamespace(aio=AsyncMock(return_value=0)), terminate=SimpleNamespace(aio=AsyncMock(return_value=137)),
    )
    sdk = SimpleNamespace(Sandbox=SimpleNamespace(create=SimpleNamespace(aio=AsyncMock(return_value=sandbox))),
                          Probe=SimpleNamespace(with_exec=Mock(return_value='fixed-ready-probe')))
    async def stop(**_options):
        sandbox.poll.aio.side_effect = None
        sandbox.poll.aio.return_value = 137
    sandbox.terminate.aio.side_effect = stop
    return sdk, sandbox


def staged_health(phase='warm', avatar=None, selection_id=None):
    return {'ready': phase in ('primed', 'streaming'), 'protocol': browser.PROTOCOL,
        'avatar': avatar, 'sourceRevision': SOURCE_REVISION, 'modelRevision': MODEL_REVISION,
        'selection': 'initial', 'phase': phase, 'voice': 'NATM1.pt',
        'promptHash': browser.production_prompt_hashes()[avatar] if phase in ('primed', 'streaming') else None,
        'selectionId': selection_id}


class BrowserTests(unittest.TestCase):
    def test_explicit_initial_plan_is_inert_and_never_calls_warm_weights_native_ready(self):
        with patch.object(browser, 'existing_token', side_effect=AssertionError('credential read')), \
                patch.object(browser, 'cache_reference', side_effect=AssertionError('private cache read')), \
                patch.dict('sys.modules', {'modal': None, 'torch': None}), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(browser.main(['--initial-role']), 0)
        value = json.loads(output.getvalue())
        self.assertEqual(value['selection'], 'initial'); self.assertEqual(value['lease_version'], 2)
        self.assertEqual(value['probe_marker'], '/tmp/personaplex-warm'); self.assertFalse(value['warm_is_voice_ready'])
        self.assertEqual(value['sandbox_lifetime_seconds'], 600); self.assertEqual(value['readiness_timeout_seconds'], 240)
        self.assertEqual(set(value['production_prompt_hashes']), {'moss', 'orbit', 'spark'})
        self.assertNotIn('selection', browser.plan())

    def test_staged_health_rejects_false_readiness_voice_hash_and_unbounded_selection(self):
        for value in (staged_health(), staged_health('priming', 'orbit', 'owned-selection'),
                      staged_health('primed', 'orbit', 'owned-selection'), staged_health('streaming', 'orbit', 'owned-selection'),
                      {**staged_health('primed', 'orbit', 'owned-selection'), 'ready':False},
                      {**staged_health('primed', 'orbit', 'owned-selection'), 'phase':'closed', 'ready':False}):
            self.assertEqual(browser.validate_staged_health(value), value)
        wrong = [
            {**staged_health(), 'ready':True}, {**staged_health(), 'ready':0},
            {**staged_health(), 'selection':'adaptive'}, {**staged_health(), 'voice':'another.pt'},
            {**staged_health(), 'avatar':'moss'}, {**staged_health(), 'phase':'new'},
            {**staged_health('primed', 'orbit', 'owned-selection'), 'promptHash':'f'*64},
            {**staged_health('priming', 'orbit', 'owned-selection'), 'promptHash':browser.production_prompt_hashes()['orbit']},
            {**staged_health('priming', 'orbit', 'owned-selection'), 'selectionId':'x'*129},
            {**staged_health(), 'providerMessage':'private-sentinel'},
        ]
        for value in wrong:
            with self.subTest(value=value), self.assertRaises(ValueError): browser.validate_staged_health(value)

    def test_staged_progress_skips_polls_but_never_rebinds_or_rewinds_an_initial_selection(self):
        warm = browser.transition_staged_health(None, staged_health())
        primed = browser.transition_staged_health(warm, staged_health('primed', 'spark', 'owned'))
        streaming = browser.transition_staged_health(primed, staged_health('streaming', 'spark', 'owned'))
        closed = {**streaming, 'ready':False, 'phase':'closed'}
        self.assertEqual(browser.transition_staged_health(streaming, closed), closed)
        for old, value in ((None, primed), (primed, warm),
                           (primed, staged_health('primed', 'orbit', 'owned')),
                           (primed, staged_health('primed', 'spark', 'foreign')),
                           (closed, streaming)):
            with self.assertRaises(ValueError): browser.transition_staged_health(old, value)

    def test_actual_worker_state_health_projects_through_launcher_without_phase_or_hash_translation(self):
        import personaplex_pcm_server as worker
        with patch.object(worker.time,'monotonic',return_value=100):
            state=worker.WorkerState(worker.Settings('moss','NATM1.pt','owned_epoch_for_local_state_only',600,initial_mode=True),started=100)
            state.mark_warm(); proof=browser.transition_staged_health(None,state.health())
            self.assertTrue(state.reserve_prime('one_opaque_selection','spark'))
            proof=browser.transition_staged_health(proof,state.health())
            state.publish_prime(); proof=browser.transition_staged_health(proof,state.health())
            self.assertTrue(state.admit()); proof=browser.transition_staged_health(proof,state.health())
            self.assertEqual(proof['phase'],'streaming'); self.assertEqual(proof['promptHash'],browser.production_prompt_hashes()['spark'])
            state.close(); proof=browser.transition_staged_health(proof,state.health())
            self.assertEqual(proof['phase'],'closed'); self.assertFalse(proof['ready'])

    def test_staged_launcher_publishes_private_warm_then_immutable_primed_tuple_with_no_prime_call(self):
        async def run():
            with tempfile.TemporaryDirectory() as directory:
                lease = Path(directory)/'lease.json'; sdk, sandbox = fake_sdk()
                sandbox.poll.aio.side_effect = [None, None, None, 0]
                reader = Mock(side_effect=[staged_health(), staged_health('priming', 'orbit', 'opaque-selection'),
                    staged_health('primed', 'orbit', 'opaque-selection'), staged_health('streaming', 'orbit', 'opaque-selection')])
                snapshots = []; actual_write = browser.private_write
                def record(path, value, **options):
                    if Path(path) == lease: snapshots.append(dict(value))
                    return actual_write(path, value, **options)
                with patch.object(browser, 'private_write', side_effect=record), \
                        patch.object(browser, 'worker_ready', side_effect=AssertionError('fixed health route')), \
                        contextlib.redirect_stdout(io.StringIO()) as output:
                    result = await browser.run_sandbox(sdk, 'app', 'cached', 'moss', lease, initial_role=True,
                        staged_health=reader, sleep=AsyncMock(), clock=lambda:1_790_848_800, monotonic=lambda:0)
                self.assertEqual([value['phase'] for value in snapshots], ['warm', 'priming', 'primed', 'streaming'])
                self.assertEqual([value['ready'] for value in snapshots], [False, False, True, True])
                self.assertTrue(all(value['version']==2 and value['voice']=='NATM1.pt' for value in snapshots))
                for key in ('epoch', 'connectToken', 'baseUrl', 'createdAt', 'expiresAt'):
                    self.assertEqual(len({value[key] for value in snapshots}), 1)
                self.assertIsNone(snapshots[0]['avatar']); self.assertIsNone(snapshots[0]['promptHash'])
                self.assertEqual(snapshots[2]['promptHash'], browser.production_prompt_hashes()['orbit'])
                self.assertEqual(sdk.Sandbox.create.aio.call_args.kwargs['env']['PERSONAPLEX_INITIAL_MODE'], '1')
                sdk.Probe.with_exec.assert_called_once_with('test', '-f', '/tmp/personaplex-warm', interval_ms=500)
                sandbox.wait_until_ready.aio.assert_awaited_once_with(timeout=240)
                self.assertEqual(sdk.Sandbox.create.aio.call_args.kwargs['timeout'], 600)
                sdk.Sandbox.create.aio.assert_awaited_once(); sandbox.terminate.aio.assert_awaited_once_with(wait=False)
                self.assertEqual(json.loads(output.getvalue())['status'], 'warm')
                self.assertFalse(json.loads(output.getvalue())['nativeReady'])
                self.assertNotIn('private-connect-sentinel', output.getvalue()); self.assertNotIn('opaque-selection', output.getvalue())
                self.assertEqual(result['lastPhase'], 'streaming'); self.assertTrue(result['initialRolePrimed'])
                self.assertTrue(result['terminationConfirmed']); self.assertFalse(result['nativeBrowserAcceptanceVerified'])
                self.assertFalse(lease.exists()); self.assertFalse(lease.with_name('launch.lock').exists())
        asyncio.run(run())

    def test_unadmitted_primed_capacity_expiry_is_unavailable_without_claiming_metadata_corruption(self):
        async def run():
            with tempfile.TemporaryDirectory() as directory:
                lease=Path(directory)/'lease.json'; sdk, sandbox=fake_sdk()
                sandbox.poll.aio.side_effect=[None,0]
                value={**staged_health('primed','orbit','owned'),'ready':False}
                reader=Mock(side_effect=[staged_health(),value])
                with contextlib.redirect_stdout(io.StringIO()):
                    report=await browser.run_sandbox(sdk,'app','image','moss',lease,initial_role=True,
                        staged_health=reader,sleep=AsyncMock())
                self.assertEqual(report['lastPhase'],'primed'); self.assertTrue(report['initialRolePrimed'])
                self.assertNotIn('failure_code',report); self.assertTrue(report['terminationConfirmed'])
                self.assertFalse(report['nativeBrowserAcceptanceVerified']); self.assertFalse(lease.exists())
        asyncio.run(run())

    def test_staged_health_conflict_revokes_lease_and_terminates_one_existing_worker(self):
        async def run():
            with tempfile.TemporaryDirectory() as directory:
                lease=Path(directory)/'lease.json'; sdk, sandbox=fake_sdk()
                sandbox.poll.aio.return_value=None
                reader=Mock(side_effect=[staged_health(), staged_health('primed', 'orbit', 'owned'),
                    staged_health('primed', 'spark', 'owned')])
                with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
                    await browser.run_sandbox(sdk, 'app', 'image', 'moss', lease, initial_role=True,
                        staged_health=reader, sleep=AsyncMock())
                sdk.Sandbox.create.aio.assert_awaited_once(); sandbox.terminate.aio.assert_awaited_once_with(wait=False)
                self.assertFalse(lease.exists()); self.assertFalse(lease.with_name('launch.lock').exists())
                report=browser.read_small_json(lease.with_name('last-run.json'))
                self.assertTrue(report['terminationConfirmed']); self.assertEqual(report['error_class'], 'ValueError')
        asyncio.run(run())

    def test_staged_optin_rejects_legacy_health_before_publishing_any_warm_lease(self):
        async def run():
            with tempfile.TemporaryDirectory() as directory:
                lease=Path(directory)/'lease.json'; sdk, sandbox=fake_sdk()
                legacy={'ready':True,'protocol':browser.PROTOCOL,'avatar':'moss',
                    'sourceRevision':SOURCE_REVISION,'modelRevision':MODEL_REVISION}
                with self.assertRaises(ValueError):
                    await browser.run_sandbox(sdk, 'app', 'image', 'moss', lease, initial_role=True,
                        staged_health=Mock(return_value=legacy), sleep=AsyncMock())
                self.assertFalse(lease.exists()); sandbox.terminate.aio.assert_awaited_once_with(wait=False)
        asyncio.run(run())

    def test_staged_health_fetch_is_private_bounded_nonredirecting_and_does_not_prime(self):
        response=Mock(status=200); response.read.return_value=json.dumps(staged_health()).encode()
        opener=Mock(); opener.open.return_value=contextlib.nullcontext(response)
        with patch.object(browser.urllib.request, 'build_opener', return_value=opener):
            self.assertEqual(browser.worker_staged_health('https://fixture.modal.host', 'private-sentinel'), staged_health())
        request=opener.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://fixture.modal.host/healthz')
        self.assertEqual(request.get_method(), 'GET'); self.assertEqual(request.get_header('Authorization'), 'Bearer private-sentinel')
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 3); response.read.assert_called_once_with(4097)
        response.read.return_value=b'x'*4097
        with patch.object(browser.urllib.request, 'build_opener', return_value=opener):
            self.assertIsNone(browser.worker_staged_health('https://fixture.modal.host', 'private-sentinel'))

    def test_staged_warm_timeout_cleanup_never_claims_a_primed_conversation(self):
        async def run():
            with tempfile.TemporaryDirectory() as directory:
                lease=Path(directory)/'lease.json'; sdk, sandbox=fake_sdk()
                elapsed=[0]
                async def pause(_seconds): elapsed[0]+=601
                with contextlib.redirect_stdout(io.StringIO()):
                    report=await browser.run_sandbox(sdk,'app','image','moss',lease,initial_role=True,
                        staged_health=Mock(return_value=staged_health()),sleep=pause,monotonic=lambda:elapsed[0])
                self.assertEqual(report['selection'], 'initial'); self.assertEqual(report['lastPhase'], 'warm')
                self.assertFalse(report['initialRolePrimed']); self.assertFalse(report['nativeBrowserAcceptanceVerified'])
                self.assertEqual(report['providerLifetimeSeconds'],600); self.assertTrue(report['terminationConfirmed'])
                self.assertFalse(lease.exists()); sdk.Sandbox.create.aio.assert_awaited_once()
        asyncio.run(run())

    def test_cli_initial_role_is_explicit_and_rejects_fixed_avatar_or_cache_build_flags_before_access(self):
        app=Mock(); app.run.aio.return_value=contextlib.nullcontext()
        sdk=SimpleNamespace(App=Mock(return_value=app),Image=SimpleNamespace(from_id=Mock(return_value='image')))
        runner=AsyncMock(return_value={'endReason':'worker_exited','terminationConfirmed':True})
        with patch.dict('sys.modules',{'modal':sdk}), patch.object(browser,'cache_reference',return_value='im-fixture'), \
                patch.object(browser,'existing_token',side_effect=AssertionError('HF credential read')), \
                patch.object(browser,'run_sandbox',runner), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(browser.main(['--execute','--initial-role']),0)
        self.assertTrue(runner.call_args.kwargs['initial_role']); runner.assert_awaited_once()
        for flags in (['--initial-role','--build-cache'],['--initial-role','--avatar','spark']):
            with patch.object(browser,'cache_reference',side_effect=AssertionError('private cache read')), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit): browser.main(flags)

    def test_launcher_and_worker_startup_bounds_match_without_retry_or_lifetime_extension(self):
        import personaplex_pcm_server as worker

        value = browser.plan()
        self.assertEqual(value['readiness_timeout_seconds'], worker.MODEL_INIT_SECONDS)
        self.assertEqual(value['readiness_timeout_seconds'], 240)
        self.assertEqual(value['sandbox_lifetime_seconds'], 600)
        self.assertFalse(value['automatic_retry'])

    def test_default_plan_reads_no_keys_no_files_and_imports_no_cloud(self):
        with patch.object(browser, 'existing_token', side_effect=AssertionError('credential read')), \
                patch.object(browser, 'build_cached_image', side_effect=AssertionError('cloud build')), \
                patch.object(browser, 'cache_reference', side_effect=AssertionError('private cache read')), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(browser.main([]), 0)
        value = json.loads(output.getvalue())
        self.assertEqual(value['sandbox_lifetime_seconds'], 600)
        self.assertEqual(value['readiness_timeout_seconds'], 240)
        self.assertFalse(value['runtime_hf_secret'])
        self.assertFalse(value['persistent_service'])
        self.assertLess(value['maximum_runtime_estimate_usd'], .78)

    def test_gated_model_refusal_precedes_any_cpu_build(self):
        with patch.object(browser, 'existing_token', return_value='private-HF-sentinel'), \
                patch.object(browser, 'check_access', return_value=403), \
                patch.object(browser, 'build_cached_image', side_effect=AssertionError('cloud build')), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(browser.main(['--build-cache']), 2)
        self.assertFalse(json.loads(output.getvalue())['cloudDispatched'])
        self.assertNotIn('private-HF-sentinel', output.getvalue())

    def test_cached_runtime_never_reads_hf_token_and_checks_pinned_reference_first(self):
        app = Mock(); app.run.aio.return_value = contextlib.nullcontext()
        sdk = SimpleNamespace(App=Mock(return_value=app), Image=SimpleNamespace(from_id=Mock(return_value='cached-image')))
        runner = AsyncMock(return_value={'endReason': 'worker_exited', 'terminationConfirmed': True})
        with patch.dict('sys.modules', {'modal': sdk}), patch.object(browser, 'cache_reference', return_value='im-fixture'), \
                patch.object(browser, 'existing_token', side_effect=AssertionError('runtime HF credential read')), \
                patch.object(browser, 'run_sandbox', runner), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(browser.main(['--execute']), 0)
        sdk.Image.from_id.assert_called_once_with('im-fixture')
        runner.assert_awaited_once()
        app.run.aio.assert_called_once_with(detach=False)

    def test_worker_refresh_reuses_cached_image_without_access_check_or_weight_builder(self):
        app = Mock(); app.run.return_value = contextlib.nullcontext()
        image = Mock(); image.object_id = 'im-refreshed'
        sdk = SimpleNamespace(App=Mock(return_value=app))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cache.json'
            with patch.dict('sys.modules', {'modal': sdk}), patch.object(browser, 'cache_reference', return_value='im-existing'), \
                    patch.object(browser, 'existing_token', side_effect=AssertionError('HF credential read')), \
                    patch.object(browser, 'check_access', side_effect=AssertionError('HF access request')), \
                    patch.object(browser, 'build_cached_image', side_effect=AssertionError('heavy build')), \
                    patch.object(browser, 'refreshed_worker_image', return_value=image) as refresh, \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(browser.main(['--refresh-worker', '--cache-file', str(path)]), 0)
            refresh.assert_called_once_with('im-existing'); image.build.assert_called_once_with(app)
            value = browser.read_small_json(path)
            self.assertEqual(value['imageId'], 'im-refreshed'); self.assertEqual(value['parentImageId'], 'im-existing')
            self.assertFalse(json.loads(output.getvalue())['modelDownload'])

    def test_worker_refresh_definition_only_copies_source_over_existing_image(self):
        image = Mock()
        for name in ('add_local_python_source', 'add_local_file', 'run_commands'):
            getattr(image, name).return_value = image
        sdk = SimpleNamespace(Image=SimpleNamespace(from_id=Mock(return_value=image)))
        with patch.dict('sys.modules', {'modal': sdk}):
            self.assertIs(browser.refreshed_worker_image('im-existing'), image)
        sdk.Image.from_id.assert_called_once_with('im-existing')
        image.add_local_python_source.assert_called_once_with('personaplex_modal', 'personaplex_pcm_core', copy=True)
        self.assertEqual(image.add_local_file.call_args.args[1], '/root/personaplex_pcm_server.py')
        self.assertEqual(image.add_local_file.call_args.kwargs, {'copy': True})
        self.assertEqual(image.run_commands.call_args.args, (
            'timeout --signal=TERM --kill-after=5s 30s python -m py_compile /root/personaplex_pcm_server.py',))
        self.assertFalse(image.run_commands.call_args.kwargs)

    def test_app_enter_sandbox_and_app_exit_share_one_async_lifecycle(self):
        loops = []
        @contextlib.asynccontextmanager
        async def app_context(**options):
            self.assertEqual(options, {'detach': False}); loops.append(asyncio.get_running_loop())
            try: yield
            finally: loops.append(asyncio.get_running_loop())
        app = SimpleNamespace(run=SimpleNamespace(aio=app_context))
        async def runner(*_args):
            loops.append(asyncio.get_running_loop()); return {'status': 'fixture'}
        with patch.object(browser, 'run_sandbox', side_effect=runner):
            self.assertEqual(asyncio.run(browser.run_attached('sdk', app, 'image', 'moss', 'lease')),
                             {'status': 'fixture'})
        self.assertEqual(len(loops), 3)
        self.assertIs(loops[0], loops[1]); self.assertIs(loops[1], loops[2])

    def test_cli_retains_warning_and_fails_when_stop_is_acknowledged_but_exit_unobserved(self):
        app = Mock(); app.run.aio.return_value = contextlib.nullcontext()
        sdk = SimpleNamespace(App=Mock(return_value=app), Image=SimpleNamespace(from_id=Mock(return_value='image')))
        result = {'endReason': 'worker_deadline', 'terminationAcknowledged': True, 'terminationConfirmed': False,
                  'cleanupFailure': {'stage': 'sandbox_exit_observation', 'failure_code': 'deadline_exceeded', 'error_class': 'TimeoutError'}}
        with patch.dict('sys.modules', {'modal': sdk}), patch.object(browser, 'cache_reference', return_value='im-existing'), \
                patch.object(browser, 'run_sandbox', AsyncMock(return_value=result)), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(browser.main(['--execute']), 1)
        value = json.loads(output.getvalue())
        self.assertEqual(value['status'], 'cleanup_unconfirmed')
        self.assertFalse(value['terminationConfirmed']); self.assertTrue(value['terminationAcknowledged'])
        self.assertEqual(value['cleanupFailure']['stage'], 'sandbox_exit_observation')

    def test_operator_connect_origin_rejects_urls_credentials_redirect_queries_and_other_hosts(self):
        self.assertEqual(browser.connect_origin('https://fixture.modal.host/'), 'https://fixture.modal.host')
        for value in ('http://fixture.modal.host', 'https://attacker.example', 'https://x.modal.host.attacker.example',
                      'https://user:secret@x.modal.host', 'https://x.modal.host:443', 'https://x.modal.host/?signed=secret'):
            with self.assertRaises(ValueError): browser.connect_origin(value)

    def test_private_atomic_lease_and_epoch_cleanup_never_delete_foreign_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'lease.json'
            browser.private_write(path, {'epoch': 'owned', 'connectToken': 'private-sentinel'})
            self.assertEqual(browser.read_small_json(path)['connectToken'], 'private-sentinel')
            if os.name != 'nt': self.assertEqual(path.stat().st_mode & 0o077, 0)
            browser.own_remove(path, 'foreign'); self.assertTrue(path.exists())
            browser.own_remove(path, 'owned'); self.assertFalse(path.exists())
            self.assertFalse(list(Path(directory).glob('*.tmp')))

    def test_cache_manifest_refuses_different_revisions_and_oversized_operator_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cache.json'
            browser.private_write(path, {'imageId': 'im-fixture', 'sourceRevision': SOURCE_REVISION, 'modelRevision': MODEL_REVISION})
            self.assertEqual(browser.cache_reference(path), 'im-fixture')
            browser.private_write(path, {'imageId': 'im-fixture', 'sourceRevision': SOURCE_REVISION, 'modelRevision': 'foreign'})
            with self.assertRaises(ValueError): browser.cache_reference(path)
            path.write_text('x' * 17000)
            with self.assertRaises(ValueError): browser.read_small_json(path)

    def test_single_sandbox_has_native_fixed_command_no_hf_secret_no_public_ports_and_finally_termination(self):
        async def run():
            with tempfile.TemporaryDirectory() as directory:
                lease = Path(directory) / 'lease.json'
                sdk, sandbox = fake_sdk()
                health = Mock(return_value=True)
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    await browser.run_sandbox(sdk, 'ephemeral-app', 'private-cached-image', 'moss', lease, health=health,
                                              sleep=AsyncMock(), clock=lambda: 1_790_848_800, monotonic=lambda: 0)
                self.assertNotIn('private-connect-sentinel', output.getvalue())
                self.assertNotIn('modal.host', output.getvalue())
                args, kwargs = sdk.Sandbox.create.aio.call_args
                self.assertEqual(args, ('python', '/root/personaplex_pcm_server.py'))
                self.assertEqual(kwargs['timeout'], 600)
                self.assertEqual(kwargs['gpu'], 'A100-80GB')
                self.assertNotIn('block_network', kwargs)
                self.assertEqual(kwargs['outbound_cidr_allowlist'], ['127.0.0.0/8'])
                self.assertEqual(kwargs['encrypted_ports'], [])
                self.assertEqual(kwargs['unencrypted_ports'], [])
                self.assertNotIn('secrets', kwargs)
                self.assertNotIn('HF_TOKEN', kwargs['env'])
                self.assertEqual(kwargs['env']['PERSONAPLEX_MODEL_DIR'], '/opt/personaplex-weights')
                sandbox.wait_until_ready.aio.assert_awaited_once_with(timeout=240)
                sandbox.create_connect_token.aio.assert_awaited_once()
                self.assertEqual(sandbox.create_connect_token.aio.call_args.kwargs['port'], 8080)
                self.assertEqual(set(sandbox.create_connect_token.aio.call_args.kwargs['user_metadata']), {'leaseEpoch'})
                sdk.Probe.with_exec.assert_called_once_with('test', '-f', '/tmp/personaplex-ready', interval_ms=500)
                sandbox.terminate.aio.assert_awaited_once_with(wait=False)
                self.assertFalse(lease.exists()); self.assertFalse(lease.with_name('launch.lock').exists())
                report = browser.read_small_json(lease.with_name('last-run.json'))
                self.assertTrue(report['terminationConfirmed']); self.assertFalse(report['bankingAccess'])
        asyncio.run(run())

    def test_failed_warmup_or_health_revokes_lease_and_terminates_existing_sandbox(self):
        async def run():
            for fail_warmup in (True, False):
                with tempfile.TemporaryDirectory() as directory:
                    lease = Path(directory) / 'lease.json'; sdk, sandbox = fake_sdk()
                    if fail_warmup: sandbox.wait_until_ready.aio.side_effect = TimeoutError('private-upstream-diagnostic')
                    with self.assertRaises((TimeoutError, RuntimeError)):
                        await browser.run_sandbox(sdk, 'app', 'image', 'moss', lease, health=Mock(return_value=False))
                    sandbox.terminate.aio.assert_awaited_once_with(wait=False)
                    self.assertFalse(lease.exists()); self.assertFalse(lease.with_name('launch.lock').exists())
        asyncio.run(run())

    def test_single_launcher_lock_refuses_duplicate_before_cloud_creation(self):
        async def run():
            with tempfile.TemporaryDirectory() as directory:
                lease = Path(directory) / 'lease.json'; sdk, _ = fake_sdk()
                browser.private_write(lease.with_name('launch.lock'), {'epoch': 'other'}, replace=False)
                with self.assertRaises(FileExistsError): await browser.run_sandbox(sdk, 'app', 'image', 'moss', lease)
                sdk.Sandbox.create.aio.assert_not_awaited()
                self.assertEqual(browser.read_small_json(lease.with_name('launch.lock'))['epoch'], 'other')
        asyncio.run(run())

    def test_provider_timeout_terminates_and_cancellation_cleans_lease(self):
        async def run():
            for cancel in (False, True):
                with tempfile.TemporaryDirectory() as directory:
                    lease = Path(directory) / 'lease.json'; sdk, sandbox = fake_sdk()
                    sandbox.poll.aio.return_value = None
                    elapsed = [0]
                    async def sleeper(_seconds):
                        if cancel: raise asyncio.CancelledError()
                        elapsed[0] += 601
                    with contextlib.redirect_stdout(io.StringIO()):
                        if cancel:
                            with self.assertRaises(asyncio.CancelledError):
                                await browser.run_sandbox(sdk, 'app', 'image', 'moss', lease, health=Mock(return_value=True),
                                                          sleep=sleeper, monotonic=lambda: elapsed[0])
                        else:
                            await browser.run_sandbox(sdk, 'app', 'image', 'moss', lease, health=Mock(return_value=True),
                                                      sleep=sleeper, monotonic=lambda: elapsed[0])
                    sandbox.terminate.aio.assert_awaited_once_with(wait=False)
                    self.assertFalse(lease.exists())
        asyncio.run(run())

    def test_private_weight_preparation_downloads_only_pins_and_writes_no_token(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); fixtures = root / 'fixtures'; fixtures.mkdir(); target = root / 'cache'
            for name in MODEL_FILES:
                (fixtures / name).write_bytes(b'fixed-file')
            with tarfile.open(fixtures / 'voices.tgz', 'w:gz') as archive:
                value = b'fixed-embedding'; member = tarfile.TarInfo('voices/' + VOICE); member.size = len(value)
                archive.addfile(member, io.BytesIO(value))
            download = Mock(side_effect=lambda repo, name, **kwargs: fixtures / name)
            with patch.dict(os.environ, {'HF_TOKEN': 'private-build-sentinel'}):
                manifest = cache.prepare_weights(target, download=download)
            self.assertEqual(download.call_count, len(MODEL_FILES))
            for call in download.call_args_list:
                self.assertEqual(call.kwargs['revision'], MODEL_REVISION)
                self.assertEqual(call.kwargs['token'], 'private-build-sentinel')
            self.assertEqual(set(manifest['sha256']), {*MODEL_FILES, 'voices/' + VOICE})
            self.assertNotIn('private-build-sentinel', (target / 'revision.json').read_text())
            self.assertFalse((target / 'token').exists())
            self.assertEqual((target / 'voices' / VOICE).read_bytes(), b'fixed-embedding')

    def test_client_disconnect_readiness_loss_is_observed_once_and_not_called_live_acceptance(self):
        async def run():
            with tempfile.TemporaryDirectory() as directory:
                lease = Path(directory) / 'lease.json'; sdk, sandbox = fake_sdk()
                sandbox.poll.aio.side_effect = [None, 0]
                health = Mock(side_effect=[True, False])
                with contextlib.redirect_stdout(io.StringIO()):
                    report = await browser.run_sandbox(sdk, 'app', 'image', 'moss', lease, health=health, sleep=AsyncMock())
                self.assertEqual(report['endReason'], 'worker_exited')
                self.assertFalse(report['nativeBrowserAcceptanceVerified'])
                sdk.Sandbox.create.aio.assert_awaited_once()
                sandbox.terminate.aio.assert_awaited_once_with(wait=False)
                self.assertFalse(lease.exists())
        asyncio.run(run())

    def test_connect_token_failure_records_safe_grpc_stage_and_always_terminates(self):
        GRPCError = type('GRPCError', (Exception,), {'__str__': lambda _self: (_ for _ in ()).throw(AssertionError('raw error inspection'))})
        error = GRPCError()
        error.status = SimpleNamespace(name='UNIMPLEMENTED')
        async def run():
            with tempfile.TemporaryDirectory() as directory:
                lease = Path(directory) / 'lease.json'; sdk, sandbox = fake_sdk()
                sandbox.create_connect_token.aio.side_effect = error
                with self.assertRaises(GRPCError):
                    await browser.run_sandbox(sdk, 'app', 'image', 'moss', lease)
                sandbox.terminate.aio.assert_awaited_once_with(wait=False)
                report = browser.read_small_json(lease.with_name('last-run.json'))
                self.assertEqual(report['stage'], 'connect_token')
                self.assertEqual(report['failure_code'], 'modal_api_unsupported')
                self.assertEqual(report['error_class'], 'GRPCError')
                self.assertEqual(report['grpc_status'], 'UNIMPLEMENTED')
                self.assertTrue(report['terminationConfirmed'])
                self.assertFalse(lease.exists())
                self.assertEqual(error._avatar_safe_failure['stage'], 'connect_token')
        asyncio.run(run())

    def test_transport_diagnostic_never_forwards_messages_or_unknown_statuses(self):
        GRPCError = type('GRPCError', (Exception,), {})
        error = GRPCError('private-secret https://provider.example')
        error.status = SimpleNamespace(name='PRIVATE_SENTINEL')
        self.assertEqual(browser.diagnostic(error, 'connect_token'), {
            'stage': 'connect_token', 'error_class': 'GRPCError', 'failure_code': 'modal_api_failed'})
        for error in (AttributeError('private-secret'), TypeError('private-secret')):
            result = browser.diagnostic(error, 'connect_token')
            self.assertEqual(result['failure_code'], 'client_adapter_mismatch')
            self.assertEqual(result['error_class'], type(error).__name__)
            self.assertNotIn('private', json.dumps(result))
        ConflictError = type('ConflictError', (Exception,), {'__str__': lambda _self: (_ for _ in ()).throw(AssertionError('raw error inspection'))})
        error = ConflictError(); error._grpc_status = SimpleNamespace(name='ABORTED')
        self.assertEqual(browser.diagnostic(error, 'connect_token'), {
            'stage': 'connect_token', 'error_class': 'ConflictError',
            'failure_code': 'modal_operation_aborted', 'grpc_status': 'ABORTED'})

    def test_stop_acknowledgment_alone_cannot_claim_exit_confirmation(self):
        async def run():
            _, sandbox = fake_sdk()
            sandbox.terminate.aio.side_effect = None; sandbox.poll.aio.return_value = None
            acknowledged, confirmed, failure = await browser.stop_owned_worker(sandbox, observation_seconds=.01)
            self.assertTrue(acknowledged); self.assertFalse(confirmed)
            self.assertEqual(failure['stage'], 'sandbox_exit_observation')
            self.assertEqual(failure['failure_code'], 'deadline_exceeded')
            sandbox.terminate.aio.assert_awaited_once_with(wait=False)
        asyncio.run(run())

    def test_stop_observes_eventual_exit_without_reissuing_termination(self):
        async def run():
            _, sandbox = fake_sdk()
            sandbox.terminate.aio.side_effect = None
            sandbox.poll.aio.side_effect = [None, 137]
            acknowledged, confirmed, failure = await browser.stop_owned_worker(sandbox, pause=AsyncMock())
            self.assertTrue(acknowledged); self.assertTrue(confirmed); self.assertIsNone(failure)
            sandbox.terminate.aio.assert_awaited_once_with(wait=False)
            self.assertEqual(sandbox.poll.aio.await_count, 2)
        asyncio.run(run())

    def test_previous_safe_failure_evidence_is_preserved_without_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            lease = Path(directory) / 'lease.json'
            previous = lease.with_name('last-run.json')
            browser.private_write(previous, {'stage': 'model_warmup', 'error_class': 'ServiceError',
                'grpc_status': 'CANCELLED', 'terminationConfirmed': False, 'connectToken': 'private-sentinel'})
            browser.preserve_report(lease)
            copies = list((lease.parent / 'history').glob('run-*.json'))
            self.assertEqual(len(copies), 1)
            self.assertEqual(browser.read_small_json(copies[0])['grpc_status'], 'CANCELLED')
            self.assertNotIn('private', copies[0].read_text())


if __name__ == '__main__':
    unittest.main()
