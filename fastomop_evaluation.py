#!/usr/bin/env python3
"""
Unified MCP-Traced FastOMOP Agent Evaluation

This script uses the openinference-instrumentation-mcp package to create
unified traces that capture SQL and DB results from the MCP server within
the same trace as the agent execution.
"""

import json
import time
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
import re

# Import OpenTelemetry components first
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanProcessor

# Import FastOMOP components
from fastomop.agents.supervisor import FastOmopSupervisor, QueryResult
from fastomop.capture_mcp_wrapper import get_global_capture, clear_global_capture, extract_sql_and_results_from_calls

# For SQL comparison
import difflib


class MCPSpanCollector(SpanProcessor):
    """Custom span processor to collect MCP SQL queries and database results."""

    def __init__(self):
        self.captured_data = {}  # trace_id -> {"sql": [], "results": []}

    def on_start(self, span: ReadableSpan, parent_context=None) -> None:
        pass

    def on_end(self, span: ReadableSpan) -> None:
        """Capture SQL and results when MCP spans end."""
        if not span:
            return

        span_name = span.name
        trace_id = span.get_span_context().trace_id

        # Initialize trace data if not exists
        if trace_id not in self.captured_data:
            self.captured_data[trace_id] = {
                "sql": [],
                "results": [],
                "sql_execution_pairs": [],  # Track SQL+result pairs together
                "all_spans": []  # Debug: store all spans for analysis
            }

        # Debug: Store ALL spans for analysis
        attributes = span.attributes or {}
        self.captured_data[trace_id]["all_spans"].append({
            "name": span_name,
            "attributes": dict(attributes) if attributes else {},
            "start_time": span.start_time,
            "end_time": span.end_time
        })

        # Debug: Print EVERY span to see what we're getting
        print(f"🔍 DEBUG: Span '{span_name}' (trace: {trace_id.to_bytes(16, 'big').hex()[-8:]})")
        if attributes:
            # Look for any db, mcp, tool, sql related attributes
            relevant_attrs = {k: v for k, v in attributes.items()
                            if any(keyword in k.lower() for keyword in ['db', 'mcp', 'tool', 'sql', 'statement', 'result'])}
            if relevant_attrs:
                print(f"🔍 DEBUG: Relevant attributes: {list(relevant_attrs.keys())}")

        # Look for MCP SQL execution spans - be more inclusive
        is_mcp_span = any(pattern in span_name.lower() for pattern in [
            "select_query", "mcp", "sql", "db", "tool", "call", "execute"
        ])

        if is_mcp_span:
            print(f"🎯 POTENTIAL MCP SPAN: {span_name}")

            # Capture SQL statement and result as a pair
            sql_query = attributes.get("db.statement")
            raw_result = attributes.get("db.result.raw")

            if sql_query:
                self.captured_data[trace_id]["sql"].append(sql_query)
                print(f"🎯 Captured SQL #{len(self.captured_data[trace_id]['sql'])}: {sql_query[:100]}...")

            if raw_result:
                print(f"🎯 Captured raw result #{len(self.captured_data[trace_id]['results']) + 1}: {len(raw_result)} chars")
                # Parse CSV/TSV result to structured data
                parsed_result = self._parse_result_data(raw_result)
                if parsed_result is not None:
                    self.captured_data[trace_id]["results"].append(parsed_result)

            # Store as execution pair if both SQL and result are present
            if sql_query and raw_result:
                parsed_result = self._parse_result_data(raw_result)
                execution_pair = {
                    "sql": sql_query,
                    "raw_result": raw_result,
                    "parsed_result": parsed_result,
                    "execution_order": len(self.captured_data[trace_id]["sql_execution_pairs"]) + 1,
                    "span_name": span_name,
                    "execution_time_ms": attributes.get("db.execution_time_ms"),
                    "success": attributes.get("db.success", True)
                }
                self.captured_data[trace_id]["sql_execution_pairs"].append(execution_pair)
                print(f"📝 Stored execution pair #{execution_pair['execution_order']}")

    def _parse_result_data(self, raw_data: str) -> Optional[List[List[Any]]]:
        """Parse CSV/TSV result into list of lists."""
        if not raw_data or not raw_data.strip():
            return None

        try:
            lines = raw_data.strip().split('\n')
            if len(lines) <= 1:  # Only header or empty
                return []

            # Skip header, convert values
            result = []
            for line in lines[1:]:  # Skip header
                # Try tab-separated first, then comma-separated
                values = line.split('\t') if '\t' in line else line.split(',')
                converted_values = []
                for value in values:
                    value = value.strip()
                    try:
                        # Try integer first
                        converted_values.append(int(value))
                    except ValueError:
                        try:
                            # Try float
                            converted_values.append(float(value))
                        except ValueError:
                            # Keep as string
                            converted_values.append(value)
                result.append(converted_values)

            return result
        except Exception as e:
            print(f"❌ Error parsing result data: {e}")
            return None

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


