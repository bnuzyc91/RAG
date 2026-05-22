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
        f"- {item.get('source_rule_id', '')}: `{item['rule']}` -> {item['severity']}"
        for item in evidence.get("examples", [])
    ) or "- No representative examples available."
    counterexamples = "\n".join(
        f"- {item.get('source_rule_id', '')}: `{item['rule']}` -> {item['severity']}"
        for item in evidence.get("counterexamples", [])
    ) or "- No counterexamples observed in this batch."
    exception_note = (
        "No exceptions were observed in the source batch."
        if not evidence.get("counterexamples")
        else "Counterexamples indicate this pattern should be applied with care."
    )
    structural_context = render_structural_context(evidence.get("structural_context", {}))
    contrastive_context = render_contrastive_context(evidence.get("contrastive_context", {}))

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

Rules matching this {evidence["pattern_type"]} pattern lean toward
{evidence.get("dominant_severity") or "Unknown"} severity in this batch, but the
full rule structure should be checked before using the suffix as prediction
logic.

### Structural Context

{structural_context}

### Severity Split Logic

{contrastive_context}

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


def render_structural_context(context: dict) -> str:
    if not context:
        return "No structural context was generated for this batch."

    lines: list[str] = []
    for title, key in (
        ("Common prefixes", "common_prefixes"),
        ("Common suffixes", "common_suffixes"),
        ("Common contiguous phrases", "common_contiguous_phrases"),
        ("Common tokens", "common_tokens"),
    ):
        items = context.get(key) or []
        if not items:
            continue
        lines.append(f"{title}:")
        for item in items:
            label = item.get("phrase") or item.get("token")
            lines.append(f"- `{label}`: {item.get('count')}")
        lines.append("")

    contrast = context.get("severity_contrast") or []
    if contrast:
        lines.append("Severity-specific contrast:")
        for item in contrast:
            tokens = ", ".join(
                f"{token['token']} ({token['count']})"
                for token in item.get("distinctive_tokens", [])[:5]
            ) or "none"
            phrases = ", ".join(
                f"{phrase['phrase']} ({phrase['count']})"
                for phrase in item.get("distinctive_phrases", [])[:5]
            ) or "none"
            lines.append(
                f"- {item.get('severity')} support={item.get('support')}; "
                f"tokens: {tokens}; phrases: {phrases}"
            )

    child_suffixes = context.get("child_suffix_distributions") or []
    if child_suffixes:
        lines.append("")
        lines.append("Child suffix distributions:")
        for item in child_suffixes:
            dist = ", ".join(
                f"{severity}={count}"
                for severity, count in item.get("severity_distribution", {}).items()
            )
            lines.append(
                f"- `{item.get('suffix')}` support={item.get('support')}; "
                f"dominant={item.get('dominant_severity')}; "
                f"purity={item.get('purity')}; {dist}"
            )

    neighbors = context.get("structural_neighbors") or []
    if neighbors:
        lines.append("")
        lines.append("Cross-batch structural neighbors:")
        for item in neighbors:
            lines.append(
                f"- `{item.get('rule')}` -> {item.get('severity')}; "
                f"score={item.get('score')}; shared=`{item.get('shared_phrase')}`; "
                f"prefix={item.get('prefix_match')}; suffix={item.get('suffix_match')}"
            )

    return "\n".join(lines).strip() or "No repeated structural signals were found."


def render_contrastive_context(context: dict) -> str:
    if not context:
        return "No contrastive severity signals were generated for this batch."

    lines: list[str] = []
    totals = context.get("severity_totals") or {}
    if totals:
        dist = ", ".join(f"{severity}={count}" for severity, count in totals.items())
        lines.append(f"Severity totals: {dist}")
        lines.append("")

    signals_by_severity = context.get("signals_by_severity") or {}
    for severity, signals in signals_by_severity.items():
        if not signals:
            continue
        lines.append(f"{severity} signals:")
        for signal in signals[:8]:
            distribution = ", ".join(
                f"{sev}={count}"
                for sev, count in signal.get("severity_distribution", {}).items()
            )
            lines.append(
                f"- `{signal.get('feature')}` ({signal.get('feature_type')}): "
                f"support={signal.get('support')}; purity={signal.get('purity')}; "
                f"lift={signal.get('lift')}; {distribution}"
            )
        lines.append("")

    pairwise = context.get("pairwise_contrasts") or []
    if pairwise:
        lines.append("Pairwise contrast summary:")
        for contrast in pairwise[:4]:
            left, right = contrast.get("severity_pair", ["", ""])
            left_features = ", ".join(
                item.get("feature", "") for item in contrast.get("left_signals", [])[:4]
            ) or "none"
            right_features = ", ".join(
                item.get("feature", "") for item in contrast.get("right_signals", [])[:4]
            ) or "none"
            lines.append(f"- {left} vs {right}: {left} -> {left_features}; {right} -> {right_features}")

    return "\n".join(lines).strip() or "No stable contrastive severity signals were found."


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
