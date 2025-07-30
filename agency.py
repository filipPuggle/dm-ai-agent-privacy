import os  # ✅ Import esențial pentru getenv
from agency_swarm.agents.agent import Agent

class Agency(Agent):
    def __init__(self, assistant_id: str = None, **kwargs):
        super().__init__(assistant_id=assistant_id, **kwargs)

# Instanța exportată pentru webhook
agency = Agency(
    assistant_id=os.getenv("ASSISTANT_ID"),
)