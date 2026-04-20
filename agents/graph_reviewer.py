"""Graph Reviewer -- exposed as an A2A server on port 8002.

This agent uses a graph-based workflow with analyze -> implement -> review
stages and conditional routing for revisions.
"""

import logging

from a2a.types import AgentSkill
from strands import Agent
from strands.multiagent import GraphBuilder
from strands.multiagent.graph import Graph

from core.model import create_toolless_model

logger = logging.getLogger(__name__)

_SKILLS = [
    AgentSkill(
        id="multi-step-reasoning",
        name="Multi-Step Reasoning",
        description=(
            "Analyze, implement, and review solutions through a structured "
            "graph workflow with automatic revision cycles"
        ),
        tags=["reasoning", "analysis", "implementation", "review"],
    ),
]


def create_agent() -> Graph:
    """Build a graph-based agent with analyze -> implement -> review workflow."""
    model = create_toolless_model()

    analyzer = Agent(
        model=model,
        name="analyzer",
        system_prompt="Analyze the input. Break down the problem and identify key requirements.",
        tools=[],
        load_tools_from_directory=False,
        callback_handler=None,
    )
    implementer = Agent(
        model=model,
        name="implementer",
        system_prompt="Implement the solution based on the analysis provided.",
        tools=[],
        load_tools_from_directory=False,
        callback_handler=None,
    )
    reviewer = Agent(
        model=model,
        name="reviewer",
        system_prompt=(
            "Review the implementation. If it needs revision, say 'needs revision' and explain why."
        ),
        tools=[],
        load_tools_from_directory=False,
        callback_handler=None,
    )

    builder = GraphBuilder()
    builder.add_node(analyzer, "analyze")
    builder.add_node(implementer, "implement")
    builder.add_node(reviewer, "review")
    builder.add_edge("analyze", "implement")
    builder.add_edge("implement", "review")
    builder.add_edge(
        "review",
        "implement",
        condition=lambda state: "needs revision" in str(state.results.get("review", "")).lower(),
    )
    builder.set_entry_point("analyze")
    builder.set_max_node_executions(5)
    graph = builder.build()
    # A2AServer reads .name and .description from the agent object.
    # Graph doesn't define these, so we attach them here.
    graph.name = "Graph Reviewer"  # type: ignore[attr-defined]
    graph.description = (  # type: ignore[attr-defined]
        "Handles multi-step reasoning workflows with analyze, implement, and review stages"
    )
    return graph


def serve() -> None:
    """Start the Graph Reviewer as an A2A server."""
    from core.server import serve_agent

    agent = create_agent()
    serve_agent(
        agent,
        name="Graph Reviewer",
        port=8002,
        skills=_SKILLS,
    )


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    serve()
