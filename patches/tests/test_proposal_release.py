"""v11 release tests: publication never grants physical execution permission."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from core.proposal_protocol import ReceiptStore, Rejected, canonical, sign
from core.proposal_bridge import ProposalBridge
from test_proposal_bridge import fixture

APP = Path(__file__).resolve().parents[1]
REPO = Path(os.environ.get('SEIZO_RELEASE_REPO', '/nonexistent'))


class PhysicalReleaseLock(unittest.TestCase):
    def test_release_label_and_visible_lock(self):
        from app import BUILD
        self.assertEqual(BUILD, 'seizo-proposal-bridge-v11')
        html = (APP/'web/index.html').read_text(encoding='utf-8')
        self.assertIn('REAL ARM LOCKED', html)
        self.assertIn('no motor connection', html)
        self.assertIn('separate real-hardware commissioning', html)

    def test_environment_cannot_enable_physical_motion(self):
        with patch.dict(os.environ, {'automatic_motion_enabled':'true', 'SEIZO_ENABLE_MOTORS':'1'}):
            state = ProposalBridge(None, None).snapshot()
        for key in ('automatic_motion_enabled','authorized','executed','physically_verified','real_pi_connected'):
            self.assertIs(state[key], False)

    def test_even_100_percent_simulation_does_not_enable_arm(self):
        p, expected = fixture()
        p['evaluation']['successes'] = 20
        expected['evaluation'] = copy.deepcopy(p['evaluation'])
        store = ReceiptStore(expected)
        p['session_id'] = store.session_id
        raw = canonical(p)
        receipt = store.receive(raw, sign(store.key, raw))
        for key in ('automatic_motion_enabled','authorized','executed','physically_verified'):
            self.assertIs(receipt[key], False)
        self.assertIn('hardware_not_commissioned', receipt['physical_blockers'])

    def test_claimed_real_test_does_not_create_execution_credential(self):
        for key in ('physical_test_passed','operator_approved','real_life_verified'):
            p, expected = fixture()
            store = ReceiptStore(expected)
            p['session_id'] = store.session_id
            p[key] = True
            raw = canonical(p)
            with self.subTest(key=key), self.assertRaises(Rejected):
                store.receive(raw, sign(store.key, raw))


@unittest.skipUnless((REPO/'seizo_updater.py').is_file(), 'Repository updater tested in release CI')
class ExistingUpdaterRelease(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('release_updater_under_test', REPO/'seizo_updater.py')
        self.updater = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.updater)
        self.manifest = json.loads((REPO/'release-candidate-manifest.json').read_text(encoding='utf-8'))

    def test_entire_new_manifest_accepted_by_existing_updated_launcher(self):
        self.updater.validated_manifest(self.manifest)
        self.assertLessEqual(len(self.manifest['patches']), 80)
        self.assertIn('core/proposal_bridge.py', self.manifest['patches'])
        self.assertIn('web/proposal_ui.js', self.manifest['patches'])

    def test_asset_fix_does_not_allow_arbitrary_new_binary_or_protected_path(self):
        for name in ('web/assets/unknown.exe','web/assets/unknown.png','data/policy.npz','../evil.py'):
            value = copy.deepcopy(self.manifest)
            value['patches'] = {name: next(iter(value['patches'].values()))}
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.updater.validated_manifest(value)

    def test_real_updater_installs_source_and_preserves_training(self):
        u = self.updater
        contents = {v['url']:(REPO/'patches'/name).read_bytes() for name,v in self.manifest['patches'].items()}
        with tempfile.TemporaryDirectory() as tmp:
            install = Path(tmp)/'Studio'; install.mkdir()
            (install/'app.py').write_bytes(b'previous application')
            sentinels = {'data/camera_views_v9/policy.npz':b'existing-trained-checkpoint',
                         'data/camera_views_v9/evaluation.json':b'existing-evaluation',
                         'data/session_state.json':b'persisted-settings',
                         '.venv/keep':b'existing-environment'}
            for name,data in sentinels.items():
                p=install/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
            with patch.object(u,'INSTALL',install), patch.object(u,'RELEASE_FILE',install/'.seizo_release.json'), \
                 patch.object(u,'already_running',return_value=False), patch.object(u,'urlbytes',side_effect=lambda url,*_:contents[url]):
                self.assertTrue(u.update_from_manifest(self.manifest))
                self.assertFalse(u.update_from_manifest(self.manifest))
                for name,data in sentinels.items():self.assertEqual((install/name).read_bytes(),data)
                for name,entry in self.manifest['patches'].items():self.assertEqual(u.sha256((install/name).read_bytes()),entry['sha256'])
                self.assertEqual(json.loads((install/'.seizo_release.json').read_text())['version'],self.manifest['version'])

    def test_download_hash_failure_changes_no_existing_code_or_checkpoint(self):
        u=self.updater
        with tempfile.TemporaryDirectory() as tmp:
            install=Path(tmp);(install/'app.py').write_bytes(b'original')
            with patch.object(u,'INSTALL',install),patch.object(u,'RELEASE_FILE',install/'.seizo_release.json'), \
                 patch.object(u,'already_running',return_value=False),patch.object(u,'urlbytes',return_value=b'corrupt'):
                with self.assertRaises(ValueError):u.update_from_manifest(self.manifest)
            self.assertEqual((install/'app.py').read_bytes(),b'original')
            self.assertFalse((install/'.seizo_release.json').exists())

if __name__ == '__main__':unittest.main()
