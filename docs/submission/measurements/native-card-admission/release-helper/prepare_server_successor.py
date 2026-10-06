"""Future OFFLINE preparation only; no Docker/npm/provider/deployment commands."""
from copy import deepcopy
from pathlib import Path
import argparse, json, re, shutil, subprocess
from release_common import *

def prepare(repo, head):
    require(head == FINAL_HEAD, 'Exact reviewed replacement source commit required')
    repo = Path(repo).resolve()
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args])
    require(git('rev-parse', '--verify', head + '^{commit}').decode().strip() == head and git('rev-parse', 'HEAD').decode().strip() == head and not git('status', '--porcelain'), 'Clean exact committed checkout required')
    tree = git('rev-parse', head + '^{tree}').decode().strip()
    old_descriptor = BASE_CONTEXT / 'expected-ui-runtime.json'
    require(digest(old_descriptor) == BASE_DESCRIPTOR_SHA, 'Reviewed current c44 descriptor changed')
    base = read_json(old_descriptor)
    require(base['final_head'] == BASE_HEAD and base['final_tree'] == BASE_TREE and base['final_source_manifest_sha256'] == BASE_MANIFEST_SHA, 'Current source identity differs')
    old = base['new_sources']
    require(len(old) == 183 and len(base['new_browser']) == 21 and len(base['native']) == 4, 'Current 183/21/4 inventories required')
    require(digest(BASE_CONTEXT / 'application/source-manifest.json') == BASE_MANIFEST_SHA and digest(BASE_CONTEXT / 'application/portal-source-manifest.json') == PORTAL_MANIFEST_SHA and digest(BASE_CONTEXT / 'browser-build-provenance.json') == BUILD_PROVENANCE_SHA, 'Current retained metadata changed')
    verify(old, BASE_CONTEXT / 'application')
    verify(base['new_browser'], BASE_CONTEXT / 'browser-dist')
    require({p.relative_to(BASE_CONTEXT / 'browser-dist').as_posix() for p in (BASE_CONTEXT / 'browser-dist').rglob('*') if p.is_file()} == set(base['new_browser']), 'Current browser inventory differs')
    future = {}
    bodies = {}
    for name, wanted in old.items():
        require(sha(git('show', BASE_HEAD + ':' + name)) == wanted, 'Current source Git/manifest congruence failed: ' + name)
        bodies[name] = git('show', head + ':' + name)
        future[name] = sha(bodies[name])
    require(tree == FINAL_TREE and {p for p in old if old[p] != future[p]} == CHANGED_SOURCES and future[CHANGED_SOURCE] == CONVERSATION_SHA and future[GRAPH_SOURCE] == GRAPH_SHA, 'Exactly reviewed conversation + generated graph must differ in the export')
    old_graph = json.loads(git('show', BASE_HEAD + ':' + GRAPH_SOURCE))
    new_graph = json.loads(bodies[GRAPH_SOURCE])
    old_graph['disputeWorkflow']['stageManifest']['sourceHashes'][CHANGED_SOURCE] = CONVERSATION_SHA
    require(old_graph == new_graph, 'Graph differs beyond exact conversation source hash refresh')
    protected = new_graph['disputeWorkflow']['stageManifest']['sourceHashes']
    require(len(protected) == 89 and all(sha(git('show', head + ':' + p)) == h for p, h in protected.items()), 'All 89 protected graph source hashes must match final committed source')
    require(not git('diff', '--name-only', BASE_HEAD, head, '--', 'docs/submission/media/'), 'Frozen original media changed')
    manifest = deepcopy(read_json(BASE_CONTEXT / 'application/source-manifest.json'))
    require(manifest['files'] == old and manifest['git_head'] == BASE_HEAD and manifest['git_tree'] == BASE_TREE, 'Current manifest fields differ')
    old_components = deepcopy(manifest['components'])
    manifest.update({'git_head': head, 'git_tree': tree, 'files': future, 'retained_image': BASE_IMAGE, 'predecessor_components': old_components})
    for component in ['application', 'analytics_cli']:
        manifest['components'][component].update({'git_head': head, 'git_tree': tree})
    require(manifest['components']['browser_build'] == old_components['browser_build'] and manifest['components']['portal'] == old_components['portal'], 'Retained provenance changed')
    output = ROOT / 'contexts' / head[:12]
    require(not output.exists(), 'Fresh preparation directory required; never replace evidence')
    app = output / 'source-review/application'
    app.mkdir(parents=True)
    for name, body in bodies.items():
        target = safe_file(app, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    portal_bytes = (BASE_CONTEXT / 'application/portal-source-manifest.json').read_bytes()
    (app / 'portal-source-manifest.json').write_bytes(portal_bytes)
    manifest_sha = write_new(app / 'source-manifest.json', manifest)
    verify(future, app)
    build = output / 'build'
    (build / 'application/frontend/server').mkdir(parents=True)
    shutil.copyfile(app / CHANGED_SOURCE, build / 'application' / CHANGED_SOURCE)
    (build / 'application/resources').mkdir()
    shutil.copyfile(app / GRAPH_SOURCE, build / 'application' / GRAPH_SOURCE)
    shutil.copyfile(app / 'source-manifest.json', build / 'application/source-manifest.json')
    expected = {'schema': 'savia-card-admission-source-guards/v1', 'base_image': BASE_IMAGE,
        'accepted_head': BASE_HEAD, 'accepted_tree': BASE_TREE, 'accepted_source_manifest_sha256': BASE_MANIFEST_SHA,
        'final_head': head, 'final_tree': tree, 'final_source_manifest_sha256': manifest_sha,
        'old_sources': old, 'new_sources': future, 'old_browser': base['new_browser'], 'new_browser': base['new_browser'],
        'native': base['native'], 'portal_head': PORTAL_HEAD, 'portal': base['portal'],
        'portal_source_manifest_sha256': PORTAL_MANIFEST_SHA, 'retained_pitch_media': base['retained_pitch_media'],
        'critical_unchanged': {p: old[p] for p in ['frontend/server/voice.py', 'deploy/rc/run.py']},
        'browser_component': old_components['browser_build'], 'retained_portal_component': old_components['portal'],
        'build_provenance_sha256': BUILD_PROVENANCE_SHA}
    descriptor_guard(expected)
    descriptor_sha = write_new(build / 'expected-server-runtime.json', expected)
    verifier = ROOT / 'verify_server_layer.py'
    shutil.copyfile(verifier, build / verifier.name)
    verifier_sha = digest(verifier)
    docker = f'''FROM {BASE_IMAGE}
USER root
COPY expected-server-runtime.json verify_server_layer.py /tmp/card-admission-release/
RUN python /tmp/card-admission-release/verify_server_layer.py before {descriptor_sha}
COPY application/frontend/server/conversation.py /srv/savia/frontend/server/conversation.py
COPY application/resources/dispute_workflow.flow.json /srv/savia/resources/dispute_workflow.flow.json
COPY application/source-manifest.json /srv/savia/source-manifest.json
RUN python /tmp/card-admission-release/verify_server_layer.py after {descriptor_sha}
LABEL io.savia.source-revision="{head}" \\
      io.savia.browser-source="{BASE_HEAD}" \\
      io.savia.successor.scope="server-native-card-admission-only"
'''
    (build / 'Dockerfile').write_text(docker, encoding='utf-8', newline='\n')
    (build / '.dockerignore').write_text('**\n!Dockerfile\n!expected-server-runtime.json\n!verify_server_layer.py\n!application/\n!application/source-manifest.json\n!application/frontend/\n!application/frontend/server/\n!application/frontend/server/conversation.py\n!application/resources/\n!application/resources/dispute_workflow.flow.json\n', encoding='utf-8', newline='\n')
    report = {'schema': 'savia-card-admission-preparation/v1', 'application_source': head, 'git_tree': tree,
        'base_image': BASE_IMAGE, 'browser_source': BASE_HEAD, 'portal_source': PORTAL_HEAD,
        'changed_exported_sources': sorted(CHANGED_SOURCES), 'source_files': 183, 'initial_browser_files': 21,
        'successor_browser_files': 21, 'native_files': 4, 'portal_files': 28, 'public_portal_files': 27,
        'pitch_delivery_files': 12, 'pitch_and_media_files': 16, 'source_manifest_sha256': manifest_sha,
        'descriptor_sha256': descriptor_sha, 'verifier_sha256': verifier_sha,
        'prepare_helper_sha256': digest(__file__), 'dockerfile_sha256': digest(build / 'Dockerfile'),
        'frontend_compilations': 0, 'docker_builds': 0, 'provider_calls': 0, 'machine_writes': 0,
        'build_context': str(build), 'scope': 'One runtime source + exact required generated graph hash refresh + source metadata overlay. Base UI/native/pitch/media bytes retained.'}
    write_new(output / 'preparation-receipt.json', report)
    return report

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--reviewed-server-and-graph-delta', action='store_true')
    args = parser.parse_args()
    require(args.reviewed_server_and_graph_delta, 'Root reviewed conversation + exact graph hash refresh required')
    print(json.dumps(prepare(args.repo, args.revision), indent=2))
