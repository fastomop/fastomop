"""Settings for the FastOMOP OpenTelemetry integration with unified MCP tracing."""

# This uses standard OpenTelemetry with MCP instrumentation for FastOMOP.
# Phoenix is disabled to avoid connection issues during testing.

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, BatchSpanProcessor
from openinference.instrumentation.mcp import MCPInstrumentor
from fastomop.config import config as cfg
import fastomop

# Initialize standard OpenTelemetry with console output
tracer_provider = TracerProvider()
console_exporter = ConsoleSpanExporter()
span_processor = BatchSpanProcessor(console_exporter)
tracer_provider.add_span_processor(span_processor)

# Set the global tracer provider
trace.set_tracer_provider(tracer_provider)

# Instrument MCP for unified tracing between client and server
instrumentor = MCPInstrumentor()
if not instrumentor.is_instrumented_by_opentelemetry:
    instrumentor.instrument()

tracer = tracer_provider.get_tracer(
    instrumenting_module_name=fastomop.__name__,
    instrumenting_library_version=fastomop.__version__,
)
