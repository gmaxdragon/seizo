"""Automatic comparison must not clear a user's STOP or re-use validation seeds."""
import unittest,tempfile,importlib.util
from pathlib import Path

class FreshEvidence(unittest.TestCase):
    def test_periodic_validation_not_same_seed_after_shortened_interval(self):
        source=(Path(__file__).resolve().parents[1]/'core/runner.py').read_text()
        self.assertNotIn('self.agent.steps//16000',source)
        self.assertIn('seed=secrets.randbelow(2**30)',source)

@unittest.skipUnless(importlib.util.find_spec('mujoco'),'Release Linux exercises actual camera runner')
class StopLatch(unittest.TestCase):
    def test_inline_quick_check_cannot_clear_stop(self):
        from core.view_runner import ViewRunner
        with tempfile.TemporaryDirectory() as td:
            r=ViewRunner(td);r.stop_event.set();fp=r.agent.signature()
            response=r.begin_evaluation('reach',5,_inline=True)
            self.assertTrue(response['cancelled']);self.assertTrue(r.stop_event.is_set())
            self.assertEqual(fp,r.agent.signature());self.assertIsNone(r.thread)
    def test_session_inline_check_returns_without_resetting_end_request(self):
        from core.session_runner import SessionRunner
        with tempfile.TemporaryDirectory() as td:
            r=SessionRunner(td)
            try:
                r.stop_event.set();r.end_state={'state':'requested'}
                response=r.begin_evaluation('reach',5,_inline=True)
                self.assertTrue(response['cancelled']);self.assertTrue(r.stop_event.is_set())
                self.assertEqual(r.end_state['state'],'requested')
            finally:r.shutdown()

if __name__=='__main__':unittest.main()
