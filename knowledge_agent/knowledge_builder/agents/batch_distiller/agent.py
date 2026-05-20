from __future__ import annotations

from pathlib import Path

from knowledge_builder.agents.batch_distiller import tools


def create_agent(model: str = "gemini-2.0-flash"):
    """Create the Google ADK Batch Distiller Agent."""
    from google.adk.agents import Agent

    instruction = Path(__file__).with_name("prompt.md").read_text(encoding="utf-8")
    return Agent(
        model=model,
        name="alarm_batch_distiller",
        description="Distills one alarm-rule evidence batch into Markdown knowledge.",
        instruction=instruction,
        tools=[
            tools.load_evidence_batch,
            tools.save_knowledge_fragment,
            tools.check_knowledge_fragment,
        ],
    )

