FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY core/ core/
COPY agents/ agents/

# No default CMD -- specify per agent in docker-compose.yml.