# Initialize the span collector
mcp_collector = MCPSpanCollector()

# Import FastOMOP tracing and add our collector
from fastomop.otel import tracer, tracer_provider
tracer_provider.add_span_processor(mcp_collector)

print("MCP span collector initialized for trace extraction")
print("Phoenix UI should be available at: http://localhost:6006")


class UnifiedMCPEvaluator:
    """Evaluator using unified MCP tracing to capture SQL and DB results."""

    def __init__(self, dataset_path: str, limit: Optional[int] = None):
        self.dataset_path = Path(dataset_path)

        # Load dataset
        with open(self.dataset_path, 'r') as f:
            self.dataset = json.load(f)

        # Apply limit if specified
        if limit:
            self.dataset = self.dataset[:limit]
            print(f"🔬 Limited to {len(self.dataset)} queries for testing")

        # Initialize supervisor
        self.supervisor = FastOmopSupervisor()

        # Reference to our span collector for extracting data
        self.mcp_collector = mcp_collector

        # Results storage
        self.evaluation_results = []

    @tracer.start_as_current_span("unified_evaluation.run_full_evaluation")
    async def run_evaluation(self) -> Dict[str, Any]:
        """Run the complete evaluation with unified MCP tracing."""
        span = trace.get_current_span()

        if span and span.is_recording():
            span.set_attribute("evaluation.type", "unified_mcp")
            span.set_attribute("evaluation.dataset_size", len(self.dataset))

        print(f"Starting unified MCP evaluation of {len(self.dataset)} queries...")

        start_time = time.time()

        for i, query_item in enumerate(self.dataset, 1):
            print(f"🧠 Evaluating query {i}/{len(self.dataset)} (ID: {query_item['id']})")

            result = await self._evaluate_single_query(query_item, i)
            self.evaluation_results.append(result)

            if i % 5 == 0:
                print(f"✅ Completed {i} queries...")

        total_time = time.time() - start_time

        # Calculate metrics
        metrics = self._calculate_metrics()

        # Create report
        report = {
            "evaluation_summary": {
                "evaluation_type": "unified_mcp",
                "dataset_path": str(self.dataset_path),
                "total_queries": len(self.dataset),
                "evaluation_time_seconds": total_time,
                "timestamp": datetime.now().isoformat(),
                **metrics
            },
            "detailed_results": self.evaluation_results
        }

        return report

    @tracer.start_as_current_span("unified_evaluation.single_query")
    async def _evaluate_single_query(self, query_item: Dict[str, Any], query_index: int) -> Dict[str, Any]:
        """Evaluate a single query with unified MCP tracing."""
        span = trace.get_current_span()
        query_id = query_item["id"]
        natural_language_query = query_item["text"]

        if span and span.is_recording():
            span.set_attribute("query.id", query_id)
            span.set_attribute("query.natural_language", natural_language_query)
            span.set_attribute("query.ground_truth_sql", query_item["sql"])
            span.set_attribute("query.ground_truth_result", str(query_item["result"]))

        start_time = time.time()

        try:
            # Process query through supervisor - this will create unified traces
            # that include the MCP SQL calls with their SQL and results
            supervisor_result = await self.supervisor.process_query(natural_language_query)

            execution_time = time.time() - start_time

            # Extract SQL and results from captured MCP tool calls
            trace_id = span.get_span_context().trace_id if span else None
            trace_id_hex = trace_id.to_bytes(16, 'big').hex() if trace_id else None

            # Get captured SQL and results from our MCP wrapper
            mcp_capture = get_global_capture()
            all_calls = mcp_capture.get_calls()
            sql_calls = mcp_capture.get_sql_calls()

            print(f"MCP Capture Summary:")
            print(f"   📊 Total MCP calls: {len(all_calls)}")
            print(f"   📊 SQL-related calls: {len(sql_calls)}")

            # Extract SQL and results from captured calls
            extracted_data = extract_sql_and_results_from_calls(all_calls)
            captured_sql = extracted_data['sql']
            captured_results = extracted_data['results']

            print(f"   📊 Extracted {len(captured_sql)} SQL queries")
            print(f"   📊 Extracted {len(captured_results)} results")

            # Debug: Show all captured calls
            for i, call in enumerate(all_calls):
                tool_name = call.get('tool_name', 'unknown')
                has_query = 'query' in call.get('arguments', {})
                has_result = call.get('result') is not None
                print(f"      {i+1}. {tool_name} {'(has query)' if has_query else ''} {'(has result)' if has_result else ''}")

            # For evaluation, we need to determine which result to compare
            # Strategy: Use the final/main query result (usually the last one)
            # or the one that matches the expected result structure
            if captured_results:
                expected_result = query_item["result"]
                # Try to find the result that matches expected structure
                best_result_match = self._find_best_result_match(captured_results, expected_result)
                if best_result_match is not None:
                    # Use the best matching result for comparison
                    captured_results = [captured_results[best_result_match]]
                    captured_sql = [captured_sql[best_result_match]] if best_result_match < len(captured_sql) else captured_sql
                    print(f"🎯 Using result #{best_result_match + 1} for evaluation (best match)")

            # Capture raw MCP tool call data for manual inspection
            raw_mcp_calls = []
            for call in all_calls:
                raw_mcp_calls.append({
                    "tool_name": call.get('tool_name'),
                    "arguments": call.get('arguments'),
                    "result": call.get('result'),
                    "timestamp": call.get('timestamp')
                })

            # Clear the global capture for the next query
            clear_global_capture()

            # Compare with ground truth
            sql_comparison = {"match": False, "similarity": 0.0}
            result_comparison = {"match": False}

            if captured_sql:
                primary_sql = captured_sql[0]
                sql_comparison = self._compare_sql_queries(
                    query_item["sql"],
                    primary_sql
                )

            # Compare database results if we captured them
            if captured_results:
                primary_result = captured_results[0]
                result_comparison = self._compare_results(
                    query_item["result"],
                    primary_result
                )

            result = {
                "query_id": query_id,
                "natural_language_query": natural_language_query,
                "ground_truth_sql": query_item["sql"],
                "ground_truth_result": query_item["result"],
                "agent_success": supervisor_result.success,
                "execution_time_seconds": execution_time,
                "trace_id": trace_id_hex,

                # Captured from unified MCP traces
                "captured_sql_queries": captured_sql,
                "captured_db_results": captured_results,

                # Raw MCP tool call data for manual inspection
                "raw_mcp_tool_calls": raw_mcp_calls,
                "mcp_call_count": len(all_calls),
                "sql_tool_call_count": len(sql_calls),

                # Comparisons
                "sql_match": sql_comparison["match"],
                "sql_similarity": sql_comparison["similarity"],
                "result_match": result_comparison["match"],

                # Agent details
                "final_answer": supervisor_result.final_answer,
                "agent_workflow_success": supervisor_result.success,

                # Trace information for later inspection
                "has_unified_trace": trace_id is not None
            }

            if span and span.is_recording():
                span.set_attribute("query.agent_success", supervisor_result.success)
                span.set_attribute("query.sql_captured", len(captured_sql))
                span.set_attribute("query.results_captured", len(captured_results))
                span.set_attribute("query.sql_match", sql_comparison["match"])
                span.set_attribute("query.result_match", result_comparison["match"])
                span.set_attribute("query.trace_id", trace_id_hex or "")
                span.set_status(Status(StatusCode.OK))

        except Exception as e:
            execution_time = time.time() - start_time

            result = {
                "query_id": query_id,
                "natural_language_query": natural_language_query,
                "ground_truth_sql": query_item["sql"],
                "ground_truth_result": query_item["result"],
                "agent_success": False,
                "execution_time_seconds": execution_time,
                "error": str(e),
                "captured_sql_queries": [],
                "captured_db_results": [],
                "raw_mcp_tool_calls": [],
                "mcp_call_count": 0,
                "sql_tool_call_count": 0,
                "sql_match": False,
                "sql_similarity": 0.0,
                "result_match": False,
                "has_unified_trace": False
            }

            if span and span.is_recording():
                span.set_attribute("query.error", str(e))
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))

        return result

    def _extract_sql_from_text(self, text: str) -> Optional[str]:
        """Extract SQL query from text (fallback method)."""
        if not text:
            return None

        # Look for SQL patterns
        sql_patterns = [
            r'```sql\s*(.*?)\s*```',
            r'```\s*(SELECT.*?)\s*```',
            r'(SELECT\s+.*?;)',
            r'(SELECT\s+.*?)(?=\n\n|\Z)',
        ]

        for pattern in sql_patterns:
            matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)
            if matches:
                return max(matches, key=len).strip()

        return None

    def _compare_sql_queries(self, ground_truth_sql: str, generated_sql: str) -> Dict[str, Any]:
        """Compare SQL queries."""
        def normalize_sql(sql):
            if not sql:
                return ""
            # Remove extra whitespace and normalize case
            normalized = re.sub(r'\s+', ' ', sql.strip().upper())
            return normalized

        ground_truth_normalized = normalize_sql(ground_truth_sql)
        generated_normalized = normalize_sql(generated_sql)

        # Check exact match
        exact_match = ground_truth_normalized == generated_normalized

        # Calculate similarity
        similarity = difflib.SequenceMatcher(
            None, ground_truth_normalized, generated_normalized
        ).ratio()

        return {
            "match": exact_match,
            "similarity": similarity,
            "ground_truth_normalized": ground_truth_normalized,
            "generated_normalized": generated_normalized
        }

    def _find_best_result_match(self, captured_results: List[List[List[Any]]], expected_result: List[List[Any]]) -> Optional[int]:
        """Find the result that best matches the expected result structure."""
        if not captured_results or not expected_result:
            return None

        best_match_index = None
        best_score = -1

        for i, result in enumerate(captured_results):
            if not result:
                continue

            # Score based on structural similarity
            score = 0

            # Same number of rows
            if len(result) == len(expected_result):
                score += 10

            # Same number of columns (if both have rows)
            if result and expected_result and len(result[0]) == len(expected_result[0]):
                score += 10

            # Same values (exact match)
            if result == expected_result:
                score += 100
                return i  # Perfect match, return immediately

            # For single-value results (common in COUNT queries), check the value
            if (len(result) == 1 and len(result[0]) == 1 and
                len(expected_result) == 1 and len(expected_result[0]) == 1):
                if result[0][0] == expected_result[0][0]:
                    score += 50

            # Size-based scoring - prefer results closer to expected size
            if len(result) > 0:
                size_similarity = 1.0 / (1.0 + abs(len(result) - len(expected_result)))
                score += int(size_similarity * 5)

            if score > best_score:
                best_score = score
                best_match_index = i

        return best_match_index

    def _compare_results(self, expected_result: List[List[Any]], actual_result: List[List[Any]]) -> Dict[str, Any]:
        """Compare results."""
        if actual_result is None:
            return {"match": False, "error": "No result captured"}

        # Check exact match
        exact_match = expected_result == actual_result

        return {
            "match": exact_match,
            "expected_rows": len(expected_result),
            "actual_rows": len(actual_result)
        }

    def _calculate_metrics(self) -> Dict[str, Any]:
        """Calculate evaluation metrics."""
        total_queries = len(self.evaluation_results)
        successful_agents = sum(1 for r in self.evaluation_results if r["agent_success"])
        sql_matches = sum(1 for r in self.evaluation_results if r.get("sql_match", False))
        result_matches = sum(1 for r in self.evaluation_results if r.get("result_match", False))

        # Unified trace stats
        unified_traces = sum(1 for r in self.evaluation_results if r.get("has_unified_trace", False))
        sql_captured = sum(1 for r in self.evaluation_results if r.get("captured_sql_queries"))

        return {
            "total_queries": total_queries,
            "agent_success_rate": successful_agents / total_queries if total_queries > 0 else 0,
            "sql_accuracy": sql_matches / total_queries if total_queries > 0 else 0,
            "result_accuracy": result_matches / total_queries if total_queries > 0 else 0,
            "unified_trace_rate": unified_traces / total_queries if total_queries > 0 else 0,
            "sql_captured_rate": sql_captured / total_queries if total_queries > 0 else 0,
            "successful_agents": successful_agents,
            "sql_matches": sql_matches,
            "result_matches": result_matches,
            "unified_traces": unified_traces,
            "sql_captured": sql_captured
        }

    def save_report(self, report: Dict[str, Any], output_path: str):
        """Save report to JSON file."""
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2, default=str)

        print(f"📄 Report saved to: {output_file}")

    def print_summary(self, report: Dict[str, Any]):
        """Print evaluation summary."""
        summary = report["evaluation_summary"]

        print("\n" + "="*80)
        print("🔗 UNIFIED MCP FASTOMOP EVALUATION SUMMARY")
        print("="*80)
        print(f"📊 Dataset: {summary['dataset_path']}")
        print(f"⏱️  Total Time: {summary['evaluation_time_seconds']:.2f} seconds")
        print(f"🔢 Total Queries: {summary['total_queries']}")
        print(f"🤖 Agent Success Rate: {summary['agent_success_rate']:.2%}")
        print(f"🎯 SQL Accuracy: {summary['sql_accuracy']:.2%}")
        print(f"🎯 Result Accuracy: {summary['result_accuracy']:.2%}")
        print(f"🔗 Unified Trace Rate: {summary['unified_trace_rate']:.2%}")
        print(f"📥 SQL Captured Rate: {summary['sql_captured_rate']:.2%}")
        print("="*80)

        # Show trace IDs for Phoenix inspection
        trace_ids = [r.get("trace_id") for r in report["detailed_results"] if r.get("trace_id")]
        if trace_ids:
            print(f"\n🔍 First few trace IDs for Phoenix inspection:")
            for i, trace_id in enumerate(trace_ids[:3], 1):
                print(f"  {i}. {trace_id}")

        print(f"\n Phoenix UI: http://localhost:6006")


async def main():
    """Main function."""
    import argparse

    parser = argparse.ArgumentParser(description="Run unified MCP-traced FastOMOP evaluation")
    parser.add_argument("--dataset", required=True, help="Path to dataset JSON file")
    parser.add_argument("--output", default="fastomop_evaluation_report.json", help="Output report file")
    parser.add_argument("--limit", type=int, help="Limit number of queries to process (for testing)")

    args = parser.parse_args()

    evaluator = UnifiedMCPEvaluator(dataset_path=args.dataset, limit=args.limit)

    try:
        # Run evaluation
        report = await evaluator.run_evaluation()

        # Save report
        evaluator.save_report(report, args.output)

        # Print summary
        evaluator.print_summary(report)

        print(f"\n🎉 Evaluation complete!")
        print(f"📊 Report: {args.output}")

    except Exception as e:
        print(f"💥 Evaluation failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())