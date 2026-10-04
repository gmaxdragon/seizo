import pathlib
import tempfile
import unittest

from seizo_core.guarded_executor import GuardedExecutor, AutomaticExecutionBlocked
from seizo_core.workspace_limits import WorkspaceGuard
from seizo_core.skill import SCHEMA


def skill(actions):
    return {
        "schema":SCHEMA,
        "name":"test",
        "created_utc":"now",
        "source_mode":"test",
        "actions":actions,
    }


class GuardedExecutorTests(unittest.TestCase):
    def ready_workspace(self):
        td=tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        g=WorkspaceGuard(pathlib.Path(td.name)/"limits.json")
        g.set_reference_here()
        g.start_calibration()
        for axis in ("X","Y","Z"):
            g.config["limits"][axis]["min"]=-10.0
            g.config["limits"][axis]["max"]=10.0
        g.complete_calibration()
        return g

    def move_action(self,axis="X",delta=1.0):
        return {"type":"relative_move","axis":axis,"delta_mm":delta,
                "feed_mm_min":50,"label":axis,"source_key":"d"}

    def test_no_authorization_means_zero_callbacks(self):
        calls=[]
        g=self.ready_workspace()
        ex=GuardedExecutor(g,lambda a:calls.append(("move",a)),
                           lambda a:calls.append(("servo",a)),
                           lambda a,r:{"ok":True})
        with self.assertRaisesRegex(AutomaticExecutionBlocked,"not authorized"):
            ex.execute(skill([self.move_action()]),{"ready_for_planning":True,"automatic_motion_enabled":True})
        self.assertEqual(calls,[])
        self.assertEqual(g.position["X"],0.0)

    def test_live_planning_gate_cannot_enable_physical_execution(self):
        calls=[]
        g=self.ready_workspace()
        ex=GuardedExecutor(g,lambda a:calls.append(a),lambda a:calls.append(a),lambda a,r:{"ok":True})
        with self.assertRaisesRegex(AutomaticExecutionBlocked,"remains disabled"):
            ex.execute(skill([self.move_action()]),
                       {"ready_for_planning":True,"automatic_motion_enabled":False},
                       execution_authorized=True)
        self.assertEqual(calls,[])

    def test_unready_gate_means_zero_callbacks(self):
        calls=[]
        g=self.ready_workspace()
        ex=GuardedExecutor(g,lambda a:calls.append(a),lambda a:calls.append(a),lambda a,r:{"ok":True})
        with self.assertRaisesRegex(AutomaticExecutionBlocked,"not ready"):
            ex.execute(skill([self.move_action()]),{"ready_for_planning":False,"automatic_motion_enabled":True},execution_authorized=True)
        self.assertEqual(calls,[])

    def test_workspace_blocks_before_move_callback(self):
        calls=[]
        g=self.ready_workspace()
        g.position["X"]=9.0
        ex=GuardedExecutor(g,lambda a:calls.append(a),lambda a:calls.append(a),lambda a,r:{"ok":True})
        with self.assertRaises(Exception):
            ex.execute(skill([self.move_action(delta=2.0)]),{"ready_for_planning":True,"automatic_motion_enabled":True},execution_authorized=True)
        self.assertEqual(calls,[])
        self.assertEqual(g.position["X"],9.0)

    def test_failed_observation_stops_without_retry(self):
        moves=[]
        g=self.ready_workspace()
        def move(a):
            moves.append(a["delta_mm"])
            return {"ok":True}
        ex=GuardedExecutor(g,move,lambda a:{"ok":True},lambda a,r:{"ok":False})
        with self.assertRaisesRegex(AutomaticExecutionBlocked,"No retry"):
            ex.execute(skill([self.move_action( "X",1.0),self.move_action("X",1.0)]),
                       {"ready_for_planning":True,"automatic_motion_enabled":True},execution_authorized=True)
        self.assertEqual(moves,[1.0])
        self.assertFalse(g.reference_valid)
        self.assertEqual(g.position["X"],0.0)

    def test_stop_before_action_sends_nothing(self):
        calls=[]
        g=self.ready_workspace()
        ex=GuardedExecutor(g,lambda a:calls.append(a),lambda a:calls.append(a),
                           lambda a,r:{"ok":True},stop_requested=lambda:True)
        with self.assertRaisesRegex(AutomaticExecutionBlocked,"STOP"):
            ex.execute(skill([self.move_action()]),{"ready_for_planning":True,"automatic_motion_enabled":True},execution_authorized=True)
        self.assertEqual(calls,[])

    def test_successful_simulation_is_one_action_one_observation(self):
        events=[]
        g=self.ready_workspace()
        def move(a):
            events.append(("move",a["axis"],a["delta_mm"]))
            return {"accepted":True}
        def check(a,r):
            events.append(("observe",a["axis"]))
            return {"ok":True,"source":"simulation"}
        ex=GuardedExecutor(g,move,lambda a:{"accepted":True},check)
        result=ex.execute(
            skill([self.move_action("X",1.0),self.move_action("Y",-2.0)]),
            {"ready_for_planning":True,"automatic_motion_enabled":True},execution_authorized=True)
        self.assertEqual(events,[("move","X",1.0),("observe","X"),("move","Y",-2.0),("observe","Y")])
        self.assertEqual(result["blind_motion_retries"],0)
        self.assertEqual(result["final_position_mm"],{"X":1.0,"Y":-2.0,"Z":0.0})


if __name__=="__main__":
    unittest.main()
