# agency.py
from agency_swarm import Agency
from YL.YL import YL

def get_completion(prompt: str) -> str:
    """
    Instanţiază Agent-ul şi Agency la cerere, apoi returnează răspunsul.
    Astfel nu mai rulăm Agent() la import, ci doar în handler.
    """
    agent = YL()
    agency = Agency(agency_chart=[agent])
    return agency.get_completion(prompt)
