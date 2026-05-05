"""Benchmark orchestrator round-trip latency.

Sends ``N`` identical requests to a running orchestrator and reports the
wall-clock timing distribution (min, max, mean, p50, p95, p99). A ``--mode``
tag is included in the output so multiple runs (e.g., pre/post Neon Data API
migration, MCP vs API backends) can be compared in the same dataset.

Example::

    python scripts/benchmark.py --prompt "list all tables" --count 50 --mode api
    python scripts/benchmark.py --prompt "list all tables" --count 50 --mode mcp

The script creates one conversation per request to avoid conversation-history
effects on latency. If the server requires an API key, pass ``--api-key`` or
set ``ORCHESTRATOR_API_KEY``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from dataclasses import dataclass

import httpx


@dataclass
class Result:
    mode: str
    index: int
    wall_ms: float
    server_ms: float | None
    status: int
    error: str | None = None


async def _one_request(
    client: httpx.AsyncClient, base_url: str, prompt: str, mode: str, index: int
) -> Result:
    start = time.perf_counter()
    try:
        conv_resp = await client.post(f"{base_url}/conversations")
        conv_resp.raise_for_status()
        conv_id = conv_resp.json()["id"]

        msg_resp = await client.post(
            f"{base_url}/conversations/{conv_id}/messages",
            json={"content": prompt},
        )
        wall_ms = (time.perf_counter() - start) * 1000
        server_header = msg_resp.headers.get("X-Response-Time-Ms")
        server_ms = float(server_header) if server_header else None

        await client.delete(f"{base_url}/conversations/{conv_id}")

        msg_resp.raise_for_status()
        return Result(mode=mode, index=index, wall_ms=wall_ms, server_ms=server_ms,
                      status=msg_resp.status_code)
    except httpx.HTTPError as exc:
        wall_ms = (time.perf_counter() - start) * 1000
        return Result(mode=mode, index=index, wall_ms=wall_ms, server_ms=None,
                      status=0, error=str(exc))


def _percentile(data: list[float], pct: float) -> float:
    if not data:
        return 0.0
    ordered = sorted(data)
    k = max(0, min(len(ordered) - 1, int(round(pct / 100 * (len(ordered) - 1)))))
    return ordered[k]


def _summarise(results: list[Result]) -> dict:
    successful = [r for r in results if r.error is None]
    walls = [r.wall_ms for r in successful]
    servers = [r.server_ms for r in successful if r.server_ms is not None]
    summary = {
        "count": len(results),
        "success": len(successful),
        "failed": len(results) - len(successful),
        "wall_ms": {
            "min": min(walls) if walls else 0,
            "max": max(walls) if walls else 0,
            "mean": statistics.fmean(walls) if walls else 0,
            "p50": _percentile(walls, 50),
            "p95": _percentile(walls, 95),
            "p99": _percentile(walls, 99),
        },
    }
    if servers:
        summary["server_ms"] = {
            "min": min(servers),
            "max": max(servers),
            "mean": statistics.fmean(servers),
            "p50": _percentile(servers, 50),
            "p95": _percentile(servers, 95),
            "p99": _percentile(servers, 99),
        }
    return summary


async def run(args: argparse.Namespace) -> int:
    headers = {}
    api_key = args.api_key or os.environ.get("ORCHESTRATOR_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key

    limits = httpx.Limits(max_connections=args.concurrency)
    timeout = httpx.Timeout(args.timeout)
    async with httpx.AsyncClient(
        base_url="", headers=headers, limits=limits, timeout=timeout
    ) as client:
        sem = asyncio.Semaphore(args.concurrency)

        async def _bounded(index: int) -> Result:
            async with sem:
                return await _one_request(client, args.base_url, args.prompt, args.mode, index)

        tasks = [_bounded(i) for i in range(args.count)]
        results = await asyncio.gather(*tasks)

    summary = {"mode": args.mode, "prompt": args.prompt, **_summarise(results)}
    if args.json:
        print(json.dumps({"summary": summary, "results": [r.__dict__ for r in results]}, indent=2))
    else:
        print(f"Mode: {args.mode}  Count: {summary['count']}  Success: {summary['success']}  "
              f"Failed: {summary['failed']}")
        wall = summary["wall_ms"]
        print(f"Wall-clock ms — min={wall['min']:.1f} mean={wall['mean']:.1f} "
              f"p50={wall['p50']:.1f} p95={wall['p95']:.1f} p99={wall['p99']:.1f} "
              f"max={wall['max']:.1f}")
        if "server_ms" in summary:
            srv = summary["server_ms"]
            print(f"Server ms    — min={srv['min']:.1f} mean={srv['mean']:.1f} "
                  f"p50={srv['p50']:.1f} p95={srv['p95']:.1f} p99={srv['p99']:.1f} "
                  f"max={srv['max']:.1f}")
    return 0 if summary["failed"] == 0 else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark orchestrator request latency")
    parser.add_argument("--base-url", default="http://localhost:8000",
                        help="Orchestrator base URL (default: http://localhost:8000)")
    parser.add_argument("--prompt", default="list all tables",
                        help="Prompt to send on each request")
    parser.add_argument("--count", type=int, default=20, help="Number of requests to send")
    parser.add_argument("--concurrency", type=int, default=1,
                        help="Max concurrent in-flight requests")
    parser.add_argument("--mode", default="api", help="Label for this run (e.g., api, mcp)")
    parser.add_argument("--timeout", type=float, default=60.0, help="Per-request timeout seconds")
    parser.add_argument("--api-key", default=None,
                        help="x-api-key header value (or set ORCHESTRATOR_API_KEY)")
    parser.add_argument("--json", action="store_true", help="Emit full JSON report")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(_parse_args())))
