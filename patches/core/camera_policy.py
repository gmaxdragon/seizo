from .ppo import Agent as StateAgent
from .camera_observation import OBS_SIZE, POLICY_ID

class Agent(StateAgent):
    OBSERVATION_SIZE=OBS_SIZE
    POLICY_MODEL_ID=POLICY_ID
