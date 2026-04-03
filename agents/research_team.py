"""Research Team — autonomous swarm agent exposed as an A2A server.

A self-organizing team of researcher, writer, and editor agents that
collaborate via handoffs. The swarm decides autonomously which agent
should handle each part of the task.

Registered in agents.yaml as type: custom.
"""

import logging

from a2a.types import AgentSkill
from strands import Agent
from strands.multiagent import Swarm

from core.model import create_model

logger = logging.getLogger(__name__)

_SKILLS = [
    AgentSkill(
        id="collaborative-research",
        name="Collaborative Research",
        description="Multi-agent research, writing, and editing with autonomous handoffs",
        tags=["research", "writing", "collaboration"],
    ),
]


def create_agent() -> Swarm:
    """Build a swarm with researcher, writer, and editor agents."""
    model = create_model()

    researcher = Agent(
        model=model,
        name="researcher",
        system_prompt=(
            "You are a research specialist. Gather information, facts, and analysis.\n"
            "When you have enough material, hand off to the 'writer' agent."
        ),
        description="Researches topics and gathers information",
        callback_handler=None,
    )
    writer = Agent(
        model=model,
        name="writer",
        system_prompt=(
            "You are a technical writer. Create clear, well-structured content "
            "from the research provided.\n"
            "When the draft is ready, hand off to the 'editor' agent.\n"
            "If you need more research, hand off to the 'researcher' agent."
        ),
        description="Writes clear content from research",
        callback_handler=None,
    )
    editor = Agent(
        model=model,
        name="editor",
        system_prompt=(
            "You are an editor. Polish the content for clarity, accuracy, and style.\n"
            "If there are major issues, hand back to the 'writer' agent.\n"
            "If the content is good, produce the final version and stop."
        ),
        description="Edits and polishes written content",
        callback_handler=None,
    )

    swarm = Swarm(
        [researcher, writer, editor],
        entry_point=researcher,
        max_handoffs=10,
        max_iterations=15,
        execution_timeout=300.0,
    )
    swarm.name = "Research Team"  # type: ignore[attr-defined]
    swarm.description = (  # type: ignore[attr-defined]
        "Collaborative research team with autonomous handoffs between agents"
    )
    return swarm


def serve() -> None:
    """Start the Research Team as an A2A server."""
    from core.server import serve_agent

    agent = create_agent()
    serve_agent(
        agent,
        name="Research Team",
        port=8003,
        skills=_SKILLS,
    )


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    serve()
