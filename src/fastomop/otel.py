"""Settings for the FastOMOP OpenTelemetry integration."""

# This currently uses Arize Phoenix OpenTelemetry for FastOMOP.

from phoenix.otel import register
from fastomop.config import config as cfg
import fastomop


tracer_provider = register(
    project_name=cfg.tracer.project_name,
    auto_instrument=cfg.tracer.auto_instrument,  # Automatically trace all calls made to a library
    endpoint=cfg.tracer.endpoint,
    batch=cfg.tracer.batch,  # Use batch processing for better performance
)

tracer = tracer_provider.get_tracer(
    instrumenting_module_name=fastomop.__name__,
    instrumenting_library_version=fastomop.__version__,
)
