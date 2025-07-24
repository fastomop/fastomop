"""Main entry point for FastOMOP application."""

import uvicorn
from fastomop.otel import tracer
from fastomop import __version__
from opentelemetry.trace import SpanKind
import asyncio


def run_a2a():
    from fastomop.agents.sqlagent import app as sqlagent_app

    uvicorn.run(sqlagent_app, port=8000)


async def run_graph():
    # This function is for running the orchestrator graph
    from fastomop.agents.orchestrator import graph

    async def stream_graph_updates(user_input: str):
        async for event in graph.astream(
            {"messages": [{"role": "user", "content": user_input}]}
        ):
            for value in event.values():
                print("Assistant:", value["messages"][-1].content)

    while True:
        try:
            user_input = input("User: ")
            if user_input.lower() in ["quit", "exit", "q"]:
                print("Goodbye!")
                break
            await stream_graph_updates(user_input)
        except Exception:
            # fallback if input() is not available
            user_input = "What do you know about LangGraph?"
            print("User: " + user_input)
            await stream_graph_updates(user_input)
            break


@tracer.start_as_current_span(
    name=__name__, kind=SpanKind.SERVER, attributes={"version": __version__}
)
async def main() -> None:
    await run_graph()


if __name__ == "__main__":
    asyncio.run(main())
