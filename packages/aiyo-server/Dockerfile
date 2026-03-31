FROM python:3.12-slim

# Install system dependencies (ripgrep for grep_files tool)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ripgrep \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy workspace config and lock file
COPY pyproject.toml uv.lock ./

# Copy libs and packages source
COPY libs/ libs/
COPY packages/aiyo-server/ packages/aiyo-server/

# Install only aiyo-server and its dependencies (no dev extras)
RUN uv sync --package aiyo-server --no-dev --frozen

# Default port
EXPOSE 8080

# Use the venv's python
ENV PATH="/app/.venv/bin:$PATH"

CMD ["aiyo-server"]
