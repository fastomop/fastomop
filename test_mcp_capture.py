#!/usr/bin/env python3
"""Test script to validate MCP capture wrapper functionality."""

import asyncio
from fastomop.agents.supervisor import FastOmopSupervisor
from fastomop.capture_mcp_wrapper import get_global_capture, clear_global_capture

async def test_mcp_capture():
    """Test the MCP capture wrapper with a simple query."""
    print("🔍 Testing MCP capture wrapper...")

    # Clear any previous captures
    clear_global_capture()

    # Initialize supervisor (which should use our capturing MCP wrapper)
    supervisor = FastOmopSupervisor()

    # Test query
    query = "How many patients are in the database?"
    print(f"🧠 Processing query: {query}")

    # Process query
    result = await supervisor.process_query(query)

    print(f"✅ Query completed: {result.success}")
    print(f"📋 Query result details:")
    print(f"   - semantic_execution: {result.semantic_execution is not None}")
    print(f"   - sql_execution: {result.sql_execution is not None}")
    print(f"   - final_answer: {result.final_answer is not None}")

    if result.semantic_execution and result.semantic_execution.error:
        print(f"   - semantic error: {result.semantic_execution.error}")
    if result.sql_execution and result.sql_execution.error:
        print(f"   - sql error: {result.sql_execution.error}")

    # Check what we captured
    capture = get_global_capture()
    all_calls = capture.get_calls()
    sql_calls = capture.get_sql_calls()

    print(f"\n📊 Capture Results:")
    print(f"   Total MCP calls: {len(all_calls)}")
    print(f"   SQL-related calls: {len(sql_calls)}")

    if all_calls:
        print(f"\n🔍 Captured calls:")
        for i, call in enumerate(all_calls):
            tool_name = call.get('tool_name', 'unknown')
            arguments = call.get('arguments', {})
            result_data = call.get('result')

            print(f"   {i+1}. Tool: {tool_name}")
            print(f"      Arguments: {list(arguments.keys())}")
            print(f"      Has result: {result_data is not None}")

            # Show SQL if present
            if 'query' in arguments:
                sql = arguments['query']
                print(f"      SQL: {sql[:100]}{'...' if len(sql) > 100 else ''}")

            # Show result if present
            if result_data and not isinstance(result_data, dict) or 'error' not in result_data:
                print(f"      Result: {str(result_data)[:100]}{'...' if len(str(result_data)) > 100 else ''}")

        # Test the extraction function
        from fastomop.capture_mcp_wrapper import extract_sql_and_results_from_calls
        extracted = extract_sql_and_results_from_calls(all_calls)
        print(f"\n🔍 Extracted data:")
        print(f"   SQL queries: {len(extracted['sql'])}")
        print(f"   DB results: {len(extracted['results'])}")

        if extracted['sql']:
            for i, sql in enumerate(extracted['sql']):
                print(f"      SQL {i+1}: {sql[:50]}{'...' if len(sql) > 50 else ''}")

        if extracted['results']:
            for i, result in enumerate(extracted['results']):
                print(f"      Result {i+1}: {result}")

        # Test raw MCP data structure for evaluation
        print(f"\n🔧 Raw MCP call structure for evaluation:")
        for i, call in enumerate(all_calls):
            raw_call_data = {
                "tool_name": call.get('tool_name'),
                "arguments": call.get('arguments'),
                "result": call.get('result'),
                "timestamp": call.get('timestamp')
            }
            print(f"   Call {i+1}: {raw_call_data['tool_name']}")
            print(f"      Args keys: {list(raw_call_data['arguments'].keys()) if raw_call_data['arguments'] else []}")
            print(f"      Has result: {raw_call_data['result'] is not None}")
            print(f"      Result type: {type(raw_call_data['result'])}")
            if raw_call_data['result'] and isinstance(raw_call_data['result'], dict):
                print(f"      Result keys: {list(raw_call_data['result'].keys())}")
                if 'content' in raw_call_data['result']:
                    content = raw_call_data['result']['content']
                    if isinstance(content, list) and len(content) > 0:
                        print(f"      Content preview: {content[0].get('text', '')[:100]}...")
            print()

    else:
        print("⚠️  No MCP calls captured!")

    return len(all_calls) > 0

if __name__ == "__main__":
    success = asyncio.run(test_mcp_capture())
    if success:
        print("\n✅ MCP capture test passed!")
    else:
        print("\n❌ MCP capture test failed!")