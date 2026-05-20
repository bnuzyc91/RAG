from __future__ import annotations

from pathlib import Path


def load_agent_instruction(agent_dir: str | Path) -> str:
    """Build an ADK instruction from skill, shared guardrails, and prompt files."""
    base = Path(agent_dir)
    package_root = base.parents[1]
    shared_guardrails = package_root / "prompts" / "shared_guardrails.md"

    sections = [
        ("Agent Skill", base / "skill.md"),
        ("Shared Guardrails", shared_guardrails),
        ("Task Prompt", base / "prompt.md"),
    ]
    parts = []
    for title, path in sections:
        if path.exists():
            parts.append(f"# {title}\n\n{path.read_text(encoding='utf-8').strip()}")
    return "\n\n".join(parts)
