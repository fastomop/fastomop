"""Main entry point for FastOMOP application."""

import uvicorn
import asyncio
from fastomop import __version__
from fastomop.otel import tracer
from opentelemetry.trace import SpanKind


def run_a2a():
    from fastomop.agents.sql_agent import app as sqlagent_app

    uvicorn.run(sqlagent_app, port=8000)


async def run_graph():
    # This function is for running the orchestrator graph
    from fastomop.agents.supervisor import graph

    async def stream_graph_updates(user_input: str):
        async for event in graph.astream(
            {"messages": [{"role": "user", "content": user_input}]}
        ):
            for value in event.values():
                print("Assistant:", value["messages"])

    while True:
        user_input = input("User: ")
        if user_input.lower() in ["quit", "exit", "q"]:
            print("Goodbye!")
            break
        await stream_graph_updates(user_input)


@tracer.start_as_current_span(
    name=__name__, kind=SpanKind.SERVER, attributes={"version": __version__}
)
async def main_async() -> None:
    await run_graph()


def main() -> None:
    """Entry point for the fastomop command."""
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
