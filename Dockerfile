FROM python:3.13-slim

WORKDIR /app

# Install dependencies
COPY requirements-prod.txt .
RUN pip install --no-cache-dir -r requirements-prod.txt

# Copy application code
COPY schemas.py store.py run_system.py log_stream.py ./
COPY agents/ agents/
COPY tools/ tools/
COPY mcp_client/ mcp_client/
COPY db/ db/
COPY frontend/ frontend/

EXPOSE 8000

# Default: run orchestrator (pair with db-agent via docker-compose)
CMD ["python", "-m", "agents.orchestrator_agent"]
