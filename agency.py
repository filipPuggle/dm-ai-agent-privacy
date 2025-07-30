from agency_swarm import Agency
from YL.YL import YL

# Instanţiem agentul YL
yl_agent = YL()

# Construim şi exportăm instanța numită exact "agency"
agency = Agency(
    agency_chart=[yl_agent],
)
