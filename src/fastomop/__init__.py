__version__ = "0.1.0"

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

import fastomop.otel  # noqa F401


print("FastOMOP initialized with OpenTelemetry support.")
