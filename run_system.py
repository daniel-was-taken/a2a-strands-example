#!/usr/bin/env python3
"""A2A Database Orchestrator -- System Runner.

Starts both the Database Agent (A2A server) and the Orchestrator Agent
(FastAPI) in parallel using multiprocessing.

Usage:
    python run_system.py           # A2A mode (default) — starts both services
    DATABASE_MODE=direct python run_system.py  # Direct mode — orchestrator only
"""

import multiprocessing
import os
import time

from dotenv import load_dotenv

load_dotenv()


def start_db_agent():
    """Launch the Database Agent A2A server."""
    from agents.db_agent import serve

    serve()


def start_graph_agent():
    """Launch the Graph Agent A2A server."""
    from agents.example_agent import serve

    serve()


def start_orchestrator():
    """Launch the Orchestrator Agent FastAPI server."""
    from agents.orchestrator_agent import serve

    serve()


def main():
    mode = os.environ.get("DATABASE_MODE", "a2a")

    print("\n=== A2A Database Orchestrator ===\n")

    if mode == "direct":
        print("Starting system (direct mode — single process)...")
        print("  - Orchestrator -> http://localhost:8000")
        print()
        start_orchestrator()
        return

    print("Starting system (A2A mode)...")
    print("  - Database Agent    (A2A Server) -> http://localhost:8001")
    print("  - Graph Agent       (A2A Server) -> http://localhost:8002")
    print("  - Orchestrator Agent (FastAPI)   -> http://localhost:8000")
    print()

    db_process = multiprocessing.Process(target=start_db_agent, name="db-agent")
    graph_process = multiprocessing.Process(target=start_graph_agent, name="graph-agent")
    orch_process = multiprocessing.Process(target=start_orchestrator, name="orchestrator")

    db_process.start()
    graph_process.start()
    time.sleep(2)  # Let the A2A agents start before the Orchestrator
    orch_process.start()

    print("\nAll components started. Send requests to http://localhost:8000/query")
    print("Press Ctrl+C to stop.\n")

    try:
        db_process.join()
        graph_process.join()
        orch_process.join()
    except KeyboardInterrupt:
        print("\nShutting down...")
        db_process.terminate()
        graph_process.terminate()
        orch_process.terminate()
        db_process.join(timeout=5)
        graph_process.join(timeout=5)
        orch_process.join(timeout=5)
        print("Stopped.")


if __name__ == "__main__":
    main()
