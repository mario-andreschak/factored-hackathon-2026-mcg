"""Future root execution only: export reviewed Git sources and build isolated public UI. Never Docker-build/deploy."""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import time
import types

TMP = Path('C:/Users/Moe/.codex/tmp')
ACCEPTED_CONTEXT = TMP / 'savia-final-runtime-634aa5244374'
ACCEPTED_HEAD = '634aa5244374b3e105ef7864fa100530bab45ec2'
BASE_IMAGE = 'registry.fly.io/savia-rc-2026@sha256:44bc554cd82ad62db51d536d580df248cbb188d24732e7ec1ed8133617c632a0'
ACCEPTED_PROOF_SHA = 'b682f3cc3784e803a7f285a4fbed8ebcd9090ab9394fd2533595fea331bbbb27'
ACCEPTED_SOURCE_SHA = '17382e0776ce03e5ec9ee43680f3112768aeba34df9818c7427d83bf70d6eb0a'
ACCEPTED_PORTAL_SHA = '652268ee73698b9f73219da6b2a5482bcfbab4efb02fcee7776f7ab9d16b57b7'
ALLOWED_DELTA = {'frontend/src/avatar/useSaviaVoice.ts', 'frontend/src/avatar/native-voice.test.tsx'}
CRITICAL = ('frontend/server/conversation.py', 'frontend/server/voice.py', 'deploy/rc/run.py')
NATIVE_HEAD = '6219bc81a8a4c7f2936769e7727e5146dd2713d0'


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(body):
    return hashlib.sha256(body).hexdigest()


def read_json(text):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, 'Duplicate JSON key denied: ' + key)
            value[key] = item
        return value
    return json.loads(text, object_pairs_hook=unique)


def save(path, obj):
    body = (json.dumps(obj, indent=2, ensure_ascii=False) + '\n').encode()
    path.write_bytes(body)
    return sha(body)


def regular_files(base):
    result = {}
    for path in sorted(base.rglob('*')):
        require(not path.is_symlink() and (path.is_file() or path.is_dir()), 'Nonregular build entry denied')
        if path.is_file():
            result[path.relative_to(base).as_posix()] = sha(path.read_bytes())
    return result


def verify_export(app, files):
    for name, wanted in files.items():
        parsed = PurePosixPath(name)
        require(parsed.as_posix() == name and not parsed.is_absolute() and '..' not in parsed.parts and
                '\\' not in name and ':' not in name, 'Unsafe export path')
        target = app / name
        require(target.is_file() and not target.is_symlink() and sha(target.read_bytes()) == wanted, name)


def is_browser_input(name):
    return name.startswith(('frontend/src/', 'frontend/public/')) or name in {
        'frontend/package.json', 'frontend/package-lock.json', 'frontend/index.html', 'frontend/vite.config.ts',
        'frontend/tsconfig.json', 'frontend/tsconfig.app.json', 'frontend/tsconfig.node.json'}


