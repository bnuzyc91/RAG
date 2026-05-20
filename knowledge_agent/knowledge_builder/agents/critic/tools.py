from __future__ import annotations

from pathlib import Path

from knowledge_builder.tools.evidence_tools import read_evidence_batch
from knowledge_builder.tools.fragment_tools import read_knowledge_fragment
from knowledge_builder.tools.validation_tools import validate_fragment


def load_critic_inputs(batch_path: str, fragment_path: str) -> dict:
    """Load evidence, fragment, and deterministic validation findings."""
    evidence = read_evidence_batch(batch_path)
    markdown = read_knowledge_fragment(fragment_path)
    validation = validate_fragment(markdown, evidence)
    return {
        "evidence": evidence,
        "fragment": markdown,
        "validation": {
            "ok": validation.ok,
            "blocking": validation.blocking,
            "warnings": validation.warnings,
            "metadata": validation.metadata,
        },
    }


def write_critique_report(report_path: str, report: str) -> dict:
    """Write a critic report."""
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")
    return {"path": str(path), "bytes": len(report.encode("utf-8"))}

