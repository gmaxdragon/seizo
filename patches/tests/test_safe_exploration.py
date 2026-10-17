"""Non-hardware regression tests for constrained simulator exploration."""
import unittest
import numpy as np
from core.view_world import ViewWorld

class SafeExploration(unittest.TestCase):
    def test_repeated_table_guard_stops_without_penetrating(self):
        w=ViewWorld(seed=42,task='reach',view_mode='two',camera_config={'profile':'fixed'})
        try:
            danger=np.array([[-.261,-.998,-1.,.481,.22]])
            guards=0
            for k in range(32):
                _,reward,term,trunc,info=w.step(danger)
                if w.guard_reason[0]:
                    guards+=1
                    self.assertGreaterEqual(w.table_clearance(0),.00149)
                    self.assertEqual(info['failure_reason'][0],'unsafe_action')
                    self.assertLessEqual(float(reward[0]),-8.)
                    if guards<12:self.assertFalse(bool(info['invalid_physics'][0]))
                if term[0] or trunc[0]:break
            self.assertGreater(guards,0)
            self.assertGreater(k+1,3,'One rejected action must not immediately end the attempt')
            self.assertTrue(bool(term[0]))
            self.assertEqual(guards,12)
        finally:w.close()

    def test_healthy_zero_actions_survive(self):
        w=ViewWorld(seed=42,task='reach',view_mode='two',camera_config={'profile':'fixed'})
        try:
            for _ in range(8):
                _,_,term,trunc,info=w.step(np.zeros((1,5)))
                self.assertFalse(bool(term[0] or trunc[0]))
                self.assertFalse(bool(info['invalid_physics'][0]))
                self.assertEqual(w.guard_reason[0],'')
            self.assertEqual(w.consecutive_guard_rejections[0],0)
        finally:w.close()

if __name__=='__main__':unittest.main()
