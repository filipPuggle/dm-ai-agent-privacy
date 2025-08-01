from agency_swarm.agents import Agent
from tools.ExampleTool import ExampleTool

class YL(Agent):
    def __init__(self):
        super().__init__(
            name="YL",
            description="Dm message Agent",
            instructions="./instructions.md",
            files_folder="./files",
            schemas_folder="./schemas",
            tools_folder="./tools",
            tools=[ ExampleTool() ],      # <— adaugă aici
            temperature=0.3,
            max_prompt_tokens=25000,
        )
    def response_validator(self, message: str) -> str:
        return message
