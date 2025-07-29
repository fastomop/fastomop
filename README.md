# FastOMOP


**Detailed documentation to follow**


## Get started

1. Clone the repo
2. Run `uv sync --extra mcp-duckdb` or `uv sync --extra mcp-postgres` depending on where your OMOP data is.
3. Setup Open Telemetry tracing with Arize-AI Phoenix (`docker run -p 6006:6006 -p 4317:4317 -i -t arizephoenix/phoenix:latest`). This should be running and the tracer endpoint reachable at port 6006 before running fastomop.
4. Copy `sample.env` to `.env` and provide a SQLAlchemy compatible connection string to your database.
5. Modify `config.toml` or preferably create a copy and name it to `config.local.toml`. This is already gitignored. Set the `CONFIG_FILE_PATH` variable in `.env` to `./config.local.toml`. This file is read by `src/fastomop/config.py` and any structural changes to this file that require changes to `config.py` must also be reflected in the default `config.toml`.
6. Run `uv run fastomop` or just `fastomop` to use the CLI. API and UI versions to be implemented.
