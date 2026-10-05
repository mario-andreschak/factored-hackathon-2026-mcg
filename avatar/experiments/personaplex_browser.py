"""Explicit bounded native browser audition. Default --plan performs no cloud work."""
from __future__ import annotations

import argparse
import asyncio
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

from personaplex_modal import (
    SOURCE_REVISION, MODEL_REVISION, GPU, CPU_LIMIT, MEMORY_LIMIT_GIB,
    build_image, existing_token, check_access, access_allowed, NoRedirect,
)
from modal_diagnostic import diagnostic

PROTOCOL = 'personaplex-pcm-v1'
LIFETIME = 600
READY_TIMEOUT = 240
ROOT = Path(__file__).resolve().parent.parent
DIRECTORY = ROOT / '.local' / 'personaplex-browser'
DEFAULT_CACHE = DIRECTORY / 'cache.json'
DEFAULT_LEASE = DIRECTORY / 'lease.json'
CPU_RATE = 0.00003942
MEMORY_RATE = 0.00000667
GPU_RATE = 0.000694
STAGED_PHASES = ('warm', 'priming', 'primed', 'streaming', 'closed')
STAGED_HEALTH_KEYS = frozenset({'ready', 'protocol', 'avatar', 'sourceRevision', 'modelRevision',
                              'selection', 'phase', 'voice', 'promptHash', 'selectionId'})


def production_prompt_hashes() -> dict:
    # Pure source constants only; this import never loads assets or GPU libraries.
    from personaplex_pcm_server import PERSONAS
    return {role: hashlib.sha256(prompt.encode('utf8')).hexdigest() for role, prompt in PERSONAS.items()}


def plan(initial_role=False) -> dict:
    return {
        'status': 'prepared_not_dispatched', 'protocol': PROTOCOL,
        'source_revision': SOURCE_REVISION, 'model_revision': MODEL_REVISION,
        'gpu': GPU, 'sandbox_lifetime_seconds': LIFETIME, 'readiness_timeout_seconds': READY_TIMEOUT,
        'worker': 'python /root/personaplex_pcm_server.py', 'port': 8080,
        'runtime_hf_secret': False, 'raw_public_ports': False,
        'outbound_cidr_allowlist': ['127.0.0.0/8'],
        'persistent_service': False, 'automatic_retry': False,
        'cpu_maximum': CPU_LIMIT, 'memory_maximum_gib': MEMORY_LIMIT_GIB,
        'maximum_runtime_estimate_usd': round(LIFETIME * (GPU_RATE + CPU_LIMIT * CPU_RATE + MEMORY_LIMIT_GIB * MEMORY_RATE), 4),
        'total_target_usd': 1.0, 'cost_note': 'Private CPU image build is separate; this estimate is not an account spending cap.',
        'scope': 'One native conversation, fixed launch avatar/qualified NATM1 voice. No bank data, result narration, ASR or tool claims.',
        **({'selection': 'initial', 'lease_version': 2, 'probe_marker': '/tmp/personaplex-warm',
            'warm_is_voice_ready': False, 'production_prompt_hashes': production_prompt_hashes(),
            'scope': 'Warm weights only until one private authenticated initial role prime; no native READY before successful prime. No bank data or result narration.'}
           if initial_role else {}),
    }


