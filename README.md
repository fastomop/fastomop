# FastOMOP


**Detailed documentation to follow**


## Get started

1. Clone the repo
2. Run `uv sync` (for default setup with DuckDb support) or `uv sync --extra mcp-postgres` depending on where your OMOP data is.
3. Copy `sample.env` to `.env` and provide a SQLAlchemy compatible connection string to your database.
4. Setup tracing with Langfuse (See https://langfuse.com/self-hosting/docker-compose#get-started for local deployment using docker compose). Follow the docs to create public and secret keys and update the `.env` file using `sample.env` as a template.
5. Modify `config.toml` or preferably create a copy and name it to `config.local.toml`. This is already gitignored. Set the `CONFIG_FILE_PATH` variable in `.env` to `./config.local.toml`. This file is read by `src/fastomop/config.py` and any structural changes to this file that require changes to `config.py` must also be reflected in the default `config.toml`.
6. Activate the virtual environment and run `uv run fastomop` or just `fastomop` to use the CLI. API and UI versions to be implemented.
