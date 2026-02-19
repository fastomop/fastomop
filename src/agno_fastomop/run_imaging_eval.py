"""
Medical CXR VQA Evaluation Runner

Batch evaluation of vision-capable agents using the Medical CXR VQA dataset.
Supports two modes:
  - team:   Full Clinical Imaging Team pipeline (semantic → DB → image fetch → imaging)
  - direct: Fetch image from HPC directly, run imaging agent only (faster, tests vision model)

Usage:
    # Full pipeline via imaging team (realistic end-to-end)
    python -m agno_fastomop.run_imaging_eval --dataset medical-cxr-vqa-questions.csv --mode team --split test --limit 100

    # Direct imaging agent only (faster, vision-only eval)
    python -m agno_fastomop.run_imaging_eval --dataset medical-cxr-vqa-questions.csv --mode direct --split test --limit 100

    # Filter by question type
    python -m agno_fastomop.run_imaging_eval --dataset medical-cxr-vqa-questions.csv --mode direct --question-type presence --limit 50
"""

import argparse
import asyncio
import csv
import json
import signal
import sys
import traceback
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from agno_fastomop.run_agent import TeeStream, save_results_safely


# ---------------------------------------------------------------------------
# CSV loading & filtering
# ---------------------------------------------------------------------------

def load_vqa_dataset(
    csv_path: str,
    split: Optional[str] = None,
    question_type: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, str]]:
    """Load the VQA CSV and return filtered rows as list of dicts."""
    rows: List[Dict[str, str]] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if split and row.get("split", "").strip().lower() != split.lower():
                continue
            if question_type and row.get("question_type", "").strip().lower() != question_type.lower():
                continue
            rows.append(row)
            if limit and len(rows) >= limit:
                break
    return rows


