from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno_fastomop.agents.factory import create_model
from agno_fastomop.config import get_agent_config
from agno_fastomop.observability.tracer import get_langfuse_client
from pathlib import Path


def create_imaging_agent() -> Agent:
    """
    Create imaging analysis agent with vision capabilities.

    This agent receives images (fetched from HPC or provided directly) and
    analyzes them using a vision-capable model. It does not use MCP tools --
    image fetching is handled by the workflow layer before invoking the agent.

    Returns:
        Agent: Agno agent configured for image analysis
    """

    agent_config = get_agent_config("imaging")
    model = create_model(agent_config)
    db = SqliteDb(db_file="db_agent.db")

    # Fetch prompt from Langfuse (fallback to local file)
    try:
        langfuse = get_langfuse_client()
        prompt = langfuse.get_prompt("imaging_agent", label="dev")
        system_prompt = prompt.prompt
        print(f"✓ Loaded imaging_agent prompt from Langfuse (version: {prompt.version})")
    except Exception as e:
        print(f"Warning: Failed to load imaging prompt from Langfuse: {e}")
        print("Falling back to local prompt file")
        prompt_path = Path(__file__).parent.parent / "prompts" / "imaging_agent.txt"
        with open(prompt_path, "r") as f:
            system_prompt = f.read()

    agent = Agent(
        name=agent_config["name"],
        model=model,
        instructions=system_prompt,
        db=db,
        add_history_to_context=True,
        reasoning=agent_config.get("reasoning", False),
        markdown=agent_config.get("markdown", True),
    )

    return agent
