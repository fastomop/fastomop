from agno.agent import Agent
from agno.tools.mcp import MCPTools
from agno_fastomop.agents.factory import create_model
from agno_fastomop.config import get_agent_config
from agno_fastomop.schemas.schemas import SemanticContext
from agno_fastomop.observability.tracer import get_langfuse_client
from agno.db.sqlite import SqliteDb
from pathlib import Path


def create_semantic_agent(mcp_tools: MCPTools) -> Agent:
    """
    Create semantic agent using FastOMOP's approach: direct SQL queries to concept table.

    Simple and effective: Query OMOP concept table with LIKE searches via shared MCP.
    Uses intelligent LLM-based concept selection with database usage checks.

    Args:
        mcp_tools: Shared MCP connection (avoids DuckDB lock)
    """

    agent_config = get_agent_config("semantic")
    model = create_model(agent_config)

    # Use same database as database_agent for shared memory
    db = SqliteDb(db_file="db_agent.db")

    # Fetch prompt from Langfuse
    try:
        langfuse = get_langfuse_client()
        prompt = langfuse.get_prompt("semantic_agent", label="dev")
        system_prompt = prompt.prompt
        print(f"✓ Loaded semantic_agent prompt from Langfuse (version: {prompt.version})")
    except Exception as e:
        print(f"Warning: Failed to load prompt from Langfuse: {e}")
        print("Falling back to local prompt file")
        prompt_path = Path(__file__).parent.parent / "prompts" / "semantic_agent_fastomop.txt"
        with open(prompt_path, 'r') as f:
            system_prompt = f.read()

    agent = Agent(
        name=agent_config["name"],
        model=model,
        instructions=system_prompt,
        db=db,  # Shared database for conversation history and memory
        tools=[mcp_tools],  # Use MCP tools directly for database queries
        # output_schema=SemanticContext,
        reasoning=agent_config.get("reasoning", False),
        markdown=False,  # Don't format as markdown - return raw JSON
        add_history_to_context=False,  # Enable conversation history
        stream=False,
        retries=4,
    )
    return agent