def group_by_image(rows: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """
    Group questions by unique image (subject_id, study_id, dicom_id).
    Returns list of image groups, each containing all questions for that image.
    """
    key_to_questions: Dict[tuple, List[Dict[str, str]]] = defaultdict(list)
    key_order: List[tuple] = []

    for row in rows:
        key = (row["subject_id"], row["study_id"], row["dicom_id"])
        if key not in key_to_questions:
            key_order.append(key)
        key_to_questions[key].append(row)

    groups = []
    for key in key_order:
        sid, stid, did = key
        groups.append({
            "subject_id": sid,
            "study_id": stid,
            "dicom_id": did,
            "questions": key_to_questions[key],
        })
    return groups


# ---------------------------------------------------------------------------
# Query composition
# ---------------------------------------------------------------------------

def compose_team_query(subject_id: str, study_id: str, dicom_id: str, question: str) -> str:
    """Build a natural-language query for the Clinical Imaging Team."""
    return (
        f"For patient {subject_id}, study {study_id}, "
        f"X-ray {dicom_id}: {question}"
    )


def compose_direct_prompt(question: str, metadata: Dict[str, str]) -> str:
    """Build a prompt for the imaging agent in direct mode."""
    meta_str = json.dumps(metadata, indent=2)
    return (
        f"{question}\n\n"
        f"Clinical context:\n```json\n{meta_str}\n```\n\n"
        "Provide a concise answer to the question based on the image."
    )


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def normalise(text: str) -> str:
    """Lower-case, strip punctuation, collapse whitespace."""
    import re
    text = text.lower().strip().strip('"').strip("'").strip(".")
    text = re.sub(r"[^\w\s,/]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def score_presence(predicted: str, ground_truth: str) -> Dict[str, Any]:
    """Score yes/no presence questions via exact match."""
    pred = normalise(predicted)
    gt = normalise(ground_truth)
    pred_yn = "yes" if "yes" in pred else ("no" if "no" in pred else pred)
    correct = pred_yn == gt
    return {"correct": correct, "predicted_normalised": pred_yn, "ground_truth_normalised": gt}


def score_view(predicted: str, ground_truth: str) -> Dict[str, Any]:
    """Score view questions (PA, AP, lateral, etc.)."""
    pred = normalise(predicted)
    gt = normalise(ground_truth)
    gt_keywords = set(gt.replace(" view", "").replace(" ", "").split(","))
    correct = any(kw in pred for kw in gt_keywords) or gt in pred
    return {"correct": correct, "predicted_normalised": pred, "ground_truth_normalised": gt}


def score_keyword_overlap(predicted: str, ground_truth: str) -> Dict[str, Any]:
    """Score by checking if ground truth keywords appear in the prediction."""
    pred = normalise(predicted)
    gt = normalise(ground_truth)
    gt_items = [item.strip() for item in gt.split(",")]
    matched = [item for item in gt_items if item in pred]
    recall = len(matched) / len(gt_items) if gt_items else 0.0
    return {
        "correct": recall >= 0.5,
        "recall": recall,
        "matched_items": matched,
        "total_gt_items": len(gt_items),
        "predicted_normalised": pred,
        "ground_truth_normalised": gt,
    }


def score_answer(question_type: str, predicted: str, ground_truth: str) -> Dict[str, Any]:
    """Route to the appropriate scorer based on question type."""
    if question_type == "presence":
        return score_presence(predicted, ground_truth)
    elif question_type == "view":
        return score_view(predicted, ground_truth)
    else:
        return score_keyword_overlap(predicted, ground_truth)


# ---------------------------------------------------------------------------
# Mode: team (full Clinical Imaging Team)
# ---------------------------------------------------------------------------

async def run_team_mode(
    groups: List[Dict[str, Any]],
    output_path: Path,
    shutdown_flag: Dict,
):
    """Run evaluation using the full Clinical Imaging Team."""
    from agno_fastomop.workflows.omop_workflow import initialize_workflow, cleanup_workflow
    from agno_fastomop.workflows.imaging_workflow import initialize_imaging_workflow, cleanup_imaging_workflow
    from agno_fastomop.workflows.clinical_imaging_pipeline import make_delegate_to_imaging_with_images_tool
    from agno_fastomop.agents.factory import create_model
    from agno_fastomop.config import get_team_model_config
    from agno.team import Team
    from agno.compression.manager import CompressionManager
    from agno.db.sqlite import SqliteDb

    print("Initializing full imaging team pipeline...")
    workflow = await initialize_workflow()
    imaging_workflow = await initialize_imaging_workflow()

    semantic_agent = workflow.steps[0].agent
    database_agent = workflow.steps[1].agent
    imaging_agent = imaging_workflow.steps[0].agent
    all_agents = [semantic_agent, database_agent, imaging_agent]

    team_model_config = get_team_model_config()
    shared_db = SqliteDb(db_file="db_eval.db")

    for agent in all_agents:
        agent.db = shared_db
        if agent.compression_manager is None:
            agent.compress_tool_results = True
            agent.compression_manager = CompressionManager(
                model=agent.model,
                compress_tool_results=True,
                compress_token_limit=8000,
                compress_tool_results_limit=6,
            )

    delegate_tool = make_delegate_to_imaging_with_images_tool(imaging_agent)
    imaging_compression = CompressionManager(
        model=create_model(team_model_config),
        compress_tool_results=True,
        compress_token_limit=8000,
        compress_tool_results_limit=6,
    )

    team = Team(
        name="Clinical Imaging Team (Eval)",
        model=create_model(team_model_config),
        members=all_agents,
        tools=[delegate_tool],
        db=shared_db,
        enable_user_memories=False,
        add_history_to_context=False,
        num_history_runs=0,
        share_member_interactions=True,
        search_session_history=False,
        compress_tool_results=True,
        compression_manager=imaging_compression,
        stream=False,
        show_members_responses=True,
        description="Eval team for clinical imaging VQA",
        instructions=[
            "You coordinate clinical imaging queries using OMOP CDM.",
            "",
            "WORKFLOW (follow this exact sequence):",
            "1. Delegate to 'OMOP Semantic Agent' to classify the query and extract concepts.",
            "2. Delegate to 'OMOP Database Agent' with the semantic context.",
            "3. Delegate to 'Clinical Imaging Agent' using delegate_to_imaging_with_images(task=..., db_results=...).",
            "4. Return a CONCISE answer to the user's specific question. For yes/no questions answer only yes or no.",
            "",
            "RULES:",
            "- Always run: semantic -> database -> imaging, in order.",
            "- For steps 1 and 2 use delegate_task_to_member(member_id, task).",
            "- For step 3 use delegate_to_imaging_with_images(task=..., db_results=...).",
            "- Answer the specific question asked. Be concise.",
        ],
    )

    print("Team initialized. Processing questions...")

    results = []
    total_q = sum(len(g["questions"]) for g in groups)
    q_idx = 0
    last_save_count = 0

    try:
        for gi, group in enumerate(groups):
            if shutdown_flag["flag"]:
                break

            for row in group["questions"]:
                if shutdown_flag["flag"]:
                    break

                q_idx += 1
                query = compose_team_query(
                    group["subject_id"], group["study_id"],
                    group["dicom_id"], row["question"],
                )
                print(f"\n[{q_idx}/{total_q}] {query[:100]}{'...' if len(query) > 100 else ''}")

                entry = _make_result_entry(q_idx, group, row)

                try:
                    t0 = datetime.now()
                    session_id = str(uuid4())
                    resp = await team.arun(query, session_id=session_id)
                    elapsed = (datetime.now() - t0).total_seconds()

                    response_text = (resp.content or "").strip()
                    entry.update({
                        "status": "success",
                        "model_response": response_text,
                        "execution_time": elapsed,
                    })
                    entry["score"] = score_answer(row["question_type"], response_text, row["answer"])
                    print(f"  -> {elapsed:.1f}s | correct={entry['score'].get('correct')}")
                except Exception as e:
                    entry.update({"status": "error", "error": str(e), "execution_time": 0})
                    print(f"  -> ERROR: {e}")
                    traceback.print_exc()

                results.append(entry)
                _maybe_save(results, output_path, last_save_count, total_q)
                if len(results) - last_save_count >= 10:
                    last_save_count = len(results)
    finally:
        await cleanup_workflow()
        await cleanup_imaging_workflow()

    return results


# ---------------------------------------------------------------------------
# Mode: direct (image fetch + imaging agent only)
# ---------------------------------------------------------------------------

async def run_direct_mode(
    groups: List[Dict[str, Any]],
    output_path: Path,
    shutdown_flag: Dict,
    path_lookup_file: Optional[str] = None,
):
    """
    Run evaluation by fetching images directly from HPC and running the imaging agent.
    Skips semantic/database agents entirely.

    If path_lookup_file is provided, reads a JSON mapping {dicom_id: local_path}.
    Otherwise, does a one-time DB query to resolve dicom_id -> local_path for all images.
    """
    from agno_fastomop.workflows.imaging_workflow import initialize_imaging_workflow, cleanup_imaging_workflow
    from agno_fastomop.tools.hpc_image import fetch_hpc_image

    print("Initializing imaging agent for direct mode...")
    imaging_workflow = await initialize_imaging_workflow()
    imaging_agent = imaging_workflow.steps[0].agent
    print("Imaging agent ready.")

    # Resolve dicom_id -> local_path
    path_map = await _resolve_image_paths(groups, path_lookup_file)
    resolved = sum(1 for g in groups if g["dicom_id"] in path_map)
    print(f"Resolved {resolved}/{len(groups)} image paths.")

    results = []
    total_q = sum(len(g["questions"]) for g in groups)
    q_idx = 0
    last_save_count = 0
    image_cache: Dict[str, Any] = {}

    try:
        for gi, group in enumerate(groups):
            if shutdown_flag["flag"]:
                break

            dicom_id = group["dicom_id"]
            remote_path = path_map.get(dicom_id)

            if not remote_path:
                for row in group["questions"]:
                    q_idx += 1
                    entry = _make_result_entry(q_idx, group, row)
                    entry.update({"status": "error", "error": f"No path found for dicom_id={dicom_id}"})
                    results.append(entry)
                    print(f"\n[{q_idx}/{total_q}] SKIP (no path): {dicom_id}")
                continue

            # Fetch image once per group
            image = image_cache.get(dicom_id)
            if image is None:
                try:
                    print(f"\n[Image {gi+1}/{len(groups)}] Fetching {remote_path}...")
                    image = fetch_hpc_image(remote_path=remote_path)
                    image_cache[dicom_id] = image
                    print(f"  Fetched ({len(image.content)} bytes)")
                except Exception as e:
                    print(f"  FETCH ERROR: {e}")
                    for row in group["questions"]:
                        q_idx += 1
                        entry = _make_result_entry(q_idx, group, row)
                        entry.update({"status": "error", "error": f"Image fetch failed: {e}"})
                        results.append(entry)
                    continue

            for row in group["questions"]:
                if shutdown_flag["flag"]:
                    break

                q_idx += 1
                metadata = {
                    "subject_id": group["subject_id"],
                    "study_id": group["study_id"],
                    "dicom_id": dicom_id,
                }
                prompt = compose_direct_prompt(row["question"], metadata)
                print(f"  [{q_idx}/{total_q}] {row['question'][:80]}")

                entry = _make_result_entry(q_idx, group, row)

                try:
                    t0 = datetime.now()
                    resp = imaging_agent.run(input=prompt, images=[image])
                    elapsed = (datetime.now() - t0).total_seconds()

                    response_text = (resp.content or "").strip()
                    entry.update({
                        "status": "success",
                        "model_response": response_text,
                        "execution_time": elapsed,
                    })
                    entry["score"] = score_answer(row["question_type"], response_text, row["answer"])
                    print(f"    -> {elapsed:.1f}s | correct={entry['score'].get('correct')}")
                except Exception as e:
                    entry.update({"status": "error", "error": str(e), "execution_time": 0})
                    print(f"    -> ERROR: {e}")
                    traceback.print_exc()

                results.append(entry)
                _maybe_save(results, output_path, last_save_count, total_q)
                if len(results) - last_save_count >= 10:
                    last_save_count = len(results)

            # Free cached image after all questions for this group are done
            if dicom_id in image_cache and gi < len(groups) - 1:
                next_dicom = groups[gi + 1]["dicom_id"] if gi + 1 < len(groups) else None
                if next_dicom != dicom_id:
                    del image_cache[dicom_id]

    finally:
        await cleanup_imaging_workflow()

    return results


async def _resolve_image_paths(
    groups: List[Dict[str, Any]],
    path_lookup_file: Optional[str] = None,
) -> Dict[str, str]:
    """
    Resolve dicom_id -> local_path (HPC absolute path).

    Priority:
    1. path_lookup_file (JSON {dicom_id: path} or CSV with dicom_id,local_path)
    2. One-time DB query via MCP to get local_path for all dicom_ids
    """
    path_map: Dict[str, str] = {}

    if path_lookup_file:
        p = Path(path_lookup_file)
        if p.suffix == ".json":
            with open(p) as f:
                path_map = json.load(f)
        elif p.suffix == ".csv":
            with open(p, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    did = row.get("dicom_id", "").strip()
                    lp = row.get("local_path", "").strip()
                    if did and lp:
                        path_map[did] = lp
        print(f"Loaded {len(path_map)} paths from {path_lookup_file}")
        return path_map

    # Fallback: query DB for all dicom_ids
    print("No path lookup file provided. Querying DB for image paths...")
    try:
        path_map = await _query_db_for_paths(groups)
    except Exception as e:
        print(f"WARNING: DB path lookup failed: {e}")
        traceback.print_exc()

    return path_map


async def _query_db_for_paths(groups: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    Query the OMOP database via MCP to resolve dicom_id -> local_path.
    Uses a single bulk query for efficiency.
    """
    from agno_fastomop.workflows.omop_workflow import initialize_workflow

    workflow = await initialize_workflow(batch_mode=True)
    db_agent = workflow.steps[1].agent

    dicom_ids = list({g["dicom_id"] for g in groups})
    print(f"Resolving {len(dicom_ids)} unique dicom_ids via DB...")

    # Query in batches to avoid SQL length limits
    BATCH_SIZE = 200
    path_map: Dict[str, str] = {}

    for i in range(0, len(dicom_ids), BATCH_SIZE):
        batch = dicom_ids[i:i + BATCH_SIZE]
        id_list = ", ".join(f"'{did}'" for did in batch)
        query = (
            f"Query the image_occurrence table: "
            f"SELECT dicom_id, local_path FROM image_occurrence "
            f"WHERE dicom_id IN ({id_list})"
        )

        try:
            resp = db_agent.run(input=query)
            content = (resp.content or "").strip()

            for line in content.split("\n"):
                parts = line.split(",")
                if len(parts) >= 2:
                    did = parts[0].strip().strip('"')
                    lp = parts[-1].strip().strip('"')
                    if lp.startswith("/"):
                        path_map[did] = lp
        except Exception as e:
            print(f"  Batch {i//BATCH_SIZE + 1} failed: {e}")

    print(f"Resolved {len(path_map)} paths from DB.")
    return path_map


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result_entry(q_idx: int, group: Dict, row: Dict) -> Dict[str, Any]:
    return {
        "question_id": q_idx,
        "subject_id": group["subject_id"],
        "study_id": group["study_id"],
        "dicom_id": group["dicom_id"],
        "question": row["question"],
        "question_type": row["question_type"],
        "ground_truth": row["answer"],
        "split": row.get("split", ""),
        "timestamp": datetime.now().isoformat(),
    }


def _maybe_save(results, output_path, last_save_count, total_q):
    """Incremental save every 10 results."""
    if len(results) - last_save_count >= 10:
        meta = {
            "status": "in_progress",
            "last_update": datetime.now().isoformat(),
            "total_processed": len(results),
            "total_questions": total_q,
        }
        save_results_safely(results, output_path, meta)
        print(f"  [saved {len(results)} results]")


def compute_summary(results: List[Dict]) -> Dict[str, Any]:
    """Compute evaluation summary statistics."""
    success = [r for r in results if r["status"] == "success"]
    errors = [r for r in results if r["status"] == "error"]

    by_type: Dict[str, Dict] = defaultdict(lambda: {"total": 0, "correct": 0, "errors": 0})

    for r in success:
        qt = r["question_type"]
        by_type[qt]["total"] += 1
        if r.get("score", {}).get("correct"):
            by_type[qt]["correct"] += 1

    for r in errors:
        qt = r.get("question_type", "unknown")
        by_type[qt]["errors"] += 1

    type_summary = {}
    for qt, counts in by_type.items():
        total = counts["total"]
        type_summary[qt] = {
            "total_answered": total,
            "correct": counts["correct"],
            "accuracy": counts["correct"] / total if total > 0 else 0.0,
            "errors": counts["errors"],
        }

    total_answered = len(success)
    total_correct = sum(1 for r in success if r.get("score", {}).get("correct"))
    avg_time = sum(r.get("execution_time", 0) for r in results) / len(results) if results else 0

    return {
        "total_processed": len(results),
        "total_answered": total_answered,
        "total_correct": total_correct,
        "total_errors": len(errors),
        "overall_accuracy": total_correct / total_answered if total_answered > 0 else 0.0,
        "avg_execution_time": avg_time,
        "by_question_type": type_summary,
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser(
        description="Medical CXR VQA Evaluation Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--dataset", required=True, help="Path to medical-cxr-vqa-questions.csv")
    parser.add_argument("--output", help="Output JSON path (default: <dataset>_eval_results.json)")
    parser.add_argument("--mode", choices=["team", "direct"], default="direct",
                        help="Eval mode: 'team' (full pipeline) or 'direct' (imaging agent only)")
    parser.add_argument("--split", help="Filter by split: train, val, test")
    parser.add_argument("--question-type", help="Filter by question type: abnormality, presence, view, type, location, level")
    parser.add_argument("--limit", type=int, help="Max number of questions to process")
    parser.add_argument("--path-lookup", help="JSON or CSV file mapping dicom_id -> local_path (for direct mode)")

    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"ERROR: Dataset not found: {dataset_path}")
        sys.exit(1)

    output_path = Path(args.output) if args.output else dataset_path.parent / f"{dataset_path.stem}_eval_results.json"

    # Set up logging
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = output_path.parent / f"{output_path.stem}_{timestamp}.log"

    shutdown_flag = {"flag": False}

    def signal_handler(signum, frame):
        print(f"\nReceived shutdown signal ({signum}). Saving results...")
        shutdown_flag["flag"] = True

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Open log and tee output
    log_file = open(log_path, "w", encoding="utf-8")
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    sys.stdout = TeeStream(original_stdout, log_file)
    sys.stderr = TeeStream(original_stderr, log_file)

    start_time = datetime.now()
    results = []

    try:
        print("=" * 60)
        print("Medical CXR VQA Evaluation")
        print("=" * 60)
        print(f"Dataset:       {dataset_path}")
        print(f"Mode:          {args.mode}")
        print(f"Split:         {args.split or 'all'}")
        print(f"Question type: {args.question_type or 'all'}")
        print(f"Limit:         {args.limit or 'none'}")
        print(f"Output:        {output_path}")
        print(f"Log:           {log_path}")
        print(f"Started:       {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

        # Load and filter dataset
        print("\nLoading dataset...")
        rows = load_vqa_dataset(dataset_path, split=args.split, question_type=args.question_type, limit=args.limit)
        groups = group_by_image(rows)
        total_q = sum(len(g["questions"]) for g in groups)
        print(f"Loaded {total_q} questions across {len(groups)} unique images")

        if not rows:
            print("No matching questions found. Check filters.")
            sys.exit(0)

        # Print distribution
        type_counts = defaultdict(int)
        for r in rows:
            type_counts[r["question_type"]] += 1
        print("Question type distribution:")
        for qt, count in sorted(type_counts.items(), key=lambda x: -x[1]):
            print(f"  {qt}: {count}")
        print()

        # Run evaluation
        if args.mode == "team":
            results = await run_team_mode(groups, output_path, shutdown_flag)
        else:
            results = await run_direct_mode(groups, output_path, shutdown_flag, args.path_lookup)

    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        shutdown_flag["flag"] = True

    except Exception as e:
        print(f"\nFatal error: {e}")
        traceback.print_exc()

    finally:
        end_time = datetime.now()
        elapsed_total = (end_time - start_time).total_seconds()

        # Compute summary
        summary = compute_summary(results) if results else {}
        summary["total_time_seconds"] = elapsed_total

        metadata = {
            "dataset": str(dataset_path),
            "mode": args.mode,
            "split": args.split,
            "question_type": args.question_type,
            "limit": args.limit,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "status": "interrupted" if shutdown_flag["flag"] else "completed",
        }

        # Final save
        output_doc = {
            "metadata": metadata,
            "summary": summary,
            "results": results,
        }

        print(f"\nSaving final results to {output_path}...")
        try:
            temp_path = output_path.with_suffix(".tmp.json")
            with open(temp_path, "w") as f:
                json.dump(output_doc, f, indent=2, default=str)
            temp_path.replace(output_path)
            print(f"Results saved to {output_path}")
        except Exception as e:
            print(f"ERROR saving results: {e}")

        # Print summary
        print("\n" + "=" * 60)
        print("EVALUATION SUMMARY")
        print("=" * 60)
        print(f"Total questions:  {summary.get('total_processed', 0)}")
        print(f"Answered:         {summary.get('total_answered', 0)}")
        print(f"Correct:          {summary.get('total_correct', 0)}")
        print(f"Errors:           {summary.get('total_errors', 0)}")
        print(f"Overall accuracy: {summary.get('overall_accuracy', 0):.1%}")
        print(f"Avg time/question:{summary.get('avg_execution_time', 0):.1f}s")
        print(f"Total time:       {elapsed_total:.0f}s ({elapsed_total/60:.1f}min)")

        if "by_question_type" in summary:
            print("\nBy question type:")
            for qt, stats in sorted(summary["by_question_type"].items()):
                acc = stats["accuracy"]
                print(f"  {qt:15s}  {stats['correct']:>4d}/{stats['total_answered']:>4d}  ({acc:.1%})  errors={stats['errors']}")

        print("=" * 60)
        print(f"Log: {log_path}")

        # Restore stdout/stderr
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        log_file.close()


if __name__ == "__main__":
    asyncio.run(main())
