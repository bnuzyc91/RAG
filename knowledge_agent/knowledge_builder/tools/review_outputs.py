from __future__ import annotations

import csv
import re
from pathlib import Path

from knowledge_builder.tools.evidence_tools import AlarmRule, read_evidence_batch


SME_REVIEW_FIELDS = [
    "ai_rule_id",
    "batch_id",
    "pattern_type",
    "pattern",
    "default_severity",
    "confidence",
    "support",
    "purity",
    "entropy",
    "core_logic",
    "severity_split_logic",
    "escalation_conditions",
    "exception_logic",
    "evidence_role",
    "source_rule_id",
    "source_rule",
    "source_severity",
    "source_relation",
    "structural_similarity_score",
    "shared_phrase",
    "sme_review_status",
    "sme_corrected_default_severity",
    "sme_comment",
]


def write_sme_review_evidence(
    fragments: list[dict],
    evidence_dir: str | Path,
    output_path: str | Path,
) -> Path:
    evidence_root = Path(evidence_dir)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SME_REVIEW_FIELDS)
        writer.writeheader()

        for fragment in fragments:
            metadata = fragment["metadata"]
            evidence_path = evidence_root / f"{metadata['batch_id']}.json"
            evidence = read_evidence_batch(evidence_path)
            sections = extract_review_sections(fragment["markdown"])
            base = {
                "ai_rule_id": metadata.get("ai_rule_id", ""),
                "batch_id": metadata.get("batch_id", ""),
                "pattern_type": metadata.get("pattern_type", ""),
                "pattern": metadata.get("pattern", ""),
                "default_severity": metadata.get("default_severity", ""),
                "confidence": metadata.get("confidence", ""),
                "support": metadata.get("support", ""),
                "purity": metadata.get("purity", ""),
                "entropy": metadata.get("entropy", ""),
                "core_logic": sections["core_logic"],
                "severity_split_logic": sections["severity_split_logic"],
                "escalation_conditions": sections["escalation_conditions"],
                "exception_logic": sections["exception_logic"],
                "sme_review_status": "",
                "sme_corrected_default_severity": "",
                "sme_comment": "",
            }

            for record in evidence.get("source_records", []):
                writer.writerow(
                    {
                        **base,
                        "evidence_role": record.get("evidence_role", ""),
                        "source_rule_id": record.get("source_rule_id", ""),
                        "source_rule": record.get("rule", ""),
                        "source_severity": record.get("severity", ""),
                        "source_relation": "in_batch",
                        "structural_similarity_score": "",
                        "shared_phrase": "",
                    }
                )

            for neighbor in evidence.get("structural_context", {}).get("structural_neighbors", []):
                writer.writerow(
                    {
                        **base,
                        "evidence_role": "structural_neighbor",
                        "source_rule_id": neighbor.get("source_rule_id", ""),
                        "source_rule": neighbor.get("rule", ""),
                        "source_severity": neighbor.get("severity", ""),
                        "source_relation": "cross_batch_neighbor",
                        "structural_similarity_score": neighbor.get("score", ""),
                        "shared_phrase": neighbor.get("shared_phrase", ""),
                    }
                )
    return output


def write_coverage_report(
    fragments: list[dict],
    evidence_dir: str | Path,
    rules: list[AlarmRule],
    output_path: str | Path,
) -> Path:
    evidence_root = Path(evidence_dir)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    representative_ids: set[str] = set()
    exception_ids: set[str] = set()
    neighbor_ids: set[str] = set()
    low_confidence = []
    high_critical_exceptions = []

    for fragment in fragments:
        metadata = fragment["metadata"]
        evidence = read_evidence_batch(evidence_root / f"{metadata['batch_id']}.json")
        if metadata.get("confidence", "").lower() in {"low", "very low"}:
            low_confidence.append(metadata)

        for record in evidence.get("source_records", []):
            source_id = record.get("source_rule_id", "")
            if record.get("evidence_role") == "representative":
                representative_ids.add(source_id)
            elif record.get("evidence_role") == "exception":
                exception_ids.add(source_id)
                if record.get("severity", "").lower() in {"high", "critical"}:
                    high_critical_exceptions.append((metadata, record))

        for neighbor in evidence.get("structural_context", {}).get("structural_neighbors", []):
            if neighbor.get("source_rule_id"):
                neighbor_ids.add(neighbor["source_rule_id"])

    all_ids = {rule.source_rule_id for rule in rules}
    covered_ids = representative_ids | exception_ids | neighbor_ids
    uncovered_ids = all_ids - covered_ids

    lines = [
        "# Alarm Knowledge Coverage Report",
        "",
        f"Total master rules: {len(rules)}",
        f"Total AI rules: {len(fragments)}",
        f"Rules covered as representative evidence: {len(representative_ids)}",
        f"Rules covered as exception evidence: {len(exception_ids)}",
        f"Rules covered as structural neighbors: {len(neighbor_ids)}",
        f"Unique source rules covered by SME evidence: {len(covered_ids)}",
        f"Uncovered source rules: {len(uncovered_ids)}",
        f"Low-confidence AI rules: {len(low_confidence)}",
        f"High/Critical exception rows: {len(high_critical_exceptions)}",
        "",
        "## Low-Confidence AI Rules",
        "",
    ]
    lines.extend(
        f"- {item.get('ai_rule_id')}: {item.get('pattern')} "
        f"({item.get('confidence')}, support={item.get('support')}, purity={item.get('purity')})"
        for item in low_confidence[:100]
    )
    if len(low_confidence) > 100:
        lines.append(f"- ... {len(low_confidence) - 100} more")

    lines.extend(["", "## High/Critical Exceptions", ""])
    for metadata, record in high_critical_exceptions[:100]:
        lines.append(
            f"- {metadata.get('ai_rule_id')}: {metadata.get('pattern')} -> "
            f"{record.get('source_rule_id')} {record.get('severity')} `{record.get('rule')}`"
        )
    if len(high_critical_exceptions) > 100:
        lines.append(f"- ... {len(high_critical_exceptions) - 100} more")

    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return output


def extract_review_sections(markdown: str) -> dict[str, str]:
    return {
        "core_logic": _section(markdown, "Core Logic"),
        "severity_split_logic": _section(markdown, "Severity Split Logic"),
        "escalation_conditions": _section(markdown, "Escalation Conditions"),
        "exception_logic": _section(markdown, "Exceptions"),
    }


def _section(markdown: str, heading: str) -> str:
    pattern = rf"^### {re.escape(heading)}\s*\n(.*?)(?=^### |\Z)"
    match = re.search(pattern, markdown, flags=re.DOTALL | re.MULTILINE)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1).strip())
