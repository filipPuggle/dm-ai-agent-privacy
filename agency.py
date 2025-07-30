from agency_swarm.agents.agent import Agent

class Agency(Agent):
    def __init__(self, assistant_id: str = None, **kwargs):
        # pasează assistant_id şi orice alt param necesar
        super().__init__(assistant_id=assistant_id, **kwargs)

# instanța exportată pentru import în webhook.py
agency = Agency(
    assistant_id=os.getenv("ASSISTANT_ID"),
    # poți pune aici şi 'instructions', 'model', etc.
)