def private_write(path: Path, value: dict, *, replace=True) -> None:
    """Restrict credentials before writing, then publish atomically."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + secrets.token_hex(8) + '.tmp') if replace else path
    handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        if os.name == 'nt':
            domain = os.environ.get('USERDOMAIN', '')
            user = os.environ.get('USERNAME') or getpass.getuser()
            principal = f'{domain}\\{user}' if domain else user
            subprocess.run(['icacls', str(temporary), '/inheritance:r', '/grant:r', principal + ':(F)'],
                           check=True, capture_output=True, timeout=10)
        payload = (json.dumps(value, separators=(',', ':')) + '\n').encode('utf8')
        if len(payload) > 16 * 1024:
            raise ValueError('The bounded lease is oversized.')
        with os.fdopen(handle, 'wb') as output:
            handle = None
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        if replace:
            os.replace(temporary, path)
    finally:
        if handle is not None:
            os.close(handle)
        if replace and temporary.exists():
            temporary.unlink()


def read_small_json(path: Path) -> dict:
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16 * 1024:
        raise ValueError('Expected a bounded operator-owned file.')
    data = json.loads(path.read_text(encoding='utf8'))
    if not isinstance(data, dict):
        raise ValueError('Expected an operator-owned JSON object.')
    return data


def cache_reference(path: Path) -> str:
    value = read_small_json(path)
    image_id = value.get('imageId', '')
    if value.get('sourceRevision') != SOURCE_REVISION or value.get('modelRevision') != MODEL_REVISION or \
            not isinstance(image_id, str) or not image_id.startswith('im-') or not image_id[3:].isalnum() or len(image_id) > 128:
        raise ValueError('The private cached image reference does not match the pinned assets.')
    return image_id


def build_cached_image(token: str):
    import modal
    directory = Path(__file__).resolve().parent
    worker = directory / 'personaplex_pcm_server.py'
    if not worker.is_file():
        raise RuntimeError('The native PCM worker source is not prepared.')
    return (
        build_image(copy_source=True)
        .add_local_file(directory / 'personaplex_cache.py', '/root/personaplex_cache.py', copy=True)
        .run_commands('timeout --signal=TERM --kill-after=10s 600s python /root/personaplex_cache.py',
                      secrets=[modal.Secret.from_dict({'HF_TOKEN': token})])
        .env({'HF_HUB_OFFLINE': '1', 'HF_HUB_DISABLE_PROGRESS_BARS': '1'})
        .add_local_python_source('personaplex_pcm_core', copy=True)
        .add_local_file(worker, '/root/personaplex_pcm_server.py', copy=True)
    )


def refreshed_worker_image(reference: str):
    """Small source overlay; never re-enters the private weight download layer."""
    import modal
    directory = Path(__file__).resolve().parent
    return (
        modal.Image.from_id(reference)
        .add_local_python_source('personaplex_modal', 'personaplex_pcm_core', copy=True)
        .add_local_file(directory / 'personaplex_pcm_server.py', '/root/personaplex_pcm_server.py', copy=True)
        .run_commands('timeout --signal=TERM --kill-after=5s 30s python -m py_compile /root/personaplex_pcm_server.py')
    )


def connect_origin(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    host = parsed.hostname or ''
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment or \
            parsed.path not in ('', '/') or not (host.endswith('.modal.run') or host.endswith('.modal.host')):
        raise ValueError('Modal returned an unexpected connect origin.')
    return f'https://{host}'


def worker_ready(base_url: str, token: str, avatar: str) -> bool:
    request = urllib.request.Request(base_url + '/healthz', headers={'Authorization': 'Bearer ' + token})
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=3) as response:
            body = response.read(4097)
            if response.status != 200 or len(body) > 4096:
                return False
        value = json.loads(body)
        return value == {'ready': True, 'protocol': PROTOCOL, 'avatar': avatar,
                         'sourceRevision': SOURCE_REVISION, 'modelRevision': MODEL_REVISION}
    except (urllib.error.URLError, ValueError, TimeoutError, OSError):
        return False


def validate_staged_health(value: dict) -> dict:
    """Strict proof of warm/primed state; no URLs or provider strings accepted."""
    if not isinstance(value, dict) or set(value) != STAGED_HEALTH_KEYS or \
            type(value.get('ready')) is not bool or value.get('selection') != 'initial' or \
            value.get('protocol') != PROTOCOL or value.get('sourceRevision') != SOURCE_REVISION or \
            value.get('modelRevision') != MODEL_REVISION or value.get('voice') != 'NATM1.pt' or \
            value.get('phase') not in STAGED_PHASES:
        raise ValueError('Unexpected staged worker health contract')
    phase, avatar, identity, prompt = value['phase'], value['avatar'], value['selectionId'], value['promptHash']
    selected = avatar in ('moss', 'orbit', 'spark') and isinstance(identity, str) and \
               re.fullmatch(r'[A-Za-z0-9_-]{1,128}', identity) is not None
    empty = avatar is None and identity is None and prompt is None
    bound = selected and prompt == production_prompt_hashes()[avatar]
    if phase == 'warm' and (value['ready'] or not empty) or \
            phase == 'priming' and (value['ready'] or not selected or prompt is not None) or \
            phase == 'primed' and not bound or \
            phase == 'streaming' and (not value['ready'] or not bound) or \
            phase == 'closed' and (value['ready'] or not (empty or selected and (prompt is None or bound))):
        raise ValueError('Staged phase and selected role proof disagree')
    return dict(value)


def transition_staged_health(previous: dict | None, value: dict) -> dict:
    """Permit one initial selection, then freeze its role/prompt/selection binding."""
    current = validate_staged_health(value)
    if previous is None:
        if current['phase'] != 'warm':
            raise ValueError('Initial lease requires actually warm, unselected weights')
        return current
    old = validate_staged_health(previous)
    if STAGED_PHASES.index(current['phase']) < STAGED_PHASES.index(old['phase']):
        raise ValueError('Staged worker phase regressed')
    if old['selectionId'] is not None and (current['selectionId'] != old['selectionId'] or current['avatar'] != old['avatar']):
        raise ValueError('An admitted initial role binding changed')
    if old['promptHash'] is not None and current['promptHash'] != old['promptHash']:
        raise ValueError('An admitted initial role prompt changed')
    return current


def worker_staged_health(base_url: str, token: str) -> dict | None:
    request = urllib.request.Request(base_url + '/healthz', headers={'Authorization': 'Bearer ' + token})
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=3) as response:
            body = response.read(4097)
            if response.status != 200 or len(body) > 4096:
                return None
        return validate_staged_health(json.loads(body))
    except (urllib.error.URLError, ValueError, TimeoutError, OSError):
        return None


def own_remove(path: Path, epoch: str) -> None:
    try:
        if read_small_json(path).get('epoch') == epoch:
            path.unlink()
    except (OSError, ValueError):
        pass


def timestamp() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime()) + '.000Z'


def preserve_report(lease_file: Path) -> None:
    """Keep bounded sanitized run evidence before the next explicit launch."""
    previous = Path(lease_file).with_name('last-run.json')
    if not previous.exists(): return
    value = read_small_json(previous)
    allowed = {'stage', 'endReason', 'workerCreated', 'terminationConfirmed', 'terminationAcknowledged',
               'providerLifetimeSeconds', 'bankingAccess', 'resultNarration', 'persistentService',
               'nativeBrowserAcceptanceVerified', 'error_class', 'failure_code', 'grpc_status',
               'cleanupFailure', 'elapsedSeconds', 'warmupSeconds'}
    allowed.update({'selection', 'lastPhase', 'initialRolePrimed'})
    safe = {key: value[key] for key in allowed if key in value}
    private_write(previous.parent / 'history' / f'run-{time.time_ns()}.json', safe)


async def stop_owned_worker(sandbox, *, exit_observed=False, observation_seconds=10, pause=asyncio.sleep):
    """One stop command; observe exit separately without another worker/start."""
    acknowledged = False
    failure = None
    try:
        await asyncio.wait_for(sandbox.terminate.aio(wait=False), timeout=5)
        acknowledged = True
    except Exception as error:
        failure = diagnostic(error, 'sandbox_termination_command')
    confirmed = exit_observed
    deadline = asyncio.get_running_loop().time() + observation_seconds
    while not confirmed and asyncio.get_running_loop().time() < deadline:
        remaining = deadline - asyncio.get_running_loop().time()
        try:
            status = await asyncio.wait_for(sandbox.poll.aio(), timeout=min(2, remaining))
            confirmed = status is not None
        except Exception as error:
            failure = diagnostic(error, 'sandbox_exit_observation')
        if not confirmed:
            await pause(min(.5, max(0, deadline - asyncio.get_running_loop().time())))
    if not confirmed and failure is None:
        failure = diagnostic(TimeoutError(), 'sandbox_exit_observation')
    return acknowledged, confirmed, failure


async def run_sandbox(sdk, app, image, avatar, lease_file, *, health=worker_ready, monotonic=time.monotonic,
                      clock=time.time, sleep=asyncio.sleep, lifetime=LIFETIME, initial_role=False,
                      staged_health=None):
    """No retries. The provider lifetime is fixed; injected clocks permit local tests."""
    epoch = secrets.token_urlsafe(32)
    lock = Path(lease_file).with_name('launch.lock')
    private_write(lock, {'epoch': epoch, 'pid': os.getpid()}, replace=False)
    sandbox = None
    created = clock()
    started = monotonic()
    deadline = started + min(lifetime, LIFETIME)
    stage = 'sandbox_create'
    terminated = False
    end_reason = 'initialization_failed'
    failure = None
    cleanup_failure = None
    acknowledged = False
    exit_observed = False
    warmup_seconds = None
    warmup_started = None
    initial_state = None
    staged_reader = worker_staged_health if staged_health is None else staged_health
    try:
        preserve_report(Path(lease_file))
        sandbox = await asyncio.wait_for(sdk.Sandbox.create.aio(
            'python', '/root/personaplex_pcm_server.py', app=app, image=image,
            gpu=GPU, cpu=(2, CPU_LIMIT), memory=(32768, MEMORY_LIMIT_GIB * 1024), timeout=LIFETIME,
            outbound_cidr_allowlist=['127.0.0.0/8'], env={'PERSONAPLEX_AVATAR': avatar, 'PERSONAPLEX_VOICE': 'NATM1.pt',
                'PERSONAPLEX_MODEL_DIR': '/opt/personaplex-weights', 'PERSONAPLEX_DEADLINE_SECONDS': str(LIFETIME),
                'PERSONAPLEX_LEASE_EPOCH': epoch, **({'PERSONAPLEX_INITIAL_MODE': '1'} if initial_role else {})},
            readiness_probe=sdk.Probe.with_exec('test', '-f', '/tmp/personaplex-warm' if initial_role else '/tmp/personaplex-ready', interval_ms=500),
            encrypted_ports=[], unencrypted_ports=[],
        ), timeout=30)
        # Metadata only: retain a cleanup handle even if readiness fails.
        private_write(Path(lease_file).with_name('worker.json'), {'epoch': epoch, 'sandboxId': sandbox.object_id,
                                                               'createdAt': created, 'expiresAt': created + LIFETIME})
        stage = 'model_warmup'
        warmup_started = monotonic()
        await asyncio.wait_for(sandbox.wait_until_ready.aio(timeout=READY_TIMEOUT), timeout=READY_TIMEOUT + 5)
        warmup_seconds = round(max(0, monotonic() - warmup_started), 3)
        stage = 'connect_token'
        credentials = await asyncio.wait_for(sandbox.create_connect_token.aio(user_metadata={'leaseEpoch': epoch}, port=8080), timeout=10)
        base_url = connect_origin(credentials.url)
        token = credentials.token
        if not isinstance(token, str) or len(token) < 16 or len(token) > 8192 or any(not 33 <= ord(char) <= 126 for char in token):
            raise ValueError('Modal returned an invalid connect token.')
        stage = 'health'
        if initial_role:
            initial_state = transition_staged_health(None, await asyncio.to_thread(staged_reader, base_url, token))
        elif not await asyncio.to_thread(health, base_url, token, avatar):
            raise RuntimeError('The warmed model health check failed.')
        def publish():
            private_write(Path(lease_file), {
                'version': 1, 'ready': True, 'protocol': PROTOCOL, 'epoch': epoch, 'avatar': avatar,
                **({'version': 2, 'ready': initial_state['ready'], 'selection': 'initial', 'phase': initial_state['phase'],
                    'avatar': initial_state['avatar'], 'voice': initial_state['voice'], 'promptHash': initial_state['promptHash'],
                    'selectionId': initial_state['selectionId']} if initial_role else {}),
                'baseUrl': base_url, 'connectToken': token, 'sourceRevision': SOURCE_REVISION, 'modelRevision': MODEL_REVISION,
                'createdAt': time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(created)) + '.000Z',
                'expiresAt': time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(created + min(lifetime, LIFETIME))) + '.000Z',
                'updatedAt': time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(clock())) + '.000Z',
            })
        publish()
        # Do not print the provider URL/token or lease contents.
        print(json.dumps({'status': 'warm' if initial_role else 'ready', 'avatar': None if initial_role else avatar,
                          **({'selection': 'initial', 'nativeReady': False} if initial_role else {}),
                          'protocol': PROTOCOL, 'leaseFile': str(lease_file),
                          'maximumWorkerLifetimeSeconds': LIFETIME}), flush=True)
        stage = 'initial_selection' if initial_role else 'browser_session'
        end_reason = 'worker_deadline'
        while monotonic() < deadline:
            await sleep(min(2, max(0, deadline - monotonic())))
            if await asyncio.wait_for(sandbox.poll.aio(), timeout=5) is not None:
                exit_observed = True
                end_reason = 'worker_exited'
                break
            alive = True
            if initial_role:
                value = await asyncio.to_thread(staged_reader, base_url, token)
                if value is None:
                    alive = False
                else:
                    initial_state = transition_staged_health(initial_state, value)
                    alive = initial_state['phase'] != 'closed' and (initial_state['phase'] != 'primed' or initial_state['ready'])
                    if initial_state['ready']:
                        stage = 'browser_session'
            else:
                alive = await asyncio.to_thread(health, base_url, token, avatar)
            if not alive:
                # Closing the one admitted stream drops HTTP readiness before
                # the process necessarily appears exited. Observe once; never
                # launch/retry another worker or turn cleanup into acceptance.
                await sleep(.2)
                exited = await asyncio.wait_for(sandbox.poll.aio(), timeout=5)
                exit_observed = exited is not None
                end_reason = 'worker_exited' if exited is not None else 'worker_lost_readiness'
                break
            publish()
    except BaseException as error:
        if stage == 'model_warmup' and warmup_started is not None:
            warmup_seconds = round(max(0, monotonic() - warmup_started), 3)
        failure = diagnostic(error, stage)
        # Preserve the actual safe stage through App cleanup without changing
        # exception identity (including cancellation). No raw data is attached.
        try: error._avatar_safe_failure = failure
        except (AttributeError, TypeError): pass
        raise
    finally:
        own_remove(Path(lease_file), epoch)
        if sandbox is not None:
            acknowledged, terminated, cleanup_failure = await stop_owned_worker(sandbox, exit_observed=exit_observed)
        own_remove(lock, epoch)
        report = {'stage': stage, 'endReason': end_reason, 'workerCreated': sandbox is not None,
                       'terminationAcknowledged': acknowledged, 'terminationConfirmed': terminated,
                       'providerLifetimeSeconds': LIFETIME, 'elapsedSeconds': round(max(0, monotonic() - started), 3),
                       'bankingAccess': False, 'resultNarration': False, 'persistentService': False,
                       'nativeBrowserAcceptanceVerified': False}
        if initial_role:
            report.update(selection='initial', lastPhase=initial_state['phase'] if initial_state else None,
                          initialRolePrimed=bool(initial_state and initial_state['promptHash']))
        if warmup_seconds is not None:
            report['warmupSeconds'] = warmup_seconds
        if failure is not None:
            report.update(failure)
        if cleanup_failure is not None:
            report['cleanupFailure'] = cleanup_failure
        private_write(Path(lease_file).with_name('last-run.json'), report)
    return report


async def run_attached(sdk, app, image, avatar, lease_file, *, initial_role=False):
    """Keep App and every async Sandbox operation in the same async lifecycle."""
    async with app.run.aio(detach=False):
        return await run_sandbox(sdk, app, image, avatar, lease_file, **({'initial_role': True} if initial_role else {}))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--plan', action='store_true')
    mode.add_argument('--build-cache', action='store_true', help='Spend CPU build compute; no GPU. Requires already granted HF access.')
    mode.add_argument('--refresh-worker', action='store_true', help='Build only a small worker COPY layer over the existing private cache; no HF/GPU.')
    mode.add_argument('--execute', action='store_true', help='Spend one bounded GPU Sandbox using an already built private cache.')
    parser.add_argument('--avatar', choices=('moss', 'orbit', 'spark'), default='moss')
    parser.add_argument('--initial-role', action='store_true', help='Source candidate: warm unselected weights, then allow one private initial role prime.')
    parser.add_argument('--cache-file', type=Path, default=DEFAULT_CACHE)
    parser.add_argument('--lease-file', type=Path, default=DEFAULT_LEASE)
    options = parser.parse_args(argv)
    if options.initial_role and (options.build_cache or options.refresh_worker or options.avatar != 'moss'):
        parser.error('--initial-role applies to plan/execute and cannot specify a fixed --avatar')
    if not options.build_cache and not options.refresh_worker and not options.execute:
        print(json.dumps(plan(options.initial_role), indent=2)); return 0
    stage = 'preflight'
    try:
        if options.build_cache:
            token = existing_token()
            status = check_access(token)
            if not access_allowed(status):
                print(json.dumps({'status': 'blocked', 'modelAccessStatus': status, 'cloudDispatched': False})); return 2
            import modal
            stage = 'private_cpu_image_build'
            image = build_cached_image(token)
            app = modal.App('elsewhere-personaplex-private-cache')
            with app.run(detach=False):
                image.build(app)
                reference = image.object_id
            private_write(options.cache_file, {'imageId': reference, 'sourceRevision': SOURCE_REVISION,
                          'modelRevision': MODEL_REVISION, 'createdAt': timestamp()})
            print(json.dumps({'status': 'private_cache_built', 'cacheFile': str(options.cache_file), 'gpuDispatched': False}))
        elif options.refresh_worker:
            reference = cache_reference(options.cache_file)
            import modal
            stage = 'worker_source_overlay'
            image = refreshed_worker_image(reference)
            app = modal.App('elsewhere-personaplex-worker-refresh')
            with app.run(detach=False):
                image.build(app)
                updated = image.object_id
            private_write(options.cache_file, {'imageId': updated, 'sourceRevision': SOURCE_REVISION,
                          'modelRevision': MODEL_REVISION, 'createdAt': timestamp(), 'parentImageId': reference})
            print(json.dumps({'status': 'worker_source_refreshed', 'cacheFile': str(options.cache_file),
                              'gpuDispatched': False, 'modelDownload': False, 'runtimeHfSecret': False}))
        else:
            reference = cache_reference(options.cache_file)  # No HF token is read for a cached runtime.
            import modal
            app = modal.App('elsewhere-personaplex-browser-audition')
            image = modal.Image.from_id(reference)
            stage = 'bounded_sandbox'
            result = asyncio.run(run_attached(modal, app, image, options.avatar, options.lease_file,
                                             **({'initial_role': True} if options.initial_role else {})))
            if result['terminationConfirmed'] is not True:
                print(json.dumps({'status': 'cleanup_unconfirmed', 'failure_code': 'worker_exit_unconfirmed',
                    'terminationAcknowledged': result.get('terminationAcknowledged', False),
                    'terminationConfirmed': False, 'persistentService': False,
                    'nativeBrowserAcceptanceVerified': False, **({'cleanupFailure': result['cleanupFailure']}
                                                                  if 'cleanupFailure' in result else {})}))
                return 1
            print(json.dumps({'status': 'ended', 'endReason': result['endReason'],
                              'terminationConfirmed': result['terminationConfirmed'], 'nativeBrowserAcceptanceVerified': False,
                              'persistentService': False}))
        return 0
    except KeyboardInterrupt:
        print(json.dumps({'status': 'stopped', 'code': 'operator_stopped', 'persistentService': False})); return 130
    except Exception as error:
        safe = getattr(error, '_avatar_safe_failure', None)
        public = {'status': 'failed', **(safe if isinstance(safe, dict) else diagnostic(error, stage)),
                  'persistentService': False}
        print(json.dumps(public)); return 1


if __name__ == '__main__':
    raise SystemExit(main())
