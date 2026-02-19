"""
FastOMOP Web Interface

Exposes the FastOMOP workflow through AgentOS with built-in web UI.

Usage:
    uv run python -m agno_fastomop.web_interface

Then visit http://localhost:7777

Note: Auto-reload is disabled due to DuckDB file locking constraints.
"""


import asyncio
from contextlib import asynccontextmanager
from agno.os import AgentOS
from agno_fastomop.workflows.omop_workflow import initialize_workflow, cleanup_workflow
from agno_fastomop.workflows.imaging_workflow import initialize_imaging_workflow, cleanup_imaging_workflow
from agno_fastomop.workflows.clinical_imaging_pipeline import (
    initialize_clinical_imaging_pipeline,
    make_delegate_to_imaging_with_images_tool,
)
from agno_fastomop.agents.factory import create_model
from agno_fastomop.config import config, get_team_model_config
from agno.db.sqlite import SqliteDb
from agno.team import Team
from agno.compression.manager import CompressionManager
import uvicorn

# Global storage
_workflow = None
_imaging_workflow = None
_clinical_imaging_pipeline = None
_agents = None
_omop_team_conv = None
_omop_team_complex = None
_imaging_team = None
_agent_os = None
_app = None


@asynccontextmanager
async def app_lifespan(app):
    """Handle graceful shutdown - cleanup MCP connections"""
    # Startup: nothing to do (workflow already initialized)
    yield
    # Shutdown: cleanup MCP subprocess to release DuckDB lock
    print("Shutting down FastOMOP - cleaning up connections...")
    await cleanup_workflow()
    await cleanup_imaging_workflow()
    print("Cleanup complete")


