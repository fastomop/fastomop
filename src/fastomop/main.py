"""Main entry point for FastOMOP application."""

from doctest import FAIL_FAST
import uvicorn
import asyncio
from fastomop import __version__
from fastomop.otel import tracer
from opentelemetry.trace import SpanKind
from fastomop.agents.supervisor import FastOmopSupervisor
from rich.console import Console
from rich.table import Table

console = Console()




@tracer.start_as_current_span(
    name=__name__, kind=SpanKind.SERVER, attributes={"version": __version__}
)
async def main_async() -> None:
    """Entry point for the fastomop command."""
    supervisor = FastOmopSupervisor()
    print("FastOMOP v2 - pydantic-AI implementation")
    print("----------------------------------------")
    print("Type 'quit', 'exit' or 'q' to quit")
    print("----------------------------------------")

    while True:
        try:
            user_query = input("User: ")
            if user_query.lower() in ["quit", "exit", "q"]:
                print("Goodbye!")
                break

            if not user_query:
                continue

            print ("Processing query...")
            result = await supervisor.process_query(user_query)

            if result.success:
                print(f"\n{result.get_summary()}")
                print(f"\nAssistant: {result.final_answer}")
            else:
                print(f"\nError: {result.final_answer}")

        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}")



def main() -> None:
    """Entry point for the fastomop command."""
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
