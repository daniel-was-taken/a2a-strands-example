"""Pipeline agent — a Graph that orchestrates remote A2A agents as nodes.

Demonstrates composing other people's A2A agents into your own workflow.
Requires the database agent and graph reviewer to be running:

    python run_system.py   # starts all agents
    python examples/pipeline_agent.py  # in another terminal

Usage:
    python examples/pipeline_agent.py
"""

from dotenv import load_dotenv
from strands import Agent
from strands.agent.a2a_agent import A2AAgent
from strands.multiagent import GraphBuilder

from core.model import create_model
from core.server import serve_agent

load_dotenv()

# Remote agents (other A2A servers — could be anyone's)
db_agent = A2AAgent(endpoint="http://localhost:8001", name="database")
reviewer = A2AAgent(endpoint="http://localhost:8002", name="graph_reviewer")

# Local agent for summarization
summarizer = Agent(
    model=create_model(),
    name="summarizer",
    system_prompt="Summarize the results from previous agents clearly and concisely.",
    callback_handler=None,
)

# Wire them into a graph
builder = GraphBuilder()
builder.add_node(db_agent, "fetch_data")
builder.add_node(reviewer, "review")
builder.add_node(summarizer, "summarize")
builder.add_edge("fetch_data", "review")
builder.add_edge("review", "summarize")
builder.set_entry_point("fetch_data")

graph = builder.build()
graph.name = "Pipeline Agent"  # type: ignore[attr-defined]
graph.description = "Fetches data, reviews, and summarizes"  # type: ignore[attr-defined]

serve_agent(graph, name="pipeline-agent", port=8010)
