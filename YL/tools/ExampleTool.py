from agency_swarm.tools import BaseTool
from pydantic import Field
from typing import Any
from send_message import send_instagram_message

class ExampleTool(BaseTool):
    """
    Tool pentru trimiterea de mesaje prin Instagram Graph API.
    Primește un ID de destinatar și textul mesajului, 
    apoi apelează send_instagram_message pentru a-l livra.
    """
    recipient_id: str = Field(
        ...,
        description="ID-ul Instagram al destinatarului (sender.id din webhook)"
    )
    message_text: str = Field(
        ...,
        description="Textul mesajului pe care vrei să-l trimiți"
    )

    def run(self) -> Any:
        """
        Rulează trimiterea mesajului.
        Returnează un dicționar cu status și codul HTTP (sau eroarea).
        """
        try:
            response = send_instagram_message(self.recipient_id, self.message_text)
            return {
                "status": "success",
                "status_code": response.get("status_code"),
                "response_text": response.get("response_text")
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }