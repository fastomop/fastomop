"""
Clinical Imaging Pipeline Workflow

4-step workflow: Semantic → Database → Image fetch (from HPC) → Imaging agent.
Fetches images from HPC using local_path from the DB step and passes them to the imaging agent.
"""

import csv
import io
import json
import re
import traceback
from typing import List

from agno.workflow import Workflow, Step
from agno.workflow.types import StepInput, StepOutput
from agno.tools.function import Function

from agno_fastomop.tools.hpc_image import fetch_hpc_image

MAX_IMAGES_TO_FETCH = 5


def parse_local_paths_from_db_content(content: str) -> List[str]:
    """
    Extract absolute file paths from database step output.

    Tries JSON, CSV, and line-based extraction in order.
    Expects paths starting with '/' (full absolute paths from omop_gold.image_occurrence.local_path).
    """
    if not content or not content.strip():
        return []

    paths: List[str] = []
    text = content.strip()

    # Strip markdown code fences if present
    if "```" in text:
        m = re.search(r"```(?:json)?\s*\n?([\s\S]*?)```", text)
        if m:
            text = m.group(1).strip()

    # 1) JSON: array/object with local_path
    if text.lstrip().startswith(("[", "{")):
        try:
            data = json.loads(text)
            items = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
            for item in items:
                if not isinstance(item, dict):
                    continue
                val = item.get("local_path", "")
                if isinstance(val, str) and val.startswith("/"):
                    paths.append(val.strip())
        except json.JSONDecodeError:
            pass
        if paths:
            return list(dict.fromkeys(paths))[:MAX_IMAGES_TO_FETCH]

    # 2) CSV with local_path header
    if "local_path" in content.lower():
        try:
            reader = csv.reader(io.StringIO(content.strip()))
            rows = list(reader)
            if rows:
                header = [c.strip().lower() for c in rows[0]]
                if "local_path" in header:
                    col = header.index("local_path")
                    for r in rows[1:]:
                        if col < len(r) and r[col].strip().startswith("/"):
                            paths.append(r[col].strip())
        except Exception:
            pass
        if paths:
            return list(dict.fromkeys(paths))[:MAX_IMAGES_TO_FETCH]

    # 3) Regex: find absolute paths anywhere in text
    path_matches = re.findall(
        r'(/[\w./_-]+\.(?:jpg|jpeg|png|gif|webp|tiff|tif|bmp|dcm))',
        content, re.IGNORECASE,
    )
    if path_matches:
        return list(dict.fromkeys(path_matches))[:MAX_IMAGES_TO_FETCH]

    return []


def image_fetch_step(step_input: StepInput) -> StepOutput:
    """
    Workflow step: parse DB output for local_path, fetch images from HPC,
    pass them along with metadata to the next step.
    """
    content = step_input.get_last_step_content()
    if isinstance(content, (dict, list)):
        content = json.dumps(content, default=str)
    text = (content or "").strip()

    paths = parse_local_paths_from_db_content(text)
    images, errors = [], []
    for remote_path in paths:
        try:
            images.append(fetch_hpc_image(remote_path=remote_path))
        except Exception as e:
            errors.append(f"{remote_path}: {e}")

    out = text
    if errors:
        out += "\n\n(Image fetch issues: " + "; ".join(errors[:3]) + ")"
    if images:
        out += f"\n\n(Fetched {len(images)} image(s) from HPC for analysis.)"

    return StepOutput(content=out, images=images or None, success=True)


def make_delegate_to_imaging_with_images_tool(imaging_agent):
    """
    Build a Team tool that fetches images from HPC and delegates to the imaging agent.
    """

    def delegate_to_imaging_with_images(task: str, db_results: str) -> str:
        """Fetch images from HPC using local_path in db_results, then run imaging agent."""
        print(f"[ImagingDelegation] task={len(task)} chars, db_results={len(db_results or '')} chars")
        print(f"[ImagingDelegation] db_results preview: {(db_results or '')[:500]}")

        paths = parse_local_paths_from_db_content(db_results or "")
        print(f"[ImagingDelegation] Extracted {len(paths)} path(s): {paths[:3]}")

        images, errors = [], []
        for p in paths:
            try:
                img = fetch_hpc_image(remote_path=p)
                images.append(img)
                print(f"[ImagingDelegation] Fetched {p} ({len(img.content)} bytes)")
            except Exception as e:
                errors.append(f"{p}: {e}")
                print(f"[ImagingDelegation] Failed {p}: {e}")
                traceback.print_exc()

        print(f"[ImagingDelegation] Running imaging agent with {len(images)} image(s)...")
        try:
            resp = imaging_agent.run(input=task, images=images or None)
            content = (resp.content or "").strip()
            print(f"[ImagingDelegation] Done, {len(content)} chars returned")
        except Exception as e:
            print(f"[ImagingDelegation] Imaging agent error: {e}")
            traceback.print_exc()
            return f"Imaging analysis failed: {e}"

        if errors:
            content += "\n\n(Image fetch errors: " + "; ".join(errors[:3]) + ")"
        return content

    return Function(
        name="delegate_to_imaging_with_images",
        description=(
            "Delegate to the Clinical Imaging Agent with images fetched from HPC. "
            "Use this instead of delegate_task_to_member for the imaging agent. "
            "Pass the full Database agent output as db_results."
        ),
        parameters={
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "Task description for the imaging agent (include the user question).",
                },
                "db_results": {
                    "type": "string",
                    "description": "Full Database agent output containing local_path values.",
                },
            },
            "required": ["task", "db_results"],
        },
        entrypoint=delegate_to_imaging_with_images,
    )


def initialize_clinical_imaging_pipeline(semantic_agent, database_agent, imaging_agent) -> Workflow:
    """Build the 4-step Clinical Imaging Pipeline workflow."""
    from agno.db.sqlite import SqliteDb

    return Workflow(
        name="Clinical Imaging Pipeline",
        db=SqliteDb(db_file="db_agent.db"),
        debug_mode=True,
        steps=[
            Step(
                name="Semantic Extraction",
                agent=semantic_agent,
                description="Extract clinical concepts and classify imaging query",
                add_workflow_history=False,
                num_history_runs=0,
            ),
            Step(
                name="SQL Generation and Execution",
                agent=database_agent,
                description="Query image_occurrence, image_feature, note and get local_path",
                add_workflow_history=False,
                num_history_runs=0,
            ),
            Step(
                name="Image Fetch",
                executor=image_fetch_step,
                description="Fetch images from HPC using local_path from DB results",
            ),
            Step(
                name="Image Analysis",
                agent=imaging_agent,
                description="Analyze fetched images with metadata and reports",
                add_workflow_history=False,
                num_history_runs=0,
            ),
        ],
    )
