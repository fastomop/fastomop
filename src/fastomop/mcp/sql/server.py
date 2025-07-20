import os


from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent
from fastomop.otel import tracer
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
@tracer.tool(name="MCP.Get_Information_Schema")
def get_information_schema() -> CallToolResult:
    """Get the information schema of the OMOP database.

    This function retrieves information from the information schema of the OMOP database.
    Information is restricted to only tables and columns allowed by the users configuration.
    Args:
        None
    Returns:
        List of schemas, tables, columns and data types formatted as a CSV string.
    """
    try:
        result = db.get_information_schema()
        return CallToolResult(
            content=[
                TextContent(type="text", text=result),
            ]
        )
    except Exception as e:
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
@tracer.tool(name="MCP.Select_Query")
def read_query(query: str) -> CallToolResult:
    """Run a SQL query against the OMOP database.

    This function is a tool in the MCP server that allows users to execute SQL queries
    against the OMOP database. Only SELECT queries are allowed. Results are returned as CSV.

    Args:
        query: SQL query to execute
    Returns:
        Result of the query as a string or a detailed error message if the query fails.
    """
    try:
        result = db.read_query(query)
        return CallToolResult(
            content=[
                TextContent(type="text", text=result),
            ]
        )

    except ExceptionGroup as e:
        errors = "\n\n".join(str(i) for i in e.exceptions)
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
