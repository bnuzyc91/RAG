from __future__ import annotations

import json
from pathlib import Path

from knowledge_builder.tools.evidence_tools import read_evidence_batch, tokenize_rule
from knowledge_builder.tools.review_outputs import extract_review_sections


def build_knowledge_items(fragments: list[dict], evidence_dir: str | Path) -> list[dict]:
    evidence_root = Path(evidence_dir)
    items = []
    for fragment in fragments:
        metadata = fragment["metadata"]
        evidence = read_evidence_batch(evidence_root / f"{metadata['batch_id']}.json")
        sections = extract_review_sections(fragment["markdown"])
        items.append(build_knowledge_item(metadata, evidence, sections))
    return items


def build_knowledge_item(metadata: dict, evidence: dict, sections: dict) -> dict:
    purity = float(evidence.get("purity", 0.0))
    split_logic = build_severity_split_logic(evidence)
    classification_mode = classify_batch(evidence, split_logic)
    do_not_use_suffix_alone = classification_mode in {"conditional_split", "taxonomy_container"}

    return {
        "ai_rule_id": metadata.get("ai_rule_id"),
        "batch_id": metadata.get("batch_id"),
        "pattern_type": metadata.get("pattern_type"),
        "pattern": metadata.get("pattern"),
        "classification_mode": classification_mode,
        "do_not_use_suffix_alone": do_not_use_suffix_alone,
        "default_severity": None if do_not_use_suffix_alone else metadata.get("default_severity"),
        "confidence": metadata.get("confidence"),
        "batch_summary": {
            "support": int(evidence.get("support", 0)),
            "severity_distribution": evidence.get("severity_distribution", {}),
            "dominant_severity": evidence.get("dominant_severity"),
            "purity": purity,
            "entropy": float(evidence.get("entropy", 0.0)),
        },
        "core_finding": core_finding(evidence, classification_mode, sections),
        "severity_split_logic": split_logic,
        "fallback_logic": fallback_logic(evidence, classification_mode),
        "representative_examples": examples_by_role(evidence, "representative"),
        "exceptions": examples_by_role(evidence, "exception"),
        "sme_review_questions": sme_review_questions(evidence, split_logic, classification_mode),
    }


def classify_batch(evidence: dict, split_logic: list[dict]) -> str:
    support = int(evidence.get("support", 0))
    purity = float(evidence.get("purity", 0.0))
    pattern = str(evidence.get("pattern", ""))
    is_part = str(evidence.get("pattern_type", "")).endswith("_part")

    if purity >= 0.85 and not is_part:
        return "simple_default"
    if split_logic:
        return "conditional_split"
    if support >= 100 or pattern in {"ALARM", "FAIL", "STATUS"} or is_part:
        return "taxonomy_container"
    return "weak_default"


def build_severity_split_logic(evidence: dict, *, max_rules: int = 12, max_per_severity: int = 4) -> list[dict]:
    contrastive = evidence.get("contrastive_context", {})
    signals_by_severity = contrastive.get("signals_by_severity", {})
    rules = evidence.get("source_records", [])

    by_severity: dict[str, list[dict]] = {}
    for severity, signals in signals_by_severity.items():
        candidates = []
        for signal in signals:
            if signal.get("support", 0) < 2:
                continue
            if float(signal.get("purity", 0.0)) < 0.70:
                continue
            if feature_specificity(signal.get("feature", "")) > 3:
                continue
            candidates.append(signal)
        by_severity[severity] = select_non_redundant_signals(candidates, max_items=max_per_severity)

    ordered_pairs = []
    for index in range(max_per_severity):
        for severity in sorted(by_severity):
            if index < len(by_severity[severity]):
                ordered_pairs.append((severity, by_severity[severity][index]))

    out = []
    for severity, signal in ordered_pairs[:max_rules]:
        feature = signal.get("feature", "")
        matching = [record for record in rules if record_matches_feature(record, feature)]
        examples = [
            record["source_rule_id"]
            for record in matching
            if record.get("severity") == severity
        ][:5]
        counterexamples = [
            record["source_rule_id"]
            for record in matching
            if record.get("severity") != severity
        ][:5]
        out.append(
            {
                "condition": f"contains {feature}",
                "feature": feature,
                "feature_type": signal.get("feature_type"),
                "predicts_severity": severity,
                "support": int(signal.get("support", 0)),
                "purity": float(signal.get("purity", 0.0)),
                "lift": float(signal.get("lift", 0.0)),
                "severity_distribution": signal.get("severity_distribution", {}),
                "rationale": rationale_for_signal(feature, severity),
                "example_rule_ids": examples,
                "counterexample_rule_ids": counterexamples,
            }
        )
    return out


