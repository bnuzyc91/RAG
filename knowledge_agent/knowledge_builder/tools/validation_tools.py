from __future__ import annotations

import re
from dataclasses import dataclass


ABSOLUTE_TERMS = ("always", "never", "guaranteed", "must be", "certainly")
REQUIRED_FRONTMATTER = (
    "batch_id",
    "pattern_type",
    "pattern",
    "default_severity",
    "support",
    "purity",
    "entropy",
    "confidence",
)


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    blocking: list[str]
    warnings: list[str]
    metadata: dict[str, str]


def parse_frontmatter(markdown: str) -> dict[str, str]:
    markdown = normalize_markdown_fragment(markdown)
    if not markdown.startswith("---"):
        return {}
    match = re.match(r"^---\n(.*?)\n---", markdown, flags=re.DOTALL)
    if not match:
        return {}
    metadata: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()
    return metadata


def normalize_markdown_fragment(markdown: str) -> str:
    """Normalize common LLM output wrappers before validation.

    ADK/LLM responses sometimes wrap Markdown in code fences or include leading
    whitespace. The knowledge fragment still needs to start with YAML
    frontmatter after normalization.
    """
    text = markdown.strip().lstrip("\ufeff")
    fence_match = re.match(r"^```(?:markdown|md)?\s*\n(.*?)\n```$", text, flags=re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    frontmatter_match = re.search(r"---\n.*?\n---", text, flags=re.DOTALL)
    if frontmatter_match and frontmatter_match.start() > 0:
        text = text[frontmatter_match.start():].strip()
    return text


def validate_fragment(markdown: str, evidence: dict | None = None) -> ValidationResult:
    blocking: list[str] = []
    warnings: list[str] = []
    metadata = parse_frontmatter(markdown)

    for key in REQUIRED_FRONTMATTER:
        if not metadata.get(key):
            blocking.append(f"missing required frontmatter field: {key}")

    if evidence:
        _check_evidence_match(metadata, evidence, blocking)

    purity = _float_value(metadata.get("purity"))
    lowered = markdown.lower()
    absolute_hits = [term for term in ABSOLUTE_TERMS if term in lowered]
    if absolute_hits and purity < 1.0:
        blocking.append(
            "absolute language is not allowed unless purity is 1.0: "
            + ", ".join(absolute_hits)
        )

    if evidence and evidence.get("counterexamples") and "### Exceptions" not in markdown:
        blocking.append("mixed batch is missing an Exceptions section")

    if evidence and float(evidence.get("purity", 0.0)) < 0.8:
        warnings.append("low-purity batch should be reviewed by critic")

    if evidence and _has_high_severity_counterexample(evidence):
        warnings.append("minority High/Critical exception should be reviewed by critic")

    return ValidationResult(
        ok=not blocking,
        blocking=blocking,
        warnings=warnings,
        metadata=metadata,
    )


def needs_critic(result: ValidationResult, evidence: dict) -> bool:
    if result.blocking:
        return True
    if result.warnings:
        return True
    if int(evidence.get("support", 0)) >= 50 and float(evidence.get("purity", 0.0)) < 0.9:
        return True
    return False


def _check_evidence_match(metadata: dict[str, str], evidence: dict, blocking: list[str]) -> None:
    expected = {
        "batch_id": str(evidence["batch_id"]),
        "pattern_type": str(evidence["pattern_type"]),
        "pattern": str(evidence["pattern"]),
        "default_severity": str(evidence.get("dominant_severity") or ""),
        "support": str(evidence["support"]),
        "purity": str(evidence["purity"]),
        "entropy": str(evidence["entropy"]),
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            blocking.append(
                f"frontmatter field {key!r} does not match evidence "
                f"(expected {value!r}, got {metadata.get(key)!r})"
            )


def _float_value(value: str | None) -> float:
    try:
        return float(value or "0")
    except ValueError:
        return 0.0


def _has_high_severity_counterexample(evidence: dict) -> bool:
    for item in evidence.get("counterexamples", []):
        if item.get("severity", "").lower() in {"high", "critical"}:
            return True
    return False
