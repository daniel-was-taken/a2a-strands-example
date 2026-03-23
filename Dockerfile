FROM python:3.13-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY schemas.py store.py run_system.py ./
COPY agents/ agents/
COPY tools/ tools/
COPY mcp_client/ mcp_client/
COPY frontend/ frontend/

EXPOSE 8000 8001

CMD ["python", "run_system.py"]
