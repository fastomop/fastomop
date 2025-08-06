"""Provider factory for creating LLM providers."""
from fastomop.config import AgentSettings
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStdio
from fastomop.agents.pydantic_factory import create_pydantic_agent
from fastomop.agents.langchain_factory import create_langchain_agent
from fastomop.agents.agent_protocol import RunnableAgent

async def create_agent(settings: AgentSettings) -> RunnableAgent:
    """Create an appropriate agent based on Agent settings

    Args:
        settings: Agent settings
        mcp_server: MCP server instance
    """
    if settings.agent_type == "pydantic":
        return create_pydantic_agent(settings)

    elif settings.agent_type == "langchain":
        return await create_langchain_agent(settings)