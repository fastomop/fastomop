from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel, OpenAIResponsesModelSettings
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.mcp import MCPServerStdio
from fastomop.config import config as cfg
from fasta2a.schema import AgentProvider


model_name = cfg.sqlagent.model_name
openai_url = cfg.sqlagent.openai_url

# This is the MCP server for SQL agent
# We should maintain a single registry for all MCP servers and call from there
mcp_server = MCPServerStdio(command="uv", args=["run", "fastomop_mcp_sql"])


provider = OpenAIProvider(base_url=openai_url)
model_settings = OpenAIResponsesModelSettings(
    openai_reasoning_generate_summary="concise",
)
model = OpenAIModel(model_name=model_name, provider=provider)

agent = Agent(
    model=model,
    name=cfg.sqlagent.agent_name,
    output_retries=3,
    retries=5,
    output_type=str,
    system_prompt=cfg.sqlagent.system_prompt,
    toolsets=[mcp_server],
)


app = agent.to_a2a(
    description=cfg.sqlagent.description,
    provider=AgentProvider(organization="FastOMOP Developers", url="example.com"),
)
