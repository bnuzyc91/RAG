from __future__ import annotations

from pathlib import Path

from knowledge_builder.agents.instruction_loader import load_agent_instruction
from knowledge_builder.agents.critic import tools


def create_agent(model: str = "gemini-2.0-flash"):
    """Create the Google ADK Critic Agent."""
    from google.adk.agents import Agent

    instruction = load_agent_instruction(Path(__file__).parent)
    return Agent(
        model=model,
        name="alarm_knowledge_critic",
        description="Audits distilled alarm knowledge against source evidence.",
        instruction=instruction,
        tools=[
            tools.load_critic_inputs,
            tools.write_critique_report,
        ],
    )
