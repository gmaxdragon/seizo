"""Credential persistence is tested with an injected fake protector, not fake
claims that Linux provides Windows DPAPI. One native Windows round-trip test
runs only on Windows. The fake protector is never used by the application.
"""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.key_store import KeyStore, MAGIC, WindowsDPAPI, validate_key
from core.cloud import HackClubPlanner


class FakeProtector:
    # Test fixture only. Intentionally not called encryption.
    def protect(self, data):return b'FAKE-FOR-TESTS:'+bytes(x^173 for x in data)
    def unprotect(self, data):
        if not data.startswith(b'FAKE-FOR-TESTS:'):raise ValueError('fixture failure')
        return bytes(x^173 for x in data[15:])


class KeyStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.folder=Path(self.tmp.name)
        self.store=KeyStore(self.folder,FakeProtector())
        self.key='not-a-real-hackclub-api-key-12345'
    def tearDown(self):self.tmp.cleanup()
    def test_empty_store_no_file(self):
        self.assertEqual(self.store.load(),('',''));self.assertFalse(self.store.path.exists())
    def test_round_trip_and_no_plaintext(self):
        self.store.save(self.key);raw=self.store.path.read_bytes()
        self.assertNotIn(self.key.encode(),raw);self.assertTrue(raw.startswith(MAGIC))
        self.assertEqual(self.store.load()[0],self.key)
    def test_new_process_object_loads_same_shared_location(self):
        a=HackClubPlanner(store=self.store);a.set_key(self.key)
        b=HackClubPlanner(store=KeyStore(self.folder,FakeProtector()))
        self.assertTrue(b.status()['persisted']);self.assertEqual(b.reveal_key()['key'],self.key)
        self.assertFalse(b.status()['verified'])
    def test_global_delete_propagates_to_other_instance(self):
        a=HackClubPlanner(store=self.store);a.set_key(self.key)
        b=HackClubPlanner(store=KeyStore(self.folder,FakeProtector()))
        a.clear_key();self.assertFalse(b.status()['enabled']);self.assertEqual(b.reveal_key()['key'],'')
    def test_replace_seen_by_other_instance(self):
        a=HackClubPlanner(store=self.store);a.set_key(self.key)
        b=HackClubPlanner(store=KeyStore(self.folder,FakeProtector()))
        k='different-not-real-hackclub-key';a.set_key(k)
        self.assertEqual(b.reveal_key()['key'],k)
    def test_replacing_clears_verification(self):
        a=HackClubPlanner(store=self.store);a.set_key(self.key);a._verified=True
        a.set_key('second-not-real-hackclub-key');self.assertFalse(a.status()['verified'])
    def test_status_contains_no_secret(self):
        import json
        a=HackClubPlanner(store=self.store);a.set_key(self.key)
        self.assertNotIn(self.key,json.dumps(a.status()))
    def test_bad_replacement_preserves_existing(self):
        a=HackClubPlanner(store=self.store);a.set_key(self.key);before=self.store.path.read_bytes()
        with self.assertRaises(ValueError):a.set_key('bad')
        self.assertEqual(before,self.store.path.read_bytes());self.assertEqual(a.reveal_key()['key'],self.key)
    def test_write_failure_preserves_existing(self):
        a=HackClubPlanner(store=self.store);a.set_key(self.key);before=self.store.path.read_bytes()
        with patch('core.key_store.os.replace',side_effect=OSError('blocked')):
            with self.assertRaises(ValueError):a.set_key('another-not-a-real-api-key')
        self.assertEqual(before,self.store.path.read_bytes());self.assertEqual(a.reveal_key()['key'],self.key)
        self.assertEqual(list(self.folder.glob('*.tmp')),[])
    def test_failed_delete_is_not_reported_as_success(self):
        a=HackClubPlanner(store=self.store);a.set_key(self.key)
        with patch.object(self.store,'delete',side_effect=OSError('blocked')):
            with self.assertRaises(ValueError):a.clear_key()
        self.assertTrue(a.status()['enabled'])
    def test_corrupt_store_does_not_crash_app_or_erase_file(self):
        self.store.path.write_bytes(b'bad-data')
        a=HackClubPlanner(store=self.store)
        self.assertFalse(a.status()['enabled']);self.assertTrue(a.status()['storage_error'])
        self.assertEqual(self.store.path.read_bytes(),b'bad-data')
        a.set_key(self.key);self.assertTrue(a.status()['enabled'])
    def test_unreadable_protection_recovers_by_replacement(self):
        self.store.path.write_bytes(MAGIC+b'some-other-user-encrypted-data')
        a=HackClubPlanner(store=self.store);self.assertTrue(a.status()['storage_error'])
        a.clear_key();self.assertFalse(self.store.path.exists())
    def test_rejects_oversized_blob(self):
        self.store.path.write_bytes(MAGIC+b'x'*65536)
        with self.assertRaises(ValueError):self.store.load()
    def test_ascii_and_paste_validation(self):
        self.assertEqual(validate_key('  '+self.key+'  '),self.key)
        for key in [None,'short','Bearer '+self.key,self.key+'\nother',self.key+'é','"'+self.key+'"']:
            with self.assertRaises(ValueError):validate_key(key)
    def test_win_api_current_user_flag_and_no_plaintext_fallback(self):
        import inspect
        code=inspect.getsource(WindowsDPAPI)
        self.assertIn('0x1, ctypes.byref(out)',code)
        self.assertIn("ctypes.WinDLL('crypt32'",code)
        self.assertNotIn('0x4, ctypes.byref(out)',code)
    @unittest.skipIf(os.name=='nt','This verifies the non-Windows fallback')
    def test_no_plaintext_non_windows(self):
        s=KeyStore(self.folder);a=HackClubPlanner(store=s)
        r=a.set_key(self.key);self.assertFalse(r['persisted']);self.assertFalse(s.path.exists())
        self.assertEqual(a.reveal_key()['key'],self.key)
    @unittest.skipUnless(os.name=='nt','Native Windows DPAPI cannot execute in the Linux test container')
    def test_native_windows_dpapi_roundtrip(self):
        s=KeyStore(self.folder,WindowsDPAPI());s.save(self.key)
        self.assertEqual(KeyStore(self.folder,WindowsDPAPI()).load()[0],self.key)
        self.assertNotIn(self.key.encode(),s.path.read_bytes());s.delete()

if __name__=='__main__':unittest.main()
