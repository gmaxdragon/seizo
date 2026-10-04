import pathlib
import tempfile
import unittest

from seizo_core.auto_gate import readiness, preview_skill
from seizo_core.workspace_limits import WorkspaceGuard
from seizo_core.skill import SCHEMA


class AutoGateTests(unittest.TestCase):
    def make_guard(self):
        td=tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        return WorkspaceGuard(pathlib.Path(td.name)/"limits.json")

    def ready_guard(self):
        g=self.make_guard()
        g.set_reference_here()
        g.start_calibration()
        for axis in ("X","Y","Z"):
            g.config["limits"][axis]["min"]=-10.0
            g.config["limits"][axis]["max"]=10.0
        g.complete_calibration()
        return g

    def test_readiness_lists_concrete_blockers(self):
        r=readiness(
            armed=False,
            physical={"base":"pass"},
            camera_overhead=True,
            camera_wrist=False,
            workspace={"reference_valid":False,"configured":False,"calibrating":False},
        )
        self.assertFalse(r["ready_for_planning"])
        self.assertIn("ARM_MANUAL",r["blockers"])
        self.assertIn("HARDWARE_TEST",r["blockers"])
        self.assertIn("TWO_CAMERAS",r["blockers"])
        self.assertIn("HOME_REFERENCE",r["blockers"])
        self.assertIn("TRAVEL_LIMITS",r["blockers"])
        self.assertFalse(r["automatic_motion_enabled"])

    def test_arm_is_always_first_when_disarmed(self):
        r=readiness(
            armed=False,
            physical={},
            camera_overhead=False,
            camera_wrist=False,
            workspace={"reference_valid":False,"configured":False,"calibrating":False},
        )
        self.assertEqual(r["next_step"],"ARM_MANUAL")

    def test_arm_is_the_next_step_after_hardware_and_cameras(self):
        r=readiness(
            armed=False,
            physical={k:"pass" for k in ("base","y","z","gripper","wrist")},
            camera_overhead=True,
            camera_wrist=True,
            workspace={"reference_valid":False,"configured":False,"calibrating":False},
        )
        self.assertEqual(r["next_step"],"ARM_MANUAL")
        self.assertFalse(r["ready_for_planning"])

    def test_full_gate_can_be_ready_for_planning_without_enabling_motion(self):
        r=readiness(
            armed=True,
            physical={k:"pass" for k in ("base","y","z","gripper","wrist")},
            camera_overhead=True,
            camera_wrist=True,
            workspace={"reference_valid":True,"configured":True,"calibrating":False},
        )
        self.assertTrue(r["ready_for_planning"])
        self.assertEqual(r["blockers"],[])
        self.assertFalse(r["automatic_motion_enabled"])
        self.assertEqual(r["next_step"],"PLANNER_READY")

    def test_preview_blocks_when_gate_is_not_ready(self):
        g=self.ready_guard()
        skill={
            "schema":SCHEMA,"name":"demo","created_utc":"now","source_mode":"test",
            "actions":[{"type":"relative_move","axis":"X","delta_mm":1.0,
                        "feed_mm_min":50,"label":"x","source_key":"d"}],
        }
        result=preview_skill(skill,g,{"blockers":["TWO_CAMERAS"]})
        self.assertFalse(result["ready"])
        self.assertFalse(result["physical_motion_executed"])

    def test_preview_rejects_out_of_workspace_path(self):
        g=self.ready_guard()
        g.position["X"]=9.0
        skill={
            "schema":SCHEMA,"name":"demo","created_utc":"now","source_mode":"test",
            "actions":[{"type":"relative_move","axis":"X","delta_mm":2.0,
                        "feed_mm_min":50,"label":"x","source_key":"d"}],
        }
        result=preview_skill(skill,g,{"blockers":[]})
        self.assertFalse(result["ready"])
        self.assertEqual(result["blockers"],["WORKSPACE_PATH"])
        self.assertFalse(result["physical_motion_executed"])

    def test_preview_returns_predicted_end_only(self):
        g=self.ready_guard()
        skill={
            "schema":SCHEMA,"name":"demo","created_utc":"now","source_mode":"test",
            "actions":[
                {"type":"relative_move","axis":"X","delta_mm":1.0,
                 "feed_mm_min":50,"label":"x","source_key":"d"},
                {"type":"relative_move","axis":"Y","delta_mm":-2.0,
                 "feed_mm_min":50,"label":"y","source_key":"s"},
            ],
        }
        result=preview_skill(skill,g,{"blockers":[]})
        self.assertTrue(result["ready"])
        self.assertEqual(result["predicted_end_position_mm"],{"X":1.0,"Y":-2.0,"Z":0.0})
        self.assertFalse(result["automatic_motion_enabled"])
        self.assertFalse(result["physical_motion_executed"])


if __name__=="__main__":
    unittest.main()
