"""Offline rejection and exact-config preservation checks; never calls a provider."""
import copy, json, unittest
from unittest.mock import patch
from release_common import *
from promote_successor import preserved_config, config_guard
from verify_server_layer import guard

def fixture():
    base = read_json(BASE_CONTEXT / 'expected-ui-runtime.json')
    old = base['new_sources']; new = dict(old); new[CHANGED_SOURCE] = CONVERSATION_SHA;new[GRAPH_SOURCE] = GRAPH_SHA
    return {'schema':'savia-card-admission-source-guards/v1','base_image':BASE_IMAGE,
        'accepted_head':BASE_HEAD,'accepted_tree':BASE_TREE,'accepted_source_manifest_sha256':BASE_MANIFEST_SHA,
        'final_head':FINAL_HEAD,'final_tree':FINAL_TREE,
        'final_source_manifest_sha256':'a'*64,'old_sources':old,'new_sources':new,
        'old_browser':base['new_browser'],'new_browser':dict(base['new_browser']),
        'native':base['native'],'portal_head':PORTAL_HEAD,'portal':base['portal'],
        'portal_source_manifest_sha256':PORTAL_MANIFEST_SHA,'retained_pitch_media':base['retained_pitch_media'],
        'critical_unchanged':{p:old[p] for p in ['frontend/server/voice.py','deploy/rc/run.py']},
        'browser_component':base['browser_component'],'retained_portal_component':base['retained_portal_component'],
        'build_provenance_sha256':BUILD_PROVENANCE_SHA}

class OfflineTests(unittest.TestCase):
    def test_exact_source_and_graph_current_predecessor_accepted(self):
        descriptor_guard(fixture()); guard(fixture())
    def test_third_exported_source_rejected(self):
        value=fixture();value['new_sources']['frontend/server/voice.py']='e'*64
        for check in [descriptor_guard,guard]:
            with self.assertRaises(RuntimeError):check(value)
    def test_browser_recompile_or_inventory_change_rejected(self):
        for mutation in ['hash','add','remove']:
            value=fixture()
            if mutation=='hash':value['new_browser']['index.html']='e'*64
            elif mutation=='add':value['new_browser']['extra.js']='e'*64
            else:value['new_browser'].pop('index.html')
            for check in [descriptor_guard,guard]:
                with self.assertRaises(RuntimeError):check(value)
    def test_old_44bc_image_rejected(self):
        value=fixture();value['base_image']='registry.fly.io/savia-rc-2026@sha256:44bc554cd82ad62db51d536d580df248cbb188d24732e7ec1ed8133617c632a0'
        for check in [descriptor_guard,guard]:
            with self.assertRaises(RuntimeError):check(value)
    def test_portal_or_native_inventory_change_rejected(self):
        for key in ['portal','native']:
            value=fixture();value[key]=dict(value[key]);value[key].pop(next(iter(value[key])))
            for check in [descriptor_guard,guard]:
                with self.assertRaises(RuntimeError):check(value)
    def test_full_configuration_is_deepcopied_image_only(self):
        config={'image':BASE_IMAGE,'env':{'PRIVATE':'fictional-mock'},'init':{'cmd':['start']},
            'services':[{'ports':[{'port':443}]}],'guest':{'cpu_kind':'shared','cpus':2,'memory_mb':4096},
            'mounts':[{'path':'/data','volume':'mock-preserved-volume'}],'metadata':{'keep':'exact'},'restart':{'policy':'always'}}
        original=copy.deepcopy(config);target='registry.fly.io/savia-rc-2026@sha256:'+'f'*64
        wanted=preserved_config(config,target)
        self.assertEqual(config,original);self.assertEqual({k:v for k,v in wanted.items() if k!='image'},{k:v for k,v in config.items() if k!='image'})
        wanted['init']['cmd'].append('changed');self.assertEqual(config,original)
        with self.assertRaises(RuntimeError):preserved_config(config,BASE_IMAGE)
    def test_wrong_guest_or_missing_complete_config_rejected(self):
        config={'image':BASE_IMAGE,'env':{},'init':{},'services':[],'guest':{'cpu_kind':'shared','cpus':2,'memory_mb':4096},'mounts':[{'path':'/data','volume':'mock'}]}
        for mutation in ['cpu','volume','env']:
            bad=copy.deepcopy(config)
            if mutation=='cpu':bad['guest']['cpu_kind']='performance'
            elif mutation=='volume':bad['mounts'][0]['path']='/replacement'
            else:bad.pop('env')
            with self.assertRaises((RuntimeError,KeyError)):config_guard(bad)
    def test_no_import_network_or_subprocess_action(self):
        with patch('subprocess.check_output',side_effect=AssertionError('No subprocess allowed')),patch('subprocess.run',side_effect=AssertionError('No subprocess allowed')):
            import importlib,release_common,promote_successor,qualify_runtime,prepare_native_binding,prepare_server_successor,verify_public_assets,verify_server_layer
            for module in [release_common,promote_successor,qualify_runtime,prepare_native_binding,prepare_server_successor,verify_public_assets,verify_server_layer]:importlib.reload(module)

if __name__=='__main__':unittest.main()
