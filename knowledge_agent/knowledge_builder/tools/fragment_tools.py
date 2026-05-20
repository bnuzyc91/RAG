from __future__ import annotations

import json
from pathlib import Path

from knowledge_builder.tools.validation_tools import normalize_markdown_fragment


CONFIDENCE_BY_PURITY = [
    (0.95, "High"),
    (0.80, "Medium"),
    (0.65, "Low"),
    (0.00, "Very Low"),
]


def confidence_label(purity: float) -> str:
    for threshold, label in CONFIDENCE_BY_PURITY:
        if purity >= threshold:
            return label
    return "Very Low"


def render_template_fragment(evidence: dict) -> str:
    """Deterministic fragment used for testing the pipeline without ADK."""
    confidence = confidence_label(float(evidence["purity"]))
    distribution = "\n".join(
        f"- {severity}: {count}"
        for severity, count in sorted(evidence["severity_distribution"].items())
    )
    examples = "\n".join(
        f"- `{item['rule']}` -> {item['severity']}"
        for item in evidence.get("examples", [])
    ) or "- No representative examples available."
    counterexamples = "\n".join(
        f"- `{item['rule']}` -> {item['severity']}"
        for item in evidence.get("counterexamples", [])
    ) or "- No counterexamples observed in this batch."
    exception_note = (
        "No exceptions were observed in the source batch."
        if not evidence.get("counterexamples")
        else "Counterexamples indicate this pattern should be applied with care."
    )

    return f"""---
batch_id: {evidence["batch_id"]}
pattern_type: {evidence["pattern_type"]}
pattern: {evidence["pattern"]}
default_severity: {evidence.get("dominant_severity") or ""}
support: {evidence["support"]}
purity: {evidence["purity"]}
entropy: {evidence["entropy"]}
confidence: {confidence}
---

## Pattern: {evidence["pattern"]}

### Observed Evidence

Type: {evidence["pattern_type"]}

Support: {evidence["support"]}

Severity distribution:
{distribution}

Dominant severity: {evidence.get("dominant_severity") or "Unknown"}

Purity: {evidence["purity"]}

Entropy: {evidence["entropy"]}

### Core Logic

Rules matching this {evidence["pattern_type"]} pattern usually map to
{evidence.get("dominant_severity") or "Unknown"} severity based on the observed
distribution. Treat this as evidence-backed guidance, not an absolute rule.

### Escalation Conditions

- Escalate or review manually when the new rule includes a higher-risk component,
  protection function, power delivery function, or direct equipment failure phrase
  that is not represented by the dominant examples.

### Exceptions

{exception_note}

{counterexamples}

### Representative Examples

{examples}
"""


def write_knowledge_fragment(fragment_path: str | Path, markdown: str) -> dict:
    path = Path(fragment_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = normalize_markdown_fragment(markdown)
    path.write_text(cleaned, encoding="utf-8")
    return {"path": str(path), "bytes": len(cleaned.encode("utf-8"))}


def read_knowledge_fragment(fragment_path: str | Path) -> str:
    return Path(fragment_path).read_text(encoding="utf-8")


def write_json(path: str | Path, payload: dict | list) -> dict:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"path": str(output)}
