from __future__ import annotations

from pathlib import Path

from knowledge_builder.agents.instruction_loader import load_agent_instruction
from knowledge_builder.agents.curator import tools


def create_agent(model: str = "gemini-2.0-flash"):
    """Create the Google ADK Curator Agent."""
    from google.adk.agents import Agent

    instruction = load_agent_instruction(Path(__file__).parent)
    return Agent(
        model=model,
        name="alarm_knowledge_curator",
        description="Suggests organization for validated alarm knowledge fragments.",
        instruction=instruction,
        tools=[
            tools.load_validated_fragments,
            tools.write_curator_plan,
        ],
    )
