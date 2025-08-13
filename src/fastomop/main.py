"""Main entry point for FastOMOP application."""

import asyncio
from fastomop.otel import tracer
from fastomop.agents.supervisor import FastOmopSupervisor
from rich.console import Console
from langfuse import observe

console = Console()


@observe(name="FastOMOP.Main")
async def main_async() -> None:
    """Entry point for the fastomop command."""
    supervisor = FastOmopSupervisor()
    print("FastOMOP v2 - pydantic-AI implementation")
    print("----------------------------------------")
    print("Type 'quit', 'exit' or 'q' to quit")
    print("----------------------------------------")

    while True:
        with tracer.start_as_current_span(name="User Query") as span:
            try:
                user_query = input("User: ")
                if user_query.lower() in ["quit", "exit", "q"]:
                    print("Goodbye!")
                    break

                if not user_query:
                    continue

                print("Processing query...")
                result = await supervisor.process_query(user_query)

                if result.success:
                    print(f"\n{result.get_summary()}")
                    print(f"\nAssistant: {result.final_answer}")
                else:
                    print(f"\nError: {result.final_answer}")
                span.update(
                    input={"user_query": user_query},
                    output={"final_answer": result.final_answer},
                    metadata=result.__dict__,
                )

            except KeyboardInterrupt:
                print("\nGoodbye!")
                break
            except Exception as e:
                print(f"\nError: {e}")
            finally:
                tracer.flush()


def main() -> None:
    """Entry point for the fastomop command."""
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
