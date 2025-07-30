from agency_swarm.agents import Agency

# Un wrapper simplu, ca să nu mai instanţiezi Agency direct în webhook.py
agent = Agency(
    name="DM-AI-Agent",
    # …alte setări pe care le foloseşti de obicei…
)
