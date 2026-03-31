FROM python:3.13-slim

WORKDIR /app

# Install dependencies (cached layer).
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy application code.
COPY agents/ agents/
COPY common/ common/
COPY tools/ tools/
COPY mcp_client/ mcp_client/
COPY db/ db/
COPY frontend/ frontend/

EXPOSE 8000

# Default: run orchestrator (pair with db-agent via docker-compose).
CMD ["python", "-m", "agents.orchestrator_agent"]
