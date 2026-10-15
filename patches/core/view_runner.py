"""Same desktop lifecycle; exploration views are temporary, tests stay two-view."""
from .runner import Runner
from .view_world import ViewWorld
from .view_policy import Agent
from .view_curriculum import STAGES

class ViewRunner(Runner):
    validation_trials=20
    def __init__(self,folder):
        super().__init__(folder,agent_factory=Agent,world_factory=ViewWorld)

    def world_options(self):
        return {'camera_config':self.camera_config,'view_mode':self.agent.view_mode,
            'view_stage':self.agent.views.stage,'learning_enabled':self.status=='training',
            'learning_episode':self.agent.episodes}

    def evaluation_options(self):
        return {**self.world_options(),'view_mode':'two','learning_enabled':False}

    def prepare_training_world(self,env):
        env.prepare_learning(self.agent.episodes,self.agent.views.stage)

    def after_validation(self,result,env):
        with self.lock:
            if self.agent.view_mode=='auto':self.agent.views.observe_test(result)
        env.view_schedule.stage=self.agent.views.stage

    def set_views(self,mode):
        if mode not in ('auto','all','two'):raise ValueError('Unknown learning-view setting')
        with self.lock:
            if self.status in ('training','evaluating','watching','stopping'):raise ValueError('STOP & save before changing learning views')
            self.agent.view_mode=mode;self.preview_frame=None
            self.save()
        return {'ok':True,'mode':mode,'tests_always_two_mounted_cameras':True}

    def save(self):
        super().save()
        loaded,_=self.Agent.load(self.folder/'policy.npz')
        if (loaded.views.stage,loaded.views.streak,loaded.view_mode)!=(self.agent.views.stage,self.agent.views.streak,self.agent.view_mode):
            self.save_verified=False;raise RuntimeError('Saved view curriculum failed verification')

    def snapshot(self):
        result=super().snapshot()
        result['observation_mode']='masked_rgb_views'
        result['input_source']='detailed_simulated_cameras'
        result['view_curriculum']={'stage':self.agent.views.stage,'label':STAGES[self.agent.views.stage],
            'mode':self.agent.view_mode,'passing_two_view_checks':self.agent.views.streak,
            'advancement_rule':'Two held-out 20-trial checks with at least 70% success and no invalid-physics trials.',
            'test_views':['overhead','wrist'],'test_uses_helpers':False,
            'temporary_motion_bonus_remaining':max(0.,1-self.agent.episodes/500.),
            'bonus_per_new_cell':.020,'bonus_cap_per_attempt':.5,'bonus_is_mastery':False}
        if self.preview_frame:
            result['motion_feedback']={k:self.preview_frame.get(k) for k in ('discovery_bonus','task_reward','discovery_cells','safety_abort')}
        return result