def select_non_redundant_signals(signals: list[dict], *, max_items: int) -> list[dict]:
    ordered = sorted(
        signals,
        key=lambda item: (
            -float(item.get("purity", 0.0)),
            -int(item.get("support", 0)),
            -feature_specificity(item.get("feature", "")),
            -float(item.get("lift", 0.0)),
            item.get("feature", ""),
        ),
    )
    selected = []
    for signal in ordered:
        feature = signal.get("feature", "")
        if is_redundant_feature(feature, [item.get("feature", "") for item in selected]):
            continue
        selected.append(signal)
        if len(selected) >= max_items:
            break
    return selected


def is_redundant_feature(feature: str, selected_features: list[str]) -> bool:
    feature_tokens = tokenize_rule(feature)
    for selected in selected_features:
        selected_tokens = tokenize_rule(selected)
        if contains_subsequence(feature_tokens, selected_tokens):
            return True
        if contains_subsequence(selected_tokens, feature_tokens):
            return True
    return False


def contains_subsequence(tokens: list[str], pattern: list[str]) -> bool:
    if not pattern or len(pattern) > len(tokens):
        return False
    for start in range(0, len(tokens) - len(pattern) + 1):
        if tokens[start : start + len(pattern)] == pattern:
            return True
    return False


def feature_specificity(feature: str) -> int:
    return len(tokenize_rule(feature))


def record_matches_feature(record: dict, feature: str) -> bool:
    tokens = tokenize_rule(record.get("rule", ""))
    feature_tokens = tokenize_rule(feature)
    if not feature_tokens:
        return False
    if len(feature_tokens) == 1:
        return feature_tokens[0] in tokens
    for start in range(0, len(tokens) - len(feature_tokens) + 1):
        if tokens[start : start + len(feature_tokens)] == feature_tokens:
            return True
    return False


def rationale_for_signal(feature: str, severity: str) -> str:
    return (
        f"The feature `{feature}` is a count-backed contrastive signal for "
        f"{severity} severity within this batch."
    )


def core_finding(evidence: dict, classification_mode: str, sections: dict) -> str:
    pattern = evidence.get("pattern")
    if classification_mode == "simple_default":
        return (
            f"`{pattern}` is a relatively stable severity pattern in this batch. "
            "Use the default severity unless an exception signal is present."
        )
    if classification_mode == "conditional_split":
        return (
            f"`{pattern}` is not severity-deterministic by itself. Severity is "
            "better explained by internal tokens and contrastive subpatterns."
        )
    if classification_mode == "taxonomy_container":
        return (
            f"`{pattern}` is a broad container rather than a standalone severity "
            "rule. Use child suffixes, structural signals, and split logic."
        )
    return sections.get("core_logic") or (
        f"`{pattern}` has weak default evidence. Use with low confidence and review."
    )


def fallback_logic(evidence: dict, classification_mode: str) -> dict:
    dominant = evidence.get("dominant_severity")
    if classification_mode == "simple_default":
        return {
            "severity": dominant,
            "confidence": "Medium",
            "use_when": "No listed exception or stronger split signal is present.",
        }
    return {
        "severity": dominant,
        "confidence": "Low",
        "use_when": "No count-backed split signal matches; request SME or manual review when impact is unclear.",
    }


def examples_by_role(evidence: dict, role: str) -> list[dict]:
    return [
        {
            "source_rule_id": record.get("source_rule_id"),
            "rule": record.get("rule"),
            "severity": record.get("severity"),
        }
        for record in evidence.get("source_records", [])
        if record.get("evidence_role") == role
    ][:10]


