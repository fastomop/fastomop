from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel, OpenAIResponsesModelSettings
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.mcp import MCPServerStdio
from fastomop.config import config as cfg
from fasta2a.schema import AgentProvider


model_name = cfg.semantic_agent.model_name
openai_url = cfg.semantic_agent.openai_url

# This is the MCP server for Semantic agent
# We should maintain a single registry for all MCP servers and call from there
mcp_server = MCPServerStdio(command="uv", args=["run", "fastomop_mcp_sql"])


provider = OpenAIProvider(base_url=openai_url)
model_settings = OpenAIResponsesModelSettings(
    # openai_reasoning_generate_summary="concise",
)
model = OpenAIModel(model_name=model_name, provider=provider)

system_prompt = (
    cfg.semantic_agent.system_prompt
    + f"""

Prefix all clinical tables with the schema name '{cfg.omop.clinical_tables_schema}' and vocabulary tables with '{cfg.omop.vocabulary_tables_schema}'.
Clinical tables: {", ".join(cfg.omop.clinical_tables)}
Vocabulary tables: {", ".join(cfg.omop.vocabulary_tables)}

"""
)

agent = Agent(
    model=model,
    name=cfg.semantic_agent.agent_name,
    output_retries=3,
    retries=5,
    system_prompt=system_prompt,
    toolsets=[mcp_server],
)

# Not used at the moment, but can be used for A2A integration
app = agent.to_a2a(
    description=cfg.semantic_agent.description,
    provider=AgentProvider(organization="FastOMOP Developers", url="example.com"),
)