async def initialize():
    """Initialize workflow and create AgentOS - all in the same event loop"""
    global _workflow, _imaging_workflow, _clinical_imaging_pipeline, _agents, _omop_team_conv, _omop_team_complex, _imaging_team, _agent_os, _app

    print("Initializing FastOMOP workflow...")
    _workflow = await initialize_workflow()
    _agents = [step.agent for step in _workflow.steps]
    print("✓ OMOP workflow initialized")

    # Initialize imaging workflow (separate from OMOP)
    print("Initializing imaging workflow...")
    _imaging_workflow = await initialize_imaging_workflow()
    _imaging_agent = _imaging_workflow.steps[0].agent
    _agents.append(_imaging_agent)
    print("✓ Imaging workflow initialized")

    # 4-step Clinical Imaging Pipeline: Semantic → DB → Image fetch (HPC) → Imaging agent
    print("Initializing Clinical Imaging Pipeline (with image-fetch step)...")
    _semantic_agent = _workflow.steps[0].agent
    _database_agent = _workflow.steps[1].agent
    _clinical_imaging_pipeline = initialize_clinical_imaging_pipeline(
        _semantic_agent, _database_agent, _imaging_agent
    )
    print("✓ Clinical Imaging Pipeline initialized")

    # Get team orchestrator model (MedGemma 27b for all teams)
    team_model_config = get_team_model_config()

    # Create shared memory db for all agents and team
    shared_db = SqliteDb(db_file="db_agent.db")

    # Update each agent to use the shared db
    for agent in _agents:
        agent.db = shared_db

    # Create a Team with both agents working together
    _omop_team_conv = Team(
        name="OMOP Conversation Team",
        model=create_model(team_model_config),
        members=_agents,
        db=shared_db,
        tool_call_limit=15,
        enable_user_memories=False,
        add_history_to_context=True,
        enable_session_summaries=True,
        add_session_summary_to_context=True,
        num_history_runs=3,
        search_session_history=False,
        share_member_interactions=True,
        compress_tool_results=True,
        stream=False,
        stream_member_events=True,
        show_members_responses=True,
        description="Team for OMOP clinical queries: semantic agent extracts concepts, database agent generates and executes SQL",
        instructions=[
            "You are coordinating a clinical database query team for OMOP CDM (Observational Medical Outcomes Partnership Common Data Model) queries.",
            "",
            "WORKFLOW (ALWAYS follow this exact sequence):",
            "1. FIRST: Delegate to 'OMOP Semantic Agent' to extract clinical concepts from the user's natural language query",
            "   - This agent will identify relevant OMOP concept IDs, domains, and vocabulary terms",
            "",
            "2. SECOND: Take the semantic context output and delegate to 'OMOP Database Agent'",
            "   - Pass both the original user query AND the semantic context",
            "   - This agent will generate OMOP CDM-compliant SQL and execute it",
            "",
            "3. FINALLY: Return the query results to the user in a clear, understandable format and explain the steps involved (derived concepts, logics etc from semantic context)",
            "",
            "IMPORTANT RULES:",
            "- NEVER skip the semantic agent - it provides crucial OMOP concept mappings",
            "- ALWAYS run agents sequentially in the order above (semantic → database)",
            "- Results have to be none 0, if you get 0 results, delegate again with refinement suggestions",
            "-For follow-ups, reference the session summary for prior context.",
        ],
    )

    # Create a Team with both agents working together
    _omop_team_complex = Team(
        name="OMOP Complex Team",
        model=create_model(team_model_config),
        members=_agents,
        db=shared_db,
        enable_user_memories=False,
        add_history_to_context=False,
        num_history_runs=0,
        share_member_interactions=True,
        search_session_history=False,
        compress_tool_results=True,
        stream=False,
        stream_member_events=True,
        show_members_responses=True,
        description="Team for OMOP complex clinical queries: semantic agent extracts concepts, database agent generates and executes SQL",
        instructions=[
            "You are coordinating a clinical database query team for OMOP CDM (Observational Medical Outcomes Partnership Common Data Model)"
            "",
            "WORKFLOW (ALWAYS follow this exact sequence):",
            "1. FIRST: Delegate to 'OMOP Semantic Agent' to extract clinical concepts from the user's natural language query",
            "   - This agent will identify relevant OMOP concept IDs, domains, and vocabulary terms",
            "",
            "2. SECOND: Take the semantic context output and delegate to 'OMOP Database Agent'",
            "   - Pass both the original user query AND the semantic context",
            "   - This agent will generate OMOP CDM-compliant SQL and execute it",
            "",
            "3. FINALLY: Return the query results to the user in a clear, understandable format and explain the steps involved (derived concepts, logics etc from semantic context)",
            "",
            "IMPORTANT RULES:",
            "- NEVER skip the semantic agent - it provides crucial OMOP concept mappings",
            "- ALWAYS run agents sequentially in the order above (semantic → database)",
            "- Results have to be none 0, if you get 0 results, delegate again with refinement suggestions",
        ],
    )

    print("✓ OMOP teams created")

    # Compression manager for imaging team and its member agents (conservative: 8000 tokens, 6 tool results)
    for agent in _agents:
        if agent.compression_manager is None:
            agent.compress_tool_results = True
            agent.compression_manager = CompressionManager(
                model=agent.model,
                compress_tool_results=True,
                compress_token_limit=8000,
                compress_tool_results_limit=6,
            )
    print("✓ Compression managers attached (token_limit=8000, tool_limit=6)")

    # Tool so the imaging agent receives images fetched from HPC (from DB local_path)
    delegate_to_imaging_with_images_tool = make_delegate_to_imaging_with_images_tool(_imaging_agent)

    # Create Clinical Imaging Team: semantic → database → imaging agent pipeline
    # Uses Complex Team pattern (no history, no session summaries) to minimize context for 20B model
    # Custom tool delegate_to_imaging_with_images fetches images from HPC and passes them to the imaging agent
    imaging_compression = CompressionManager(
        model=create_model(team_model_config),
        compress_tool_results=True,
        compress_token_limit=8000,
        compress_tool_results_limit=6,
    )
    _imaging_team = Team(
        name="Clinical Imaging Team",
        model=create_model(team_model_config),
        members=_agents,
        tools=[delegate_to_imaging_with_images_tool],
        db=shared_db,
        enable_user_memories=False,
        add_history_to_context=False,
        num_history_runs=0,
        share_member_interactions=True,
        search_session_history=False,
        compress_tool_results=True,
        compression_manager=imaging_compression,
        stream=False,
        stream_member_events=True,
        show_members_responses=True,
        description="Team for clinical imaging queries: retrieves image metadata, CheXpert labels, and radiology reports",
        instructions=[
            "You coordinate clinical imaging queries using OMOP CDM.",
            "",
            "WORKFLOW (follow this exact sequence):",
            "1. Delegate to 'OMOP Semantic Agent' to classify the query and extract concepts (use delegate_task_to_member).",
            "2. Delegate to 'OMOP Database Agent' with the semantic context (use delegate_task_to_member).",
            "   - DB agent queries image_occurrence, image_feature (CheXpert labels), and note tables.",
            "3. Delegate to 'Clinical Imaging Agent' using the tool delegate_to_imaging_with_images(task=..., db_results=...).",
            "   - Pass the full Database agent output as db_results so images are fetched from HPC (local_path) and passed to the imaging agent.",
            "   - Do NOT use delegate_task_to_member for the Clinical Imaging Agent; use delegate_to_imaging_with_images only.",
            "4. Synthesize and return a clear imaging report to the user",
            "",
            "RULES:",
            "- Always run: semantic → database → imaging, in order.",
            "- For steps 1 and 2 use delegate_task_to_member(member_id, task) with only those two parameters.",
            "- For step 3 use delegate_to_imaging_with_images(task=..., db_results=...) with the DB output as db_results.",
            "- If no images found, report this clearly.",
            "",
            "DELEGATE TOOL: When you call delegate_task_to_member, use ONLY two parameters: member_id and task.",
            "Put everything the member needs (including semantic context or DB results) inside the task string as plain text.",
            "Do not add a third parameter like semantic_context_json. Output exactly one valid JSON object with no extra trailing braces or characters.",
        ],
    )

    print("✓ Clinical Imaging Team created")

    # Create AgentOS with all options:
    # - workflows: for cloud AgentOS UI
    # - teams: for local Agent UI (Team mode)
    # - agents: for local Agent UI (Agent mode - individual agents)
    _agent_os = AgentOS(
        name="FastOMOP",
        description="Natural language interface for OMOP clinical databases",
        workflows=[_workflow, _imaging_workflow, _clinical_imaging_pipeline],
        teams=[_omop_team_conv, _omop_team_complex, _imaging_team],
        agents=_agents,
        lifespan=app_lifespan,
    )

    _app = _agent_os.get_app()
    print("✓ AgentOS created with workflows, teams (OMOP + Imaging), and individual agents")


async def main():
    """Main async entry point"""
    # Initialize everything in this event loop
    await initialize()

    # Configure and run uvicorn server
    uvicorn_config = uvicorn.Config(
        app=_app,
        host="0.0.0.0",
        port=3000,
        reload=False,
        log_level="info",
    )
    server = uvicorn.Server(uvicorn_config)

    # Run server in the same event loop
    await server.serve()


if __name__ == "__main__":
    """Visit http://localhost:7777 to interact with FastOMOP"""
    asyncio.run(main())
