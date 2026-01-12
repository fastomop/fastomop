import asyncio
from agno_fastomop.workflows.omop_workflow import run_omop_query, cleanup_workflow
import argparse
import sys
from pathlib import Path
import json
from datetime import datetime
from uuid import uuid4
import logging
import signal


def save_results_safely(results, output_path, metadata=None):
    """Save results to JSON file with atomic write (write to temp, then rename)

    Args:
        results: List of result dictionaries
        output_path: Path to output file
        metadata: Optional metadata dictionary
    """
    output_path = Path(output_path)
    temp_path = output_path.with_suffix('.tmp.json')

    output_doc = {
        "metadata": metadata or {},
        "results": results,
    }

    try:
        # Write to temp file first
        with open(temp_path, 'w') as f:
            json.dump(output_doc, f, indent=2)

        # Atomic rename (on most systems)
        temp_path.replace(output_path)
        return True
    except Exception as e:
        print(f"Error saving results: {e}")
        # Try to clean up temp file
        if temp_path.exists():
            try:
                temp_path.unlink()
            except:
                pass
        return False


class TeeStream:
    """Stream that writes to both terminal and file (like Unix 'tee' command)"""
    def __init__(self, terminal, log_file):
        self.terminal = terminal
        self.log_file = log_file

    def write(self, message):
        self.terminal.write(message)
        self.log_file.write(message)
        self.log_file.flush()  # Ensure immediate write

    def flush(self):
        self.terminal.flush()
        self.log_file.flush()

    def isatty(self):
        return self.terminal.isatty()


async def interactive_session():
    """Interactive CLI session with persistent agents and memory"""

    print("Welcome to FastOMOP - the OMOP Clinical Query Workflow")
    print("="*50)
    print("Initializing agents (this may take a moment)...")

    # Generate session and user IDs for memory persistence
    session_id = str(uuid4())
    user_id = "default_user"

    try:
        # Initialize workflow once
        from agno_fastomop.workflows.omop_workflow import initialize_workflow
        await initialize_workflow()

        print("Agents initialized! Enter your query or type 'exit' to quit")
        print(f"Session ID: {session_id}")
        print("="*50)

        while True:
            user_query = input("Enter your query: ")
            if user_query.lower() == "exit":
                print("Shutting down...")
                await cleanup_workflow()
                print("Goodbye!")
                break

            try:
                print("Processing...")
                response = await run_omop_query(user_query, session_id=session_id, user_id=user_id)
                print("="*50)
                print(response.content)
                print("="*50)

            except Exception as e:
                print(f"Error: {e}")
                print("Please try again")

    except Exception as e:
        print(f"Failed to initialize: {e}")
        await cleanup_workflow()


