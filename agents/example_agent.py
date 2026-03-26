"""Graph Agent -- exposed as an A2A server on port 8002.

This agent uses a graph-based workflow with analyze -> implement -> review
stages and conditional routing for revisions.
"""

import logging
import os

from google import genai
from strands import Agent
from strands.multiagent import GraphBuilder
from strands.multiagent.a2a import A2AServer
from strands.models.gemini import GeminiModel
from strands.types.tools import ToolSpec

from agents.model import create_model

logger = logging.getLogger(__name__)

GRAPH_AGENT_PORT = int(os.environ.get("GRAPH_AGENT_PORT", "8002"))


class NoToolsGeminiModel(GeminiModel):
    """GeminiModel that omits the tools field when there are no tool specs.

    Works around a Gemini API bug where an empty Tool(function_declarations=[])
    causes a 400 error.
    """

    def _format_request_tools(self, tool_specs: list[ToolSpec] | None) -> list[genai.types.Tool]:
        if not tool_specs and not self.config.get("gemini_tools"):
            return []
        return super()._format_request_tools(tool_specs)


def _create_no_tools_model() -> NoToolsGeminiModel:
    """Create a Gemini model that won't send empty tool definitions."""
    base = create_model()
    return NoToolsGeminiModel(
        client_args=base.client_args,
        model_id=base.config["model_id"],
    )


def create_graph_agent():
    """Build a graph-based agent with analyze -> implement -> review workflow."""
    model = _create_no_tools_model()

    analyzer = Agent(
        model=model,
        name="analyzer",
        system_prompt="Analyze the input. Break down the problem and identify key requirements.",
        tools=[],
        load_tools_from_directory=False,
    )
    implementer = Agent(
        model=model,
        name="implementer",
        system_prompt="Implement the solution based on the analysis provided.",
        tools=[],
        load_tools_from_directory=False,
    )
    reviewer = Agent(
        model=model,
        name="reviewer",
        system_prompt="Review the implementation. If it needs revision, say 'needs revision' and explain why.",
        tools=[],
        load_tools_from_directory=False,
    )

    builder = GraphBuilder()
    builder.add_node(analyzer, "analyze")
    builder.add_node(implementer, "implement")
    builder.add_node(reviewer, "review")
    builder.add_edge("analyze", "implement")
    builder.add_edge("implement", "review")
    # Conditional routing: loop back if reviewer flags revision needed
    builder.add_edge(
        "review",
        "implement",
        condition=lambda state: "needs revision" in str(state.results.get("review", "")).lower(),
    )
    builder.set_entry_point("analyze")
    builder.set_max_node_executions(5)
    graph = builder.build()
    graph.name = "Graph Agent"
    graph.description = "Handles multi-step reasoning workflows with analyze, implement, and review stages"
    return graph


def serve():
    """Start the Graph Agent as an A2A server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info("Starting Graph Agent A2A server on port %d", GRAPH_AGENT_PORT)

    agent = create_graph_agent()
    a2a_server = A2AServer(agent=agent, skills=[], enable_a2a_compliant_streaming=True)
    a2a_server.serve(host="0.0.0.0", port=GRAPH_AGENT_PORT)


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    serve()