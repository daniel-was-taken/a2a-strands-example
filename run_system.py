#!/usr/bin/env python3
"""A2A Orchestrator -- System Runner.

Reads agents.yaml and starts all declared agents plus the orchestrator
as separate processes.

Usage:
    python run_system.py                          # A2A mode (default)
    DATABASE_MODE=direct python run_system.py     # Direct mode -- orchestrator only
"""

import os
import signal
import subprocess
import sys
import time
import urllib.request

from dotenv import load_dotenv

load_dotenv()


def _load_agents_config() -> list[dict]:
    """Load agent definitions from the YAML config."""
    from agents.mcp_agent import load_agents_config

    config_path = os.environ.get("AGENTS_CONFIG", "agents.yaml")
    return load_agents_config(config_path)


def _check_health(port: int, timeout: float = 1.0) -> bool:
    """Return True if the agent-card endpoint responds on the given port."""
    url = f"http://127.0.0.1:{port}/.well-known/agent-card.json"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except Exception:
        return False


def _wait_for_agents(
    processes: list[subprocess.Popen],
    ports: list[int],
    names: list[str],
    timeout: float = 30.0,
) -> bool:
    """Wait until all agents respond to health checks or a process dies."""
    deadline = time.monotonic() + timeout
    ready = [False] * len(ports)

    while time.monotonic() < deadline:
        for i, proc in enumerate(processes):
            if proc.poll() is not None and not ready[i]:
                print(
                    f"\n  ERROR: {names[i]} exited with code {proc.returncode}.",
                    file=sys.stderr,
                )
                print(
                    "  Check the output above for the error.",
                    file=sys.stderr,
                )
                return False

        for i, port in enumerate(ports):
            if not ready[i]:
                ready[i] = _check_health(port)

        if all(ready):
            return True

        time.sleep(0.5)

    for i, r in enumerate(ready):
        if not r:
            print(f"  TIMEOUT: {names[i]} did not respond on port {ports[i]}.", file=sys.stderr)
    return False


def main():
    mode = os.environ.get("DATABASE_MODE", "a2a")
    python = sys.executable
    config_path = os.environ.get("AGENTS_CONFIG", "agents.yaml")

    print("\n=== A2A Orchestrator ===\n")

    if mode == "direct":
        print("Starting system (direct mode -- single process)...")
        print("  Orchestrator -> http://localhost:8000\n")
        os.execvp(python, [python, "-m", "agents.orchestrator_agent"])
        return

    agents_config = _load_agents_config()

    print("Starting system (A2A mode)...")
    for cfg in agents_config:
        print(f"  {cfg['name']:20s} -> http://localhost:{cfg['port']}")
    print(f"  {'Orchestrator':20s} -> http://localhost:8000")
    print()

    # Start agent processes
    agent_procs: list[subprocess.Popen] = []
    agent_names: list[str] = []
    agent_ports: list[int] = []

    for cfg in agents_config:
        if cfg["type"] == "mcp":
            cmd = [
                python,
                "-m",
                "agents.mcp_agent",
                "--config",
                config_path,
                "--agent",
                cfg["name"],
            ]
        elif cfg["type"] == "custom":
            cmd = [python, "-m", cfg["module"]]
        else:
            print(
                f"  WARNING: Unknown agent type '{cfg['type']}' for {cfg['name']}, skipping.",
                file=sys.stderr,
            )
            continue

        agent_procs.append(subprocess.Popen(cmd))
        agent_names.append(cfg["name"])
        agent_ports.append(cfg["port"])

    print("Waiting for agents to start...")
    if not _wait_for_agents(agent_procs, agent_ports, agent_names):
        print(
            "\nAgent startup failed. Shutting down.",
            file=sys.stderr,
        )
        for p in agent_procs:
            p.terminate()
        for p in agent_procs:
            p.wait(timeout=5)
        sys.exit(1)

    print("Agents healthy. Starting orchestrator...\n")

    orch = subprocess.Popen([python, "-m", "agents.orchestrator_agent"])
    all_procs = agent_procs + [orch]

    print("All components started. Send requests to http://localhost:8000/query")
    print("Press Ctrl+C to stop.\n")

    def _shutdown(signum, _frame):
        print("\nShutting down...")
        for p in all_procs:
            p.terminate()
        for p in all_procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        print("Stopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    while True:
        for i, p in enumerate(all_procs):
            ret = p.poll()
            if ret is not None:
                name = "orchestrator" if p is orch else agent_names[i]
                print(f"\n{name} exited (code {ret}). Shutting down.", file=sys.stderr)
                _shutdown(signal.SIGTERM, None)
        time.sleep(1)


if __name__ == "__main__":
    main()
