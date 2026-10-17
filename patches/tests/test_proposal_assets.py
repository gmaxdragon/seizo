"""Exercise the exact historical launcher, not merely a repaired repository copy."""
import base64
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from core.release_assets import ensure_assets, FILES

APP=Path(__file__).resolve().parents[1]
REPO=Path(os.environ.get('SEIZO_RELEASE_REPO','/nonexistent'))

class FixedAssetEnvelope(unittest.TestCase):
    def setUp(self):
        self.bundle=json.loads((APP/'web/assets/release_assets_v11.json').read_text(encoding='utf-8'))
    def stage(self, root, bundle):
        directory=root/'web/assets';directory.mkdir(parents=True)
        (directory/'release_assets_v11.json').write_text(json.dumps(bundle))
        return directory
    def test_exact_reconstruction_and_no_rewrite_on_second_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);directory=self.stage(root,self.bundle)
            self.assertEqual(set(ensure_assets(root)),set(FILES))
            for name in FILES:self.assertEqual((directory/name).read_bytes(),(APP/'web/assets'/name).read_bytes())
            self.assertEqual(ensure_assets(root),[])
    def test_corrupt_envelope_does_not_write_any_assets(self):
        value=copy.deepcopy(self.bundle);value['files']['room_wood.png']['sha256']='0'*64
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);directory=self.stage(root,value)
            with self.assertRaises(ValueError):ensure_assets(root)
            self.assertTrue(all(not (directory/name).exists() for name in FILES))
    def test_arbitrary_output_path_rejected(self):
        value=copy.deepcopy(self.bundle);value['files']['../../data/policy.npz']=value['files'].pop('room_wood.png')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.stage(root,value)
            with self.assertRaises(ValueError):ensure_assets(root)
            self.assertFalse((root/'data').exists())
    def test_oversized_or_noninteger_declared_size_rejected(self):
        for size in (True,750001,'400'):
            value=copy.deepcopy(self.bundle);value['files']['camera_lod.json.gz']['size']=size
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);self.stage(root,value)
                with self.subTest(size=size),self.assertRaises(ValueError):ensure_assets(root)

@unittest.skipUnless((REPO/'release-legacy-updater.py').exists(),'Original updater compatibility tested in release CI')
class OriginalInstalledUpdater(unittest.TestCase):
    def test_unmodified_original_installs_v11_and_preserves_model_and_assets(self):
        spec=importlib.util.spec_from_file_location('original_installed_updater',REPO/'release-legacy-updater.py')
        u=importlib.util.module_from_spec(spec);spec.loader.exec_module(u)
        manifest=json.loads((REPO/'release-candidate-manifest.json').read_text())
        u.validated_manifest(manifest)
        contents={v['url']:(REPO/'patches'/name).read_bytes() for name,v in manifest['patches'].items()}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'Studio';root.mkdir();(root/'app.py').write_bytes(b'old app')
            checkpoint=root/'data/camera_views_v9/policy.npz';checkpoint.parent.mkdir(parents=True);checkpoint.write_bytes(b'existing training must stay')
            with patch.object(u,'INSTALL',root),patch.object(u,'RELEASE_FILE',root/'.seizo_release.json'), \
                 patch.object(u,'already_running',return_value=False),patch.object(u,'urlbytes',side_effect=lambda url,*_:contents[url]):
                self.assertTrue(u.update_from_manifest(manifest))
                self.assertFalse(u.update_from_manifest(manifest))
            self.assertEqual(checkpoint.read_bytes(),b'existing training must stay')
            ensure_assets(root)
            for name in FILES:self.assertEqual((root/'web/assets'/name).read_bytes(),(APP/'web/assets'/name).read_bytes())
            self.assertIn('from core.release_assets import ensure_assets',(root/'app.py').read_text())
            self.assertIn('seizo-windows-render-v13',(root/'app.py').read_text())
            self.assertLessEqual(len(manifest['patches']),80)

if __name__=='__main__':unittest.main()
