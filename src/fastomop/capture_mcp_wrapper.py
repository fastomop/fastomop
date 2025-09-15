"""MCP client wrapper to capture raw tool calls and results."""

from typing import Any, Dict, List, Optional
from pydantic_ai.mcp import MCPServerStdio
from contextlib import asynccontextmanager
import threading
import logging

logger = logging.getLogger(__name__)

class MCPToolCallCapture:
    """Thread-safe storage for captured MCP tool calls and results."""

    def __init__(self):
        self._lock = threading.Lock()
        self._captured_calls: List[Dict[str, Any]] = []

    def add_call(self, tool_name: str, arguments: Dict[str, Any], result: Any):
        """Add a captured tool call and result."""
        with self._lock:
            self._captured_calls.append({
                "tool_name": tool_name,
                "arguments": arguments,
                "result": result,
                "timestamp": __import__("time").time()
            })

    def get_calls(self) -> List[Dict[str, Any]]:
        """Get all captured calls (copy)."""
        with self._lock:
            return self._captured_calls.copy()

    def clear(self):
        """Clear all captured calls."""
        with self._lock:
            self._captured_calls.clear()

    def get_sql_calls(self) -> List[Dict[str, Any]]:
        """Get only SQL-related tool calls."""
        with self._lock:
            return [call for call in self._captured_calls
                   if 'query' in call.get('arguments', {}) or
                      'sql' in call.get('tool_name', '').lower()]

# Global capture instance
_global_capture = MCPToolCallCapture()

class CapturingMCPServerStdio(MCPServerStdio):
    """MCP Server wrapper that captures tool calls and results."""

    def __init__(self, *args, capture_instance: Optional[MCPToolCallCapture] = None, **kwargs):
        print(f"🔧 [MCP WRAPPER] Initializing CapturingMCPServerStdio with args: {args}")
        super().__init__(*args, **kwargs)
        self.capture = capture_instance or _global_capture
        print(f"🔧 [MCP WRAPPER] Wrapper initialized successfully")

    async def call_tool(self, name: str, tool_args: Dict[str, Any], ctx: Any, tool: Any) -> Any:
        """Override call_tool to capture calls and results."""
        print(f"🔧 [MCP WRAPPER] call_tool invoked: {name} with args: {list(tool_args.keys())}")
        logger.debug(f"Capturing MCP tool call: {name} with args: {tool_args}")

        try:
            # Call the original method
            result = await super().call_tool(name, tool_args, ctx, tool)

            # Capture the call and result
            self.capture.add_call(name, tool_args, result)

            print(f"🔧 [MCP WRAPPER] Captured tool result: {type(result)}")
            logger.debug(f"Captured MCP tool result for {name}: {type(result)}")
            return result

        except Exception as e:
            # Also capture failed calls
            self.capture.add_call(name, tool_args, {"error": str(e)})
            print(f"🔧 [MCP WRAPPER] Tool call failed: {e}")
            logger.error(f"MCP tool call failed for {name}: {e}")
            raise

    async def process_tool_call(self, call_data: Any) -> Any:
        """Override process_tool_call if it's used by pydantic-ai."""
        logger.debug(f"Processing tool call: {call_data}")

        try:
            result = await super().process_tool_call(call_data)

            # Try to extract tool name and arguments from call_data
            tool_name = getattr(call_data, 'name', 'unknown')
            arguments = getattr(call_data, 'arguments', {})

            self.capture.add_call(tool_name, arguments, result)
            return result

        except Exception as e:
            logger.error(f"Process tool call failed: {e}")
            raise

def get_global_capture() -> MCPToolCallCapture:
    """Get the global capture instance."""
    return _global_capture

def clear_global_capture():
    """Clear the global capture."""
    _global_capture.clear()

@asynccontextmanager
async def capture_mcp_calls():
    """Context manager to capture MCP calls in a session."""
    capture = MCPToolCallCapture()
    try:
        yield capture
    finally:
        # Capture is automatically cleaned up when context exits
        pass

def extract_sql_and_results_from_calls(calls: List[Dict[str, Any]]) -> Dict[str, List[Any]]:
    """Extract SQL queries and database results from captured MCP calls."""
    sql_queries = []
    db_results = []

    for call in calls:
        # Look for SQL in tool arguments
        args = call.get('arguments', {})
        if 'query' in args:
            sql_queries.append(args['query'])

        # Look for database results in the response
        result = call.get('result')
        if result and isinstance(result, dict) and 'content' in result:
            # Extract CSV data from MCP result content
            content = result['content']
            if isinstance(content, list) and len(content) > 0:
                text_content = content[0].get('text', '')
                if text_content:
                    # Parse CSV text into structured data
                    parsed_result = _parse_csv_result(text_content)
                    if parsed_result is not None:
                        db_results.append(parsed_result)

    return {
        'sql': sql_queries,
        'results': db_results
    }

def _parse_csv_result(csv_text: str) -> Optional[List[List[Any]]]:
    """Parse CSV text result into structured data."""
    try:
        lines = csv_text.strip().split('\n')
        if len(lines) < 2:
            return None

        # Skip header line, parse data rows
        data_rows = []
        for line in lines[1:]:  # Skip header
            if line.strip():
                # Split by common delimiters and try to convert to appropriate types
                values = [_convert_value(val.strip()) for val in line.split()]
                if values:
                    data_rows.append(values)

        return data_rows if data_rows else None
    except Exception:
        return None

def _convert_value(value: str) -> Any:
    """Convert string value to appropriate type."""
    if not value:
        return None

    # Try integer
    try:
        return int(value)
    except ValueError:
        pass

    # Try float
    try:
        return float(value)
    except ValueError:
        pass

    # Return as string
    return value