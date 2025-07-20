"""Main entry point for FastOMOP application."""

import uvicorn
from fastomop.otel import tracer
from fastomop import __version__
from opentelemetry.trace import SpanKind


@tracer.start_as_current_span(
    name=__name__, kind=SpanKind.SERVER, attributes={"version": __version__}
)
def main() -> None:
    # Initialize and run the User facing agent
    # For now, just run the SQLagent as an example

    from fastomop.agents.sqlagent import app as sqlagent_app

    uvicorn.run(sqlagent_app, port=8000)


if __name__ == "__main__":
    main()