def sme_review_questions(evidence: dict, split_logic: list[dict], classification_mode: str) -> list[str]:
    questions = []
    pattern = evidence.get("pattern")
    if classification_mode != "simple_default":
        questions.append(f"Should `{pattern}` be treated as a conditional/taxonomy pattern instead of a default severity rule?")
    for item in split_logic[:6]:
        questions.append(
            f"Is `{item['feature']}` a valid signal for {item['predicts_severity']} severity?"
        )
    if evidence.get("counterexamples"):
        questions.append("Are the listed exception severities correct, or should the AI rule default be changed?")
    return questions


def render_knowledge_markdown(items: list[dict]) -> str:
    lines = [
        "# Alarm Rule Severity Knowledge Base",
        "",
        "This file is generated from master alarm rules. Mixed batches are rendered",
        "as conditional decision logic instead of one default severity rule.",
        "",
        "## Prediction Checklist",
        "",
        "1. Prefer count-backed split logic over suffix-only defaults.",
        "2. Treat `do_not_use_suffix_alone: true` rules as conditional.",
        "3. Use fallback severity only when no stronger condition matches.",
        "4. Return `ai_rule_id` and source rule evidence with predictions.",
        "",
        "## AI Rules",
        "",
    ]
    for item in items:
        lines.extend(render_item_markdown(item))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_item_markdown(item: dict) -> list[str]:
    summary = item["batch_summary"]
    lines = [
        f"## {item['ai_rule_id']}: {item['pattern']}",
        "",
        f"Classification mode: `{item['classification_mode']}`",
        f"Do not use suffix alone: `{str(item['do_not_use_suffix_alone']).lower()}`",
        f"Default severity: `{item.get('default_severity') or 'conditional'}`",
        f"Confidence: `{item.get('confidence')}`",
        "",
        "### Evidence Summary",
        "",
        f"Support: {summary['support']}",
        f"Purity: {summary['purity']}",
        f"Entropy: {summary['entropy']}",
        "",
        "Severity distribution:",
    ]
    for severity, count in summary.get("severity_distribution", {}).items():
        lines.append(f"- {severity}: {count}")
    lines.extend(["", "### Core Finding", "", item["core_finding"], ""])
    if item["severity_split_logic"]:
        lines.extend(["### Severity Split Logic", "", "| Signal | Predicts | Support | Purity | Lift |", "|---|---:|---:|---:|---:|"])
        for signal in item["severity_split_logic"]:
            lines.append(
                f"| `{signal['feature']}` | {signal['predicts_severity']} | "
                f"{signal['support']} | {signal['purity']} | {signal['lift']} |"
            )
        lines.extend(["", "### Decision Logic", ""])
        for index, signal in enumerate(item["severity_split_logic"][:8], start=1):
            lines.append(f"{index}. If the rule {signal['condition']}, predict `{signal['predicts_severity']}`.")
        fallback = item["fallback_logic"]
        lines.append(f"{len(item['severity_split_logic'][:8]) + 1}. Otherwise use `{fallback['severity']}` with `{fallback['confidence']}` confidence: {fallback['use_when']}")
        lines.append("")
    else:
        fallback = item["fallback_logic"]
        lines.extend(["### Decision Logic", "", f"Use `{fallback['severity']}` when: {fallback['use_when']}", ""])

    lines.extend(["### Examples", ""])
    if item["representative_examples"]:
        lines.append("Representative:")
        for example in item["representative_examples"][:5]:
            lines.append(f"- {example['source_rule_id']} `{example['rule']}` -> {example['severity']}")
    if item["exceptions"]:
        lines.append("")
        lines.append("Exceptions:")
        for example in item["exceptions"][:5]:
            lines.append(f"- {example['source_rule_id']} `{example['rule']}` -> {example['severity']}")

    if item["sme_review_questions"]:
        lines.extend(["", "### SME Review Questions", ""])
        for question in item["sme_review_questions"]:
            lines.append(f"- {question}")
    return lines


def write_knowledge_json(items: list[dict], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"ai_rules": items}, indent=2), encoding="utf-8")
    return path
