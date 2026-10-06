"""Offline regression tests. All Fly mutations/queries are mocked."""
import copy, json, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import promote_successor as promoter
from successor_common import BASE_IMAGE, DESCRIPTOR_SHA, MACHINE, load_context

TARGET = 'registry.fly.io/savia-rc-2026@sha256:' + '1' * 64

class Helpers(unittest.TestCase):
    def test_prepared_descriptor_and_complete_local_maps(self):
        expected, _ = load_context(DESCRIPTOR_SHA)
        self.assertEqual(len(expected['new_browser']),21)
        self.assertNotEqual(expected['new_browser'],expected['old_browser'])

    def test_unreviewed_descriptor_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'Exact reviewed'):
            load_context('0' * 64)

    def exercise_promotion(self, before_change=None, after_change=None):
        with tempfile.TemporaryDirectory(prefix='savia-ack-helper-offline-') as directory:
            work=Path(directory); private=work/'private'; private.mkdir()
            cfg={'image':BASE_IMAGE,'guest':{'cpus':2,'memory_mb':4096},'mounts':[{'path':'/data','volume':'fixture-volume'}],
                 'env':{'FAKE_PRIVATE_MARKER':'offline fixture only'},'services':[{'ports':[{'port':443}]}],
                 'metadata':{'preserve':'all fields'},'restart':{'policy':'always'}}
            accepted={'id':MACHINE,'state':'started','config':cfg}
            snapshot=private/'accepted-44bc-machine.private.json'
            snapshot.write_text(json.dumps(accepted),encoding='utf-8')
            before=copy.deepcopy(accepted)
            if before_change: before_change(before)
            wanted=copy.deepcopy(cfg); wanted['image']=TARGET
            after={'id':MACHINE,'state':'started','config':copy.deepcopy(wanted)}
            if after_change: after_change(after)
            args=['promote_successor.py','promote','--image',TARGET,'--accepted-config',str(snapshot),
                  '--descriptor-sha',DESCRIPTOR_SHA,'--root-go','--frozen-cohort-complete']
            with patch.object(promoter,'PRIVATE',private), patch.object(promoter,'CONTEXT',work), \
                 patch.object(promoter,'load_context',return_value=({},{})), \
                 patch.object(promoter,'machine',side_effect=[before,after]), \
                 patch.object(promoter.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='',stderr='')) as update, \
                 patch('sys.argv',args), patch('builtins.print'):
                failure=None
                try: promoter.main()
                except RuntimeError as error: failure=str(error)
                if before_change:
                    self.assertEqual(update.call_count,0)
                    self.assertFalse((private/'successor-promote-config.private.json').exists())
                else:
                    self.assertEqual(update.call_count,1)
                    self.assertEqual(json.loads((private/'successor-promote-config.private.json').read_text()),wanted)
                    self.assertEqual(update.call_args.args[0][:4],['flyctl.exe','machine','update',MACHINE])
                self.assertEqual((work/'promotion-verification.json').exists(),failure is None)
                return failure

    def test_image_only_update_keeps_complete_config(self):
        self.assertIsNone(self.exercise_promotion())

    def test_config_drift_denies_before_update(self):
        failure=self.exercise_promotion(before_change=lambda m:m['config']['env'].update(FAKE_PRIVATE_MARKER='drift'))
        self.assertIn('Complete live configuration differs',failure)

    def test_after_config_drift_never_claims_preservation(self):
        failure=self.exercise_promotion(after_change=lambda m:m['config']['metadata'].update(preserve='drift'))
        self.assertIn('Post-update full configuration differs',failure)

    def test_missing_go_denies_before_network(self):
        with patch('sys.argv',['promote_successor.py','capture','--descriptor-sha',DESCRIPTOR_SHA]), \
             patch.object(promoter,'machine') as query,patch('builtins.print'):
            with self.assertRaisesRegex(RuntimeError,'Explicit root GO'):
                promoter.main()
            query.assert_not_called()

if __name__ == '__main__':
    unittest.main()
