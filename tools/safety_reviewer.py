"""Safety reviewer agent for evaluating destructive database queries."""

import logging

from strands import Agent, tool

from agents.model import create_model

logger = logging.getLogger(__name__)

SAFETY_REVIEWER_SYSTEM_PROMPT = """
You are SafetyReviewer, responsible for reviewing destructive database requests.

Approve only clearly scoped requests that target specific rows.
Reject requests that are broad, ambiguous, or likely to affect many rows.

Output exactly one of:
- APPROVE: <short reason>
- REJECT: <short reason>
"""


@tool
def _dummy_tool() -> str:
    """A placeholder tool to satisfy minimum tool requirements."""
    return "ok"


def create_safety_reviewer() -> Agent:
    """Create a safety reviewer agent."""
    return Agent(
        model=create_model(),
        system_prompt=SAFETY_REVIEWER_SYSTEM_PROMPT,
        tools=[_dummy_tool],
    )


def review_delete_request(reviewer: Agent, query: str) -> tuple[bool, str]:
    """Ask the safety reviewer agent to evaluate a destructive query.

    Returns:
        (is_approved, verdict) -- True when the reviewer outputs APPROVE:.
    """
    response = str(
        reviewer(
            f"""Review this delete request for safety:

{query}

Remember to output exactly one line:
APPROVE: <short reason>
or
REJECT: <short reason>"""
        )
    ).strip()

    upper_response = response.upper()
    if upper_response.startswith("APPROVE:"):
        return True, response

    if upper_response.startswith("REJECT:"):
        return False, response

    return False, f"REJECT: Could not determine safety. Raw reviewer output: {response}"
