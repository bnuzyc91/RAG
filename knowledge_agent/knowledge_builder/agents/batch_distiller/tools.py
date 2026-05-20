from __future__ import annotations

from knowledge_builder.tools.evidence_tools import read_evidence_batch
from knowledge_builder.tools.fragment_tools import read_knowledge_fragment, write_knowledge_fragment
from knowledge_builder.tools.validation_tools import validate_fragment


def load_evidence_batch(batch_path: str) -> dict:
    """Load one evidence batch JSON file."""
    return read_evidence_batch(batch_path)


def save_knowledge_fragment(fragment_path: str, markdown: str) -> dict:
    """Write one generated Markdown knowledge fragment."""
    return write_knowledge_fragment(fragment_path, markdown)


def check_knowledge_fragment(fragment_path: str, batch_path: str) -> dict:
    """Validate one fragment against its evidence batch."""
    markdown = read_knowledge_fragment(fragment_path)
    evidence = read_evidence_batch(batch_path)
    result = validate_fragment(markdown, evidence)
    return {
        "ok": result.ok,
        "blocking": result.blocking,
        "warnings": result.warnings,
        "metadata": result.metadata,
    }

