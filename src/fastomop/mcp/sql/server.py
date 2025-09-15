import os
import time
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent

# Get tracer for this module - Phoenix will be initialized by the client
tracer = trace.get_tracer(__name__)

from .db import OmopDatabase

connection_string = os.environ["DB_CONNECTION_STRING"]

# # Default host and port values, can be overridden via environment variables
# NotImplemented
# host = os.environ.get("MCP_HOST", "localhost")
# port = int(os.environ.get("MCP_PORT", "8000"))

mcp = FastMCP(name="OMOP MCP Server")
db = OmopDatabase(
    connection_string=connection_string,
    cdm_schema=os.environ.get("CDM_SCHEMA", "base"),
    vocab_schema=os.environ.get("VOCAB_SCHEMA", "base"),
)


@mcp.tool(
    name="Get_Information_Schema",
    description="Get the information schema of the OMOP database.",
)
def get_information_schema() -> CallToolResult:
    """Get the information schema of the OMOP database.

    This function retrieves information from the information schema of the OMOP database.
    Information is restricted to only tables and columns allowed by the users configuration.
    Args:
        None
    Returns:
        List of schemas, tables, columns and data types formatted as a CSV string.
    """
    # Get current span for adding attributes
    span = trace.get_current_span()

    # Add operation metadata
    if span and span.is_recording():
        span.set_attribute("db.operation", "information_schema")
        span.set_attribute("db.system", "omop")

    start_time = time.time()

    try:
        result = db.get_information_schema()
        execution_time_ms = (time.time() - start_time) * 1000

        # Add success attributes
        if span and span.is_recording():
            span.set_attribute("db.success", True)
            span.set_attribute("db.execution_time_ms", execution_time_ms)
            # Store a sample of the result (truncated for safety)
            span.set_attribute("db.result.sample", result[:2000] if result else "")
            span.set_attribute("db.result.size_bytes", len(result) if result else 0)
            # Count number of tables returned (lines in CSV)
            table_count = result.count('\n') if result else 0
            span.set_attribute("db.result.table_count", table_count)
            span.set_status(Status(StatusCode.OK))

        return CallToolResult(
            content=[
                TextContent(type="text", text=result),
            ]
        )
    except Exception as e:
        execution_time_ms = (time.time() - start_time) * 1000

        # Add error attributes
        if span and span.is_recording():
            span.set_attribute("db.success", False)
            span.set_attribute("db.execution_time_ms", execution_time_ms)
            span.set_attribute("db.error", str(e))
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))

        return CallToolResult(
            isError=True,
            content=[
                TextContent(
                    type="text",
                    text=f"Failed to retrieve information schema: {str(e)}",
                )
            ],
        )


@mcp.tool(
    name="Select_Query", description="Execute a select query against the OMOP database."
)
def read_query(query: str) -> CallToolResult:
    """Run a SQL query against the OMOP database.

    This function is a tool in the MCP server that allows users to execute SQL queries
    against the OMOP database. Only SELECT queries are allowed. Results are returned as CSV.

    Args:
        query: SQL query to execute
    Returns:
        Result of the query as a string or a detailed error message if the query fails.
    """
    # Get current span for adding attributes
    span = trace.get_current_span()

    # Add the raw SQL query to the span
    if span and span.is_recording():
        span.set_attribute("db.statement", query)
        span.set_attribute("db.system", "omop")
        span.set_attribute("db.operation", "select")

    start_time = time.time()

    try:
        result = db.read_query(query)
        execution_time_ms = (time.time() - start_time) * 1000

        # Add success attributes including the raw result
        if span and span.is_recording():
            span.set_attribute("db.success", True)
            span.set_attribute("db.execution_time_ms", execution_time_ms)

            # Capture the FULL raw result (be careful with large results in production)
            # In production, you might want to limit this or make it configurable
            span.set_attribute("db.result.raw", result if result else "")
            span.set_attribute("db.result.size_bytes", len(result) if result else 0)

            # Count rows returned (CSV lines minus header)
            if result:
                lines = result.strip().split('\n')
                row_count = len(lines) - 1 if len(lines) > 1 else 0
                span.set_attribute("db.result.row_count", row_count)

                # Also store just the headers for quick reference
                if lines:
                    span.set_attribute("db.result.headers", lines[0])
            else:
                span.set_attribute("db.result.row_count", 0)

            span.set_status(Status(StatusCode.OK))

        return CallToolResult(
            content=[
                TextContent(type="text", text=result),
            ]
        )

    except ExceptionGroup as e:
        execution_time_ms = (time.time() - start_time) * 1000
        errors = "\n\n".join(str(i) for i in e.exceptions)

        # Add error attributes
        if span and span.is_recording():
            span.set_attribute("db.success", False)
            span.set_attribute("db.execution_time_ms", execution_time_ms)
            span.set_attribute("db.error", errors)
            span.set_attribute("db.error.type", "validation_error")
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, "Query validation failed"))

        return CallToolResult(
            isError=True,
            content=[
                TextContent(
                    type="text",
                    text=f"Query validation failed with one or more errors:\n {errors}",
                )
            ],
        )
    except Exception as e:
        execution_time_ms = (time.time() - start_time) * 1000

        # Add error attributes
        if span and span.is_recording():
            span.set_attribute("db.success", False)
            span.set_attribute("db.execution_time_ms", execution_time_ms)
            span.set_attribute("db.error", str(e))
            span.set_attribute("db.error.type", type(e).__name__)
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))

        return CallToolResult(
            isError=True,
            content=[
                TextContent(
                    type="text",
                    text=f"Failed to execute query: {str(e)}",
                )
            ],
        )


def main():
    """Main function to run the MCP server."""

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
