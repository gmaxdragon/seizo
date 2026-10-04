import pathlib
import tempfile
import unittest

from seizo_core.workspace_limits import WorkspaceGuard, WorkspaceLimitError
from seizo_core.skill import validate_skill, SCHEMA

ROOT=pathlib.Path(__file__).resolve().parents[1]


class WorkspaceLimitTests(unittest.TestCase):
    def make_guard(self):
        td=tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        return WorkspaceGuard(pathlib.Path(td.name)/"limits.json")

    def test_motion_requires_reference(self):
        g=self.make_guard()
        with self.assertRaises(WorkspaceLimitError):
            g.predict("X",1.0)

    def test_calibration_requires_reference(self):
        g=self.make_guard()
        with self.assertRaises(WorkspaceLimitError):
            g.start_calibration()

    def test_capture_complete_and_block(self):
        g=self.make_guard()
        g.set_reference_here()
        g.start_calibration()
        for axis in ("X","Y","Z"):
            g.position[axis]=-2.0
            g.set_limit_here(axis,"min")
            g.position[axis]=2.0
            g.set_limit_here(axis,"max")
            g.position[axis]=0.0
        g.complete_calibration()
        self.assertTrue(g.configured())
        self.assertAlmostEqual(g.predict("X",1.5),1.5)
        with self.assertRaises(WorkspaceLimitError):
            g.predict("X",2.5)

    def test_replay_preview_blocks_before_motion(self):
        g=self.make_guard()
        g.set_reference_here()
        g.start_calibration()
        for axis in ("X","Y","Z"):
            g.config["limits"][axis]["min"]=-2.0
            g.config["limits"][axis]["max"]=2.0
        g.complete_calibration()
        with self.assertRaises(WorkspaceLimitError):
            g.preview_sequence([("X",1.0),("X",1.5)])

    def test_reference_not_persisted(self):
        g=self.make_guard()
        g.set_reference_here()
        self.assertTrue(g.reference_valid)
        g2=WorkspaceGuard(g.path)
        self.assertFalse(g2.reference_valid)

    def test_home_must_be_strictly_inside_each_limit_range(self):
        g=self.make_guard()
        g.set_reference_here()
        g.start_calibration()
        for axis in ("X","Y","Z"):
            g.config["limits"][axis]["min"]=0.0
            g.config["limits"][axis]["max"]=2.0
        self.assertFalse(g.configured())
        with self.assertRaisesRegex(WorkspaceLimitError,"strictly inside"):
            g.complete_calibration()

    def test_skill_preserves_direction_metadata(self):
        skill=validate_skill({
            "schema":SCHEMA,
            "name":"test",
            "created_utc":"now",
            "source_mode":"phone-record",
            "metadata":{"invert":{"X":True,"Y":False,"Z":True},
                        "workspace_reference":"session-home-v1",
                        "start_position":{"X":0.0,"Y":1.0,"Z":-1.0}},
            "actions":[{"type":"relative_move","axis":"X","delta_mm":1.0,
                        "feed_mm_min":50,"label":"x","source_key":"d"}],
        })
        self.assertEqual(skill["metadata"]["invert"],{"X":True,"Y":False,"Z":True})
        self.assertEqual(skill["metadata"]["workspace_reference"],"session-home-v1")
        self.assertEqual(skill["metadata"]["start_position"],{"X":0.0,"Y":1.0,"Z":-1.0})


class PhoneWorkspaceStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.phone=(ROOT/"scripts/seizo_phone_control.py").read_text()

    def test_phone_exposes_only_setup_workspace_routes(self):
        for token in [
            'self.path == "/auto/home"',
            'self.path == "/auto/cal-start"',
            'self.path == "/auto/cal-done"',
            'self.path == "/auto/cal-cancel"',
            'self.path == "/auto/limit"',
            'self.path == "/auto/limits-clear"',
            'self.path == "/auto/dry-run"',
        ]:
            self.assertIn(token,self.phone)
        self.assertNotIn('self.path == "/auto/run"',self.phone)

    def test_manual_moves_track_workspace_after_reference(self):
        self.assertIn("self.workspace.predict(axis, physical_delta)",self.phone)
        self.assertIn("self.workspace.commit(axis, physical_delta)",self.phone)
        self.assertIn("physical_delta = sign * rr.STEPPER_STEP_MM[axis]",self.phone)

    def test_stop_invalidates_session_reference(self):
        close=self.phone[self.phone.index("def _close_locked"):self.phone.index("def arm(self)")]
        self.assertIn("self.workspace.clear_reference()",close)

    def test_limit_finish_requires_return_near_home(self):
        block=self.phone[self.phone.index("def finish_limit_calibration"):self.phone.index("def cancel_limit_calibration")]
        self.assertIn("Return all axes to HOME before finishing",block)
        self.assertIn("self.workspace.complete_calibration()",block)

    def test_automatic_planner_is_preview_only(self):
        self.assertIn("preview_skill",self.phone)
        self.assertIn("automatic_motion_enabled", (ROOT/"seizo_core/auto_gate.py").read_text())
        self.assertNotIn('self.path == "/auto/run"',self.phone)


if __name__=="__main__":
    unittest.main()