def prepare(args):
    require(args.reviewed_ui_delta and args.build_public_frontend,
            'Future execution requires both --reviewed-ui-delta and --build-public-frontend')
    head = args.revision
    require(re.fullmatch('[0-9a-f]{40}', head) is not None, 'Exact lowercase 40-hex committed HEAD required')
    repo = args.repo.resolve()
    def git(*cmd):
        return subprocess.check_output(['git', '-C', str(repo), *cmd])
    require(git('rev-parse', '--verify', head + '^{commit}').decode().strip() == head and
            git('rev-parse', 'HEAD').decode().strip() == head, 'Exact reviewed revision must be this checkout HEAD')
    require(not git('status', '--porcelain'), 'Reviewed checkout must be clean')
    tree = git('rev-parse', head + '^{tree}').decode().strip()
    accepted_bytes = (ACCEPTED_CONTEXT / 'runtime-verification.json').read_bytes()
    require(sha(accepted_bytes) == ACCEPTED_PROOF_SHA, 'Accepted runtime proof bytes changed')
    accepted = read_json(accepted_bytes)
    old = accepted['source_hashes']
    require(accepted['image'] == BASE_IMAGE and accepted['manifest']['git_head'] == ACCEPTED_HEAD and
            old == accepted['manifest']['files'] and len(old) == 183, 'Accepted 634 source/image proof mismatch')
    require(accepted['source_manifest_sha256'] == ACCEPTED_SOURCE_SHA, 'Accepted source manifest pin mismatch')
    require(len(accepted['served_ui']) == 22 and len(accepted['retained_runtime_hashes']) == 4,
            'Accepted component counts mismatch')
    # Compare the actual immutable source bytes before creating any build directory.
    future = {}
    for name in old:
        require(sha(git('show', ACCEPTED_HEAD + ':' + name)) == old[name],
                'Accepted Git634 source congruence mismatch: ' + name)
        future[name] = sha(git('show', head + ':' + name))
    require({p for p in old if old[p] != future[p]} == ALLOWED_DELTA,
            'Exactly the two reviewed UI source files must differ from accepted634')
    for name in CRITICAL:
        require(future[name] == old[name] == sha(git('show', NATIVE_HEAD + ':' + name)),
                'Accepted6219 critical server/RC bytes changed: ' + name)
    # Frozen source media is outside the application export; validate it separately against immutable Git.
    validation_name = 'docs/submission/media/decks/final/savia-final-pitch-validation.json'
    validation = read_json(git('show', ACCEPTED_HEAD + ':' + validation_name))
    frozen_media = validation['frozen_artifacts_sha256']
    require(len(frozen_media) == 6, 'Frozen original media count changed')
    for name, wanted in frozen_media.items():
        require(name.startswith('docs/submission/media/') and '..' not in PurePosixPath(name).parts and
                sha(git('show', ACCEPTED_HEAD + ':' + name)) == wanted and
                sha(git('show', head + ':' + name)) == wanted, 'Frozen original media changed: ' + name)
    deck_prefix = 'docs/submission/media/decks/final/'
    deck_manifest_name = deck_prefix + 'savia-final-pitch-manifest.json'
    deck_bytes = git('show', ACCEPTED_HEAD + ':' + deck_manifest_name)
    require(git('show', head + ':' + deck_manifest_name) == deck_bytes, 'Final deck metadata changed')
    deck_manifest = read_json(deck_bytes)
    require(len(deck_manifest['files']) == 16, 'Full final deck artifact count changed')
    frozen_deck = {deck_manifest_name: sha(deck_bytes)}
    for name, record in deck_manifest['files'].items():
        parsed = PurePosixPath(name)
        require(not parsed.is_absolute() and '..' not in parsed.parts and parsed.as_posix() == name and
                '\\' not in name and ':' not in name, 'Unsafe deck manifest path')
        path = deck_prefix + name
        require(sha(git('show', ACCEPTED_HEAD + ':' + path)) == record['sha256'] and
                sha(git('show', head + ':' + path)) == record['sha256'], 'Final deck artifact changed: ' + path)
        frozen_deck[path] = record['sha256']
    exporter_name = 'deploy/rc/build_public_context.py'
    exporter_body = git('show', head + ':' + exporter_name)
    require(sha(exporter_body) == old[exporter_name], 'Immutable exporter changed')
    require(args.node.is_file() and args.npm_cli.is_file(), 'Explicit existing Node and npm CLI files required')
    context = TMP / ('savia-ui-runtime-' + head[:12])
    work = TMP / ('savia-ui-frontend-build-' + head[:12])
    require(context.parent.resolve() == TMP.resolve() and work.parent.resolve() == TMP.resolve(), 'Output root mismatch')
    require(not context.exists() and not work.exists(), 'Fresh context/build directories required; never overwritten or deleted')
    context.mkdir(); work.mkdir()
    app = context / 'application'
    exporter = types.ModuleType('immutable_public_export')
    exporter.__file__ = str(repo / exporter_name)
    exec(compile(exporter_body, exporter.__file__, 'exec'), exporter.__dict__)
    exporter.export(app, head)
    manifest = read_json((app / 'source-manifest.json').read_text(encoding='utf-8'))
    require(manifest['git_head'] == head and manifest['git_tree'] == tree and len(manifest['files']) == 177,
            'Immutable export shape changed')
    analytics = {p: h for p, h in future.items() if p.startswith('analytics/')}
    require(len(analytics) == 6, 'Offline analytics file count changed')
    for name in analytics:
        target = app / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(git('show', head + ':' + name))
    manifest['files'].update(analytics)
    require(manifest['files'] == future and len(future) == 183, 'Exported path set or hashes changed')
    verify_export(app, future)
    # Preserve portal payloads AND its metadata byte-for-byte at its qualified634 origin.
    portal = {p: h for p, h in old.items() if p.startswith('web/submission/')}
    require(len(portal) == 28 and all(future[p] == h for p, h in portal.items()), 'Portal634 changed')
    pitch = {p: h for p, h in portal.items() if p.startswith('web/submission/pitch/')}
    retained_media = {**pitch, **{p: h for p, h in portal.items() if p.startswith('web/submission/assets/') or
        p in {'web/submission/savia-submission.vtt', 'web/submission/styles.css'}}}
    require(len(pitch) == 12 and len(retained_media) == 16, 'Retained delivery artifact counts changed')
    portal_bytes = (ACCEPTED_CONTEXT / 'application/portal-source-manifest.json').read_bytes()
    require(sha(portal_bytes) == ACCEPTED_PORTAL_SHA and read_json(portal_bytes) == accepted['portal_source_manifest'] and
            read_json(portal_bytes)['files'] == portal, 'Accepted portal metadata proof mismatch')
    (app / 'portal-source-manifest.json').write_bytes(portal_bytes)
    inputs = {p: h for p, h in future.items() if is_browser_input(p)}
    frontend = work / 'frontend'; frontend.mkdir()
    for name in inputs:
        rel = PurePosixPath(name).relative_to('frontend')
        require(not any(x.startswith('.env') or x in {'node_modules', 'dist', 'private', '__pycache__'} for x in rel.parts),
                'Private/transient frontend input denied')
        target = frontend / str(rel); target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(app / name, target)
    require(regular_files(frontend) == {p.removeprefix('frontend/'): h for p, h in inputs.items()},
            'Clean isolated frontend input map mismatch')
    # No inherited npm/VITE/credential environment or global/user configuration enters the public build.
    user_rc = work / 'empty-user.npmrc'; user_rc.write_bytes(b'')
    global_rc = work / 'empty-global.npmrc'; global_rc.write_bytes(b'')
    env = {k: v for k, v in os.environ.items() if k.upper() in {
        'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'TEMP', 'TMP'}}
    env['PATH'] = str(args.node.resolve().parent) + os.pathsep + env.get('PATH', '')
    env.update({'NPM_CONFIG_USERCONFIG': str(user_rc), 'NPM_CONFIG_GLOBALCONFIG': str(global_rc),
                'NPM_CONFIG_CACHE': str(work / 'npm-cache'), 'NPM_CONFIG_AUDIT': 'false',
                'NPM_CONFIG_FUND': 'false', 'NODE_ENV': 'production'})
    node = str(args.node.resolve()); npm_cli = str(args.npm_cli.resolve())
    node_version = subprocess.check_output([node, '--version'], env=env, text=True).strip()
    npm_version = subprocess.check_output([node, npm_cli, '--version'], env=env, text=True).strip()
    commands = []
    for label, command in [('npm-ci', [node, npm_cli, 'ci', '--include=dev', '--ignore-scripts', '--no-audit', '--no-fund']),
                           ('npm-build', [node, npm_cli, '--ignore-scripts', 'run', 'build'])]:
        started = time.monotonic()
        with (work / (label + '.log')).open('wb') as log:
            result = subprocess.run(command, cwd=frontend, env=env, stdout=log, stderr=subprocess.STDOUT,
                                    timeout=600, check=False)
        require(result.returncode == 0, label + ' failed; preserve isolated log and failed context for review')
        commands.append({'step': label, 'arguments': command[2:], 'exit_code': result.returncode,
                         'duration_seconds': round(time.monotonic() - started, 3),
                         'log_sha256': sha((work / (label + '.log')).read_bytes())})
    # Build may create only disposable artifacts in work; immutable inputs must stay exact.
    require(all(sha((frontend / p.removeprefix('frontend/')).read_bytes()) == h for p, h in inputs.items()),
            'npm or build mutated a committed frontend input')
    output = frontend / 'dist'; require(output.is_dir() and not output.is_symlink(), 'No public frontend build')
    built = regular_files(output)
    require('index.html' in built and any(p.startswith('assets/') and p.endswith('.js') for p in built),
            'Missing HTML/JS build entry')
    require(all(PurePosixPath(p).suffix.lower() in {'.html', '.js', '.css', '.svg', '.woff', '.woff2', '.png', '.jpg', '.jpeg', '.webp', '.ico'}
                for p in built), 'Unexpected build output type, source map or config denied')
    require(built != accepted['served_ui'], 'Browser output unchanged from accepted UI')
    shutil.copytree(output, context / 'browser-dist')
    require(regular_files(context / 'browser-dist') == built, 'Copied browser output differs')
    provenance = {'schema': 'savia-immutable-browser-build/v1', 'git_head': head, 'git_tree': tree,
        'created_at_utc': datetime.now(timezone.utc).isoformat(), 'build_inputs': inputs,
        'package_lock_sha256': inputs['frontend/package-lock.json'],
        'toolchain': {'node_version': node_version, 'npm_version': npm_version,
                     'node_binary_sha256': sha(args.node.read_bytes()), 'npm_cli_sha256': sha(args.npm_cli.read_bytes())},
        'commands': commands, 'isolated_empty_npm_config': True, 'inherited_vite_environment': False,
        'node_env': 'production', 'dev_dependencies_explicitly_included_for_compilation': True,
        'frozen_original_media_git_hashes': frozen_media, 'frozen_full_deck_git_hashes': frozen_deck,
        'built_public_files': built, 'source_maps': False, 'provider_calls': 0, 'docker_built': False, 'deployed': False}
    provenance_sha = save(context / 'browser-build-provenance.json', provenance)
    components = deepcopy(accepted['manifest']['components'])
    for name in ('application', 'analytics_cli'):
        components[name].update({'git_head': head, 'git_tree': tree})
    browser_component = {'source': head, 'git_tree': tree, 'public_files': len(built),
                         'build_provenance_sha256': provenance_sha,
                         'scope': 'fresh isolated locked public frontend build; no new live playback acceptance'}
    components['browser_build'] = browser_component
    manifest.update({'schema': 'savia-public-rc-components/v2', 'retained_image': BASE_IMAGE,
        'components': components, 'predecessor_components': accepted['manifest']['components'],
        'dated_voice_transport_predecessor': {'git_head': NATIVE_HEAD,
            'critical_server_sources': {p: old[p] for p in CRITICAL},
            'scope': 'unchanged dated server/native transport; reviewed new browser ACK recovery needs separate qualification'}})
    source_sha = save(app / 'source-manifest.json', manifest)
    require(regular_files(app) == {**future, 'source-manifest.json': source_sha,
                                 'portal-source-manifest.json': sha(portal_bytes)}, 'Unexpected Docker application file')
    expected = {'schema': 'savia-ui-successor-guards/v1', 'accepted_head': ACCEPTED_HEAD,
        'accepted_source_manifest_sha256': accepted['source_manifest_sha256'], 'old_sources': old,
        'old_browser': accepted['served_ui'], 'native': accepted['retained_runtime_hashes'],
        'final_head': head, 'final_tree': tree, 'final_source_manifest_sha256': source_sha, 'new_sources': future,
        'new_browser': built, 'portal_head': ACCEPTED_HEAD, 'portal': portal,
        'portal_source_manifest_sha256': sha(portal_bytes), 'retained_pitch_media': retained_media,
        'critical_server_sources': {p: old[p] for p in CRITICAL},
        'retained_portal_component': components['portal'], 'browser_component': browser_component,
        'build_provenance_sha256': provenance_sha}
    expected_sha = save(context / 'expected-ui-runtime.json', expected)
    verifier = Path(__file__).with_name('verify_ui_layer.py'); shutil.copyfile(verifier, context / verifier.name)
    docker = f'''FROM {BASE_IMAGE}
USER root
COPY expected-ui-runtime.json verify_ui_layer.py browser-build-provenance.json /tmp/ui-release/
RUN python /tmp/ui-release/verify_ui_layer.py before {expected_sha}
RUN python /tmp/ui-release/verify_ui_layer.py remove-ui {expected_sha}
COPY application/ /srv/savia/
COPY browser-dist/ /srv/savia/frontend/dist/
RUN python /tmp/ui-release/verify_ui_layer.py after {expected_sha}
LABEL io.savia.source-revision="{head}" \\
      io.savia.browser-source="{head}" \\
      io.savia.successor.scope="reviewed-ui-ack-rejection-recovery"
'''
    (context / 'Dockerfile').write_text(docker, encoding='utf-8', newline='\n')
    (context / '.dockerignore').write_text(
        '**\n!Dockerfile\n!expected-ui-runtime.json\n!verify_ui_layer.py\n!browser-build-provenance.json\n'
        '!application/\n!application/**\n!browser-dist/\n!browser-dist/**\n'
        '**/node_modules\n**/node_modules/**\n**/__pycache__\n**/__pycache__/**\n**/*.pyc\n**/*.tsbuildinfo\n'
        '**/private\n**/private/**\n**/.overlay\n**/.overlay/**\n**/.env*\n'
        'application/**/dist\napplication/**/dist/**\napplication/**/*.sqlite*\napplication/**/*.pem\napplication/**/*.key\n',
        encoding='utf-8', newline='\n')
    receipt = {'schema': 'savia-ui-successor-preparation/v1', 'git_head': head, 'git_tree': tree,
        'context': str(context), 'isolated_frontend_work': str(work), 'base_image': BASE_IMAGE,
        'changed_exported_sources': sorted(ALLOWED_DELTA), 'source_files': 183,
        'new_browser_files': len(built), 'old_browser_files': 22, 'native_files': 4,
        'portal_files_retained': 28, 'pitch_files_retained': 12, 'pitch_media_files_retained': 16,
        'source_manifest_sha256': source_sha, 'portal_source_manifest_sha256': sha(portal_bytes),
        'build_provenance_sha256': provenance_sha, 'expected_guards_sha256': expected_sha,
        'layer_verifier_sha256': sha(verifier.read_bytes()), 'prepare_helper_sha256': sha(Path(__file__).read_bytes()),
        'dockerfile_sha256': sha((context / 'Dockerfile').read_bytes()),
        'frontend_built': True, 'docker_built': False, 'deployed': False, 'provider_calls': 0,
        'runtime_configuration': 'inherited unchanged; helper supplies no machine update or deployment configuration'}
    save(context / 'preparation-receipt.json', receipt)
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--node', type=Path, required=True)
    parser.add_argument('--npm-cli', type=Path, required=True)
    parser.add_argument('--reviewed-ui-delta', action='store_true')
    parser.add_argument('--build-public-frontend', action='store_true')
    print(json.dumps(prepare(parser.parse_args()), indent=2))
