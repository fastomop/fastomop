"""Settings for the FastOMOP OpenTelemetry integration."""

# This currently uses Langfuse OpenTelemetry for FastOMOP.

from langfuse import Langfuse

from fastomop.config import config as cfg

tracer = Langfuse(
    public_key=cfg.tracer.public_key,
    secret_key=cfg.tracer.secret_key,
    host=cfg.tracer.host,
)


# Verify connection
if tracer.auth_check():
    print("Langfuse client is authenticated and ready!")
else:
    print("Authentication failed. Please check your credentials and host.")
