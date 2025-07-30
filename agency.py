import os
from agency_swarm.agents.agent import Agent

class Agency(Agent):
    def __init__(self):
        assistant_id = os.getenv("ASSISTANT_ID")
        if assistant_id:
            super().__init__(id=assistant_id)
        else:
            super().__init__(
                name="YL",
                description="Dm message Agent",
                instructions="./instructions.md",
                files_folder="YL/files",
                schemas_folder="YL/schemas",
                tools=[],
                tools_folder="YL/tools",
                temperature=0.3,
                max_prompt_tokens=25000,
            )