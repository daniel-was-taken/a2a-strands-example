FROM python:3.13-slim

WORKDIR /app

# Install dependencies (cached layer).
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy application code.
COPY core/ core/
COPY agents/ agents/
COPY db/ db/
COPY frontend/ frontend/

EXPOSE 8000

# Default: run orchestrator (pair with agents via docker-compose).
CMD ["python", "-m", "core.orchestrator"]
