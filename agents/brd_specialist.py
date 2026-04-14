"""BRD Specialist — dedicated BRD drafting agent exposed as an A2A server."""

from a2a.types import AgentSkill
from strands import Agent

from core.model import create_toolless_model

_SKILLS = [
    AgentSkill(
        id="brd-generation",
        name="BRD Generation",
        description="Creates business requirements documents from structured evidence summaries",
        tags=["brd", "requirements", "documentation"],
    ),
]


def create_agent() -> Agent:
    """Build a BRD specialist agent for mixed-audience requirements documents."""
    return Agent(
        model=create_toolless_model(),
        name="BRD Specialist",
        description="Drafts business requirements documents from confirmed evidence summaries",
        system_prompt=(
            "You create clear business requirements documents for a mixed audience.\n"
            "Always include these sections with the exact headings:\n"
            "1. Problem Statement\n"
            "2. Scope and Exclusions\n"
            "3. Functional Requirements\n"
            "4. Assumptions and Constraints\n"
            "5. Risks and Open Questions\n\n"
            "Separate facts from assumptions, avoid unsupported claims, cite the provided evidence "
            "summary, and explicitly highlight missing data. If the evidence is too weak, end with "
            "clear follow-up questions."
        ),
        tools=[],
        load_tools_from_directory=False,
        callback_handler=None,
    )


def serve() -> None:
    """Start the BRD Specialist as an A2A server."""
    from core.server import serve_agent

    serve_agent(
        create_agent(),
        name="BRD Specialist",
        port=8004,
        skills=_SKILLS,
    )


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    serve()