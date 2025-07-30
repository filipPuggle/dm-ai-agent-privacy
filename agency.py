from agency_swarm import Agency
from YL.YL import YL

# 1. Instanțiem agentul tău YL
yl_agent = YL()

# 2. Construim Agency, cu chart-ul care conține agentul
agent = Agency(
    agency_chart=[yl_agent],
)

