"""Agent builder for creating pydantic or langchain agents."""
from fastomop.config import AgentSettings
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStdio
from fastomop.agents.pydantic_factory import create_pydantic_agent
from fastomop.config import config as cfg

def create_agent(settings: AgentSettings) -> Agent:
    """Create an appropriate agent based on Agent settings

    Args:
        settings: Agent settings
        mcp_server: MCP server instance
    """
    toolsets = []
    if settings.mcp_servers:
        for server_name in settings.mcp_servers:
            server_config = next((s for s in cfg.mcp_servers if s.name == server_name),
            None
            )
            if server_config:
                mcp_server = MCPServerStdio(command=server_config.command, args=server_config.args)
                toolsets.append(mcp_server)
                print(f"Added MCP server: {server_name}")
            else:
                print(f"MCP server not found: {server_name}")

    return create_pydantic_agent(settings, toolsets)