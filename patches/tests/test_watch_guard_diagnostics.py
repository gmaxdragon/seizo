"""Check Watch policy reveals real reasons and playback isn't hidden."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]


class WatchDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner=(ROOT/"core/runner.py").read_text()
        cls.js=(ROOT/"web/app.js").read_text()

    def test_watch_returns_real_terminal_reason(self):
        self.assertIn("'failure_reason':why",self.runner)
        self.assertIn("'safety_abort':abort",self.runner)
        self.assertIn("'invalid_physics':invalid",self.runner)
        self.assertIn("'terminated_after_steps':len(frames)-1",self.runner)
        self.assertIn("final_info=info",self.runner)
        self.assertIn("'guard_counts':guard_reasons",self.runner)
        world=(ROOT/"core/view_world.py").read_text()
        self.assertIn("info['guard_reason']=np.array(self.guard_reason,dtype=str)",world)

    def test_hide_training_previews_does_not_hide_watch(self):
        self.assertIn("($('hidePreviews').checked&&!play)",self.js)
        self.assertIn("Watch returned '+tr.episode_moves",self.js)
        self.assertIn("p.trace.failure_reason",self.js)
        self.assertIn("p.trace.safety_abort",self.js)

    def test_failure_reporting_not_used_as_ai_train_reward(self):
        watch=self.runner.split("def trial(self,",1)[1].split("def experience_summary(",1)[0]
        self.assertNotIn("agent.update(",watch)
        self.assertNotIn("self.agent.update(",watch)


if __name__=="__main__":
    unittest.main()
