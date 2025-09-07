from fasta2a.schema import AgentProvider

from fastomop.agents.agent_factory import create_agent
from fastomop.config import config as cfg

agent = create_agent(cfg.sql_agent)

# Not used at the moment, but can be used for A2A integration
app = agent.to_a2a(
    name=cfg.sql_agent.agent_name,
    description=cfg.sql_agent.description,
    provider=AgentProvider(
        organization="FastOMOP Developers",
        url="https://github.com/fastomop/fastomop",
    ),
)
