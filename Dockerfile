# FastOMOP Dockerfile

FROM python:3.13-slim AS builder

# Install system dependencies for building Python packages
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install UV package manager
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Install OMCP dependencies (postgres + duckdb for Ibis backends)
RUN pip install --no-cache-dir\
    "ibis-framework[postgres]>=10.5.0" \
    "ibis-framework[duckdb]>=10.5.0" \
    "langfuse>=3.5.2" \
    "mcp[cli]>=1.6.0" \
    "psycopg>=3.2.6"

#

# Set working directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml uv.lock* ./

# Install dependencies using UV with increased timeout
ENV UV_HTTP_TIMEOUT=300
RUN uv sync --frozen --no-dev

# Stage 2: Build Agent UI
FROM node:20-slim AS ui-builder

# Install pnpm and git
RUN npm install -g pnpm
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Clone the agent-ui repository
WORKDIR /tmp
RUN git clone https://github.com/agno-agi/agent-ui.git

# Move to the cloned directory and install/build
WORKDIR /tmp/agent-ui

# Set the backend URL for the UI at build time
ENV NEXT_PUBLIC_AGENTOS_URL=/api

RUN pnpm install
RUN pnpm build

# Verify build was successful
RUN ls -la /tmp/agent-ui/.next

# Final stage - minimal runtime image
FROM python:3.13-slim

# Install runtime dependencies (including Node.js for Agent UI)
RUN apt-get update && apt-get install -y \
    curl \
    nginx \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g pnpm \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 fastomop && \
    mkdir -p /app /app/data && \
    chown -R fastomop:fastomop /app

# Create nginx directories with proper permissions
RUN mkdir -p /var/lib/nginx/body /var/lib/nginx/proxy /var/lib/nginx/fastcgi /var/lib/nginx/uwsgi /var/lib/nginx/scgi && \
    mkdir -p /var/log/nginx /var/cache/nginx && \
    chown -R fastomop:fastomop /var/lib/nginx /var/log/nginx /var/cache/nginx && \
    chmod -R 755 /var/lib/nginx /var/log/nginx /var/cache/nginx

# Install uv and make it available to all users
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    cp /root/.local/bin/uv /usr/local/bin/uv && \
    chmod 755 /usr/local/bin/uv
ENV PATH="/usr/local/bin:$PATH"

# Set working directory
WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY --chown=fastomop:fastomop . .

# Copy built Agent UI from ui-builder stage (with .next directory)
COPY --from=ui-builder --chown=fastomop:fastomop /tmp/agent-ui /ui

# Copy nginx config
COPY nginx.conf /etc/nginx/nginx.conf

# Add virtual environment to PATH
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src:$PYTHONPATH"

# Expose web interface port
EXPOSE 7777

# Create startup script to run nginx, backend, and UI
USER root
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Health check (check UI port since that's what's exposed)
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:7777 || exit 1

# Default command - run both services
CMD ["/bin/bash", "/app/start.sh"]
