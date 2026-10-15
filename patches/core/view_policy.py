"""A fresh image-conditioned PPO policy, not a downloaded AI or stored solution."""
from .ppo import Agent as BaseAgent
from .view_observation import OBS_SIZE,POLICY_ID
from .view_curriculum import ViewSchedule

class Agent(BaseAgent):
    OBSERVATION_SIZE=OBS_SIZE
    POLICY_MODEL_ID=POLICY_ID
    def __init__(self,seed=101,hidden=64):
        super().__init__(seed,hidden)
        self.p['logstd'][:]=-.10  # Stochastic exploration, within the existing action bounds.
        self.views=ViewSchedule();self.view_mode='auto'
    def save(self,path,metadata=None):
        extra=dict(metadata or {})
        extra['view_progress']={'stage':self.views.stage,'streak':self.views.streak,'mode':self.view_mode}
        super().save(path,extra)
    @classmethod
    def load(cls,path):
        agent,extra=super().load(path);v=extra.get('view_progress',{})
        agent.views=ViewSchedule(v.get('stage',0),v.get('streak',0))
        agent.view_mode=v.get('mode','auto')
        if agent.view_mode not in ('auto','all','two'):raise ValueError('Invalid saved view mode')
        return agent,extra
