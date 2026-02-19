"""
Imaging Workflow

Separate workflow that fetches images from a remote HPC node and runs them
through a vision-capable imaging agent. Operates independently from the
OMOP clinical query workflow.

Usage:
    from agno_fastomop.workflows.imaging_workflow import run_imaging_query

    response = await run_imaging_query(
        remote_path="/hpc/data/scans/patient_001.png",
        message="Describe the findings in this chest X-ray",
        metadata={"patient_id": "001", "modality": "X-ray"},
    )
"""

from agno.workflow import Workflow, Step
from agno_fastomop.agents.imaging import create_imaging_agent
from agno_fastomop.tools.hpc_image import fetch_hpc_image
from agno.db.sqlite import SqliteDb
from agno.media import Image
from langfuse import observe
from typing import Optional
import asyncio
import json

# Module-level storage (created once, reused)
_imaging_workflow = None
_imaging_agent = None
_init_lock = asyncio.Lock()


async def initialize_imaging_workflow() -> Workflow:
    """
    Initialize the imaging workflow with a single imaging agent step.
    Creates agent and workflow once, caches for reuse.

    Returns:
        Workflow: Configured imaging workflow
    """
    global _imaging_workflow, _imaging_agent

    async with _init_lock:
        if _imaging_workflow is not None:
            return _imaging_workflow

        db = SqliteDb(db_file="db_agent.db")

        print("Initializing imaging agent...")
        _imaging_agent = create_imaging_agent()
        print("✓ Imaging agent created")

        _imaging_workflow = Workflow(
            name="Clinical Imaging Analysis Workflow",
            db=db,
            debug_mode=True,
            steps=[
                Step(
                    name="Image Analysis",
                    agent=_imaging_agent,
                    description="Analyze clinical images with vision-capable model",
                    add_workflow_history=True,
                    num_history_runs=3,
                ),
            ],
        )

        print("✓ Imaging workflow initialized")
        return _imaging_workflow


def _build_message(
    message: str,
    remote_path: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> str:
    """
    Build a composite message string that includes the user query,
    the image source path, and any metadata context.

    Args:
        message: User's question or instruction about the image
        remote_path: Path to the image on the HPC node (for context)
        metadata: Optional dict with additional context (patient info, etc.)

    Returns:
        str: Formatted message for the agent
    """
    parts = [message]

    if remote_path:
        parts.append(f"\n\nImage source: {remote_path}")

    if metadata:
        formatted_meta = json.dumps(metadata, indent=2)
        parts.append(f"\n\nMetadata:\n```json\n{formatted_meta}\n```")

    return "".join(parts)


@observe()
async def run_imaging_query(
    remote_path: str,
    message: str,
    metadata: Optional[dict] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    host: Optional[str] = None,
    username: Optional[str] = None,
    ssh_key_path: Optional[str] = None,
    port: Optional[int] = None,
):
    """
    Fetch an image from a remote HPC node and run it through the imaging agent.

    This is the main entry point for the imaging workflow. It:
    1. Fetches the image from the HPC node via SSH/SFTP
    2. Builds a message with the user query and metadata
    3. Runs the imaging agent with the image and message

    Args:
        remote_path: Absolute path to the image file on the HPC node
        message: User's question or instruction about the image
        metadata: Optional dict with context (patient info, modality, etc.)
        session_id: Session identifier for conversation history
        user_id: User identifier for personalized memories
        host: Override HPC hostname (default: from config/env)
        username: Override SSH username (default: from config/env)
        ssh_key_path: Override SSH key path (default: from config/env)
        port: Override SSH port (default: from config/env)

    Returns:
        RunOutput: The agent's analysis response
    """
    # Step 1: Fetch image from HPC
    print(f"Fetching image from HPC: {remote_path}")
    image = fetch_hpc_image(
        remote_path=remote_path,
        host=host,
        username=username,
        ssh_key_path=ssh_key_path,
        port=port,
    )
    print(f"✓ Image fetched ({len(image.content)} bytes, {image.mime_type})")

    # Step 2: Build composite message
    composite_message = _build_message(message, remote_path, metadata)

    # Step 3: Run through imaging workflow
    workflow = await initialize_imaging_workflow()
    response = await workflow.arun(
        composite_message,
        images=[image],
        session_id=session_id,
        user_id=user_id,
    )

    return response


@observe()
async def run_imaging_query_local(
    image_path: str,
    message: str,
    metadata: Optional[dict] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
):
    """
    Run a local image through the imaging agent (no SSH required).
    Convenience function for testing or when the image is already local.

    Args:
        image_path: Path to a local image file
        message: User's question or instruction about the image
        metadata: Optional dict with context
        session_id: Session identifier for conversation history
        user_id: User identifier

    Returns:
        RunOutput: The agent's analysis response
    """
    image = Image(filepath=image_path)

    composite_message = _build_message(message, image_path, metadata)

    workflow = await initialize_imaging_workflow()
    response = await workflow.arun(
        composite_message,
        images=[image],
        session_id=session_id,
        user_id=user_id,
    )

    return response


async def cleanup_imaging_workflow():
    """Cleanup resources (call on shutdown)."""
    global _imaging_workflow, _imaging_agent
    _imaging_workflow = None
    _imaging_agent = None
