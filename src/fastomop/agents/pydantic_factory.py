from fastomop.config import AgentSettings
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStdio
from fastomop.config import config as cfg
from fastomop.agents.llm_builder import create_provider, create_model


def create_pydantic_agent(settings: AgentSettings, toolsets: list[MCPServerStdio]) -> Agent:
    """Create an appropriate agent based on Agent settings

    Args:
        settings: Agent settings
        mcp_server: MCP server instance

    Returns:
        Appropriate agent instance

    Raises:
        ValueError: If agent type is not supported
    """
    
    provider = create_provider(settings.provider)
    model = create_model(settings.model_name, provider, settings.provider)


    system_prompt = settings.system_prompt
    if settings.needs_omop_schema:
        system_prompt += f"""

        Prefix all clinical tables with the schema name '{cfg.omop.clinical_tables_schema}' and vocabulary tables with '{cfg.omop.vocabulary_tables_schema}'.
        Clinical tables: {", ".join(cfg.omop.clinical_tables)}
        Vocabulary tables: {", ".join(cfg.omop.vocabulary_tables)}

        """
    agent = Agent(
        name=settings.agent_name,
        model=model,
        system_prompt=system_prompt,
        toolsets=toolsets or [],
        output_retries=3,
        retries=5
    )
    return agent