async def batch_mode(dataset_path, output_path=None, limit=None):
    """Batch mode for processing multiple queries from a file

    Args:
        dataset_path: Path to the file containing queries
        output_path: Path to the file to save the results
        limit: Maximum number of queries to process (None = all queries)
    """

    input_file = Path(dataset_path)
    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    if output_path is None:
        output_path = input_file.parent / f"{input_file.stem}_results.json"

    # Set up log file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file_path = input_file.parent / f"{input_file.stem}_execution_{timestamp}.log"

    # Signal handling for graceful shutdown
    shutdown_requested = {"flag": False}

    def signal_handler(signum, frame):
        print(f"\n⚠️  Received shutdown signal ({signum}). Saving results and exiting...")
        shutdown_requested["flag"] = True

    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    print("FastOMOP - Batch Mode")
    print("="*50)
    print(f"Processing {input_file} and saving results to {output_path}")
    print(f"Execution log will be saved to {log_file_path}")
    print("="*50)

    # Open log file and redirect all output (stdout/stderr) to both terminal and file
    log_file = open(log_file_path, 'w', encoding='utf-8')
    original_stdout = sys.stdout
    original_stderr = sys.stderr

    # Redirect stdout and stderr to capture ALL terminal output
    sys.stdout = TeeStream(original_stdout, log_file)
    sys.stderr = TeeStream(original_stderr, log_file)

    print(f"\n=== Batch execution started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
    print(f"Input file: {input_file}")
    print(f"Output file: {output_path}")
    print(f"Log file: {log_file_path}")

    try:  # Main try block for stdout/stderr restoration
        try:
            with open(input_file, "r") as f:
                dataset = json.load(f)

            if isinstance(dataset, list):
                queries = dataset
            elif isinstance(dataset, dict) and "queries" in dataset:
                queries = dataset["queries"]
            elif isinstance(dataset, dict) and "text" in dataset:
                queries = dataset["text"]
            else:
                raise ValueError("Input file must contain a list of queries")

            # Apply limit if specified
            if limit is not None and limit > 0:
                queries = queries[:limit]
                print(f"Found {len(queries)} queries in the dataset (limited from total)")
            else:
                print(f"Found {len(queries)} queries in the dataset")
            print("="*50)

        except json.JSONDecodeError as e:
            print(f"Error parsing JSON: {e}")
            print("Please check the input file format")
            sys.exit(1)

        except Exception as e:
            print(f"Error processing queries: {e}")
            print("Please try again")
            sys.exit(1)

        print("Processing queries...")
        print("="*50)
        start_time = datetime.now()

        # Each batch gets its own session (queries within batch share context)
        session_id = str(uuid4())
        user_id = "batch_user"
        print(f"Batch Session ID: {session_id}")

        results = []
        last_save_count = 0

        for i, query_item in enumerate(queries, 1):
            # Check for shutdown signal
            if shutdown_requested["flag"]:
                print(f"\n⚠️  Shutdown requested. Processed {i-1}/{len(queries)} queries.")
                break

            if isinstance(query_item, str):
                query_text = query_item
                query_metadata = {}
            elif isinstance(query_item, dict):
                query_text = query_item.get("query") or query_item.get("question") or query_item.get("text") or query_item.get("input")
                query_metadata = {k: v for k, v in query_item.items() if k not in ['query', 'question', 'text', 'input']}
            else:
                raise ValueError(f"Invalid query item: {query_item}")

            if not query_text:
                print(f"Skipping empty query {i}")
                continue

            print(f"\n[{i}/{len(queries)}] Processing: {query_text[:80]}{'...' if len(query_text) > 80 else ''}")

            result_entry = {
                "query_id": i,
                "query": query_text,
                "metadata": query_metadata,
                "timestamp": datetime.now().isoformat(),
            }

            try:
                query_start = datetime.now()
                result = await run_omop_query(query_text, session_id=session_id, user_id=user_id, batch_mode=True)
                query_end = datetime.now()

                result_entry.update({
                    "status": "success",
                    "response": result.content,
                    "sql_query": getattr(result, 'sql_query', None),
                    "raw_csv_result": getattr(result, 'raw_csv_result', None),
                    "execution_time": (query_end - query_start).total_seconds(),
                })
                print(f"Query {i} completed in {result_entry['execution_time']:.2f} seconds")
            except Exception as e:
                result_entry.update({
                    "status": "error",
                    "error": str(e),
                    "execution_time": (datetime.now() - query_start).total_seconds(),
                })
                print(f"Query {i} failed: {str(e)[:100]}")

            results.append(result_entry)

            # Incremental save every 10 queries or on error
            if len(results) - last_save_count >= 10 or result_entry["status"] == "error":
                temp_metadata = {
                    "input_file": str(input_file),
                    "output_file": str(output_path),
                    "start_time": start_time.isoformat(),
                    "last_update": datetime.now().isoformat(),
                    "total_queries_processed": len(results),
                    "total_queries_in_dataset": len(queries),
                    "status": "in_progress",
                }
                if save_results_safely(results, output_path, temp_metadata):
                    last_save_count = len(results)
                    print(f"💾 Progress saved ({len(results)} queries)")

            # Check for shutdown after save
            if shutdown_requested["flag"]:
                print(f"\n⚠️  Shutdown requested after query {i}. Saving final results...")
                break

    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user (Ctrl+C). Saving results...")
        shutdown_requested["flag"] = True

    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # ALWAYS save results and cleanup, even on crash/interrupt
        try:
            # Cleanup workflow
            print("\nCleaning up resources...")
            await cleanup_workflow()
        except Exception as e:
            print(f"Error during cleanup: {e}")

        # Calculate final statistics
        end_time = datetime.now()
        success_count = sum(1 for r in results if r['status'] == 'success')
        error_count = len(results) - success_count
        avg_time = sum(r['execution_time'] for r in results) / len(results) if results else 0

        # Prepare final metadata
        final_metadata = {
            "input_file": str(input_file),
            "output_file": str(output_path),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "total_time": (end_time - start_time).total_seconds(),
            "total_queries": len(results),
            "total_queries_in_dataset": len(queries),
            "successful_queries": success_count,
            "failed_queries": error_count,
            "average_execution_time": avg_time,
            "status": "interrupted" if shutdown_requested["flag"] else "completed",
        }

        # ALWAYS save final results (atomic write)
        print(f"\n💾 Saving final results to {output_path}...")
        if save_results_safely(results, output_path, final_metadata):
            print(f"✓ Results saved successfully to {output_path}")
        else:
            print(f"❌ Failed to save results to {output_path}")
            # Try backup location
            backup_path = output_path.with_suffix('.backup.json')
            print(f"Attempting backup save to {backup_path}...")
            if save_results_safely(results, backup_path, final_metadata):
                print(f"✓ Backup saved to {backup_path}")

        # Print summary
        print("="*50)
        print("Batch mode completed" if not shutdown_requested["flag"] else "Batch mode interrupted")
        print("="*50)
        print(f"Total queries: {len(results)}")
        print(f"Successful: {success_count}")
        print(f"Failed: {error_count}")
        print(f"Average execution time: {avg_time:.2f} seconds")
        print(f"Total time: {(end_time - start_time).total_seconds():.2f} seconds")
        print(f"Execution log saved to: {log_file_path}")
        print("="*50)

        # Always restore stdout/stderr and close log file
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        log_file.close()

        return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FastOMOP - OMOP Clinical Query Workflow")
    parser.add_argument("--batch", type=str, help="Path to the dataset file")
    parser.add_argument("--output", type=str, help="Path to the output file")
    parser.add_argument("--limit", type=int, help="Limit number of queries to process (default: all)")
    args = parser.parse_args()

    if args.batch:
        asyncio.run(batch_mode(args.batch, args.output, args.limit))
    else:
        asyncio.run(interactive_session())