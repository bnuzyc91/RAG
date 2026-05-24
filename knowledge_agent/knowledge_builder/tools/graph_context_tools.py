from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from knowledge_builder.tools.evidence_tools import read_evidence_batch, tokenize_rule
from knowledge_builder.tools.knowledge_model import build_knowledge_item, build_knowledge_items
from knowledge_builder.tools.review_outputs import extract_review_sections
from knowledge_builder.tools.validation_tools import parse_frontmatter


def attach_graph_context(batch_paths: list[Path]) -> dict[str, dict]:
    """Derive suffix parent/sibling context and write it into evidence JSON."""
    evidence_by_id = {read_evidence_batch(path)["batch_id"]: read_evidence_batch(path) for path in batch_paths}
    batch_ids_by_pattern = {}
    for batch_id, evidence in evidence_by_id.items():
        if str(evidence.get("pattern_type", "")).startswith("suffix"):
            batch_ids_by_pattern.setdefault(evidence["pattern"], []).append(batch_id)

    graph_by_id = {}
    for batch_id, evidence in evidence_by_id.items():
        pattern = evidence.get("pattern", "")
        ancestors = existing_ancestor_ids(pattern, batch_ids_by_pattern, exclude=batch_id)
        parent_batch_id = ancestors[-1] if ancestors else None
        parent_key = parent_pattern(pattern)
        graph_by_id[batch_id] = {
            "depth": suffix_depth(pattern),
            "parent_key": parent_key,
            "parent_batch_id": parent_batch_id,
            "ancestor_batch_ids": ancestors,
            "sibling_batch_ids": [],
        }

    siblings_by_key: dict[str, list[str]] = defaultdict(list)
    for batch_id, graph in graph_by_id.items():
        siblings_by_key[graph["parent_batch_id"] or graph["parent_key"] or "__root__"].append(batch_id)
    for sibling_ids in siblings_by_key.values():
        for batch_id in sibling_ids:
            graph_by_id[batch_id]["sibling_batch_ids"] = [
                other for other in sibling_ids if other != batch_id
            ]

    path_by_id = {read_evidence_batch(path)["batch_id"]: path for path in batch_paths}
    for batch_id, graph in graph_by_id.items():
        evidence = evidence_by_id[batch_id]
        evidence["graph_context"] = graph
        path_by_id[batch_id].write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return graph_by_id


def order_batch_paths_by_graph(batch_paths: list[Path], graph_by_id: dict[str, dict]) -> list[Path]:
    def key(path: Path) -> tuple[int, str]:
        batch_id = read_evidence_batch(path)["batch_id"]
        return (int(graph_by_id.get(batch_id, {}).get("depth", 0)), batch_id)

    return sorted(batch_paths, key=key)


def parent_context_for_evidence(evidence: dict, accepted_contexts: dict[str, dict]) -> list[dict]:
    graph = evidence.get("graph_context", {})
    context = []
    for ancestor_id in graph.get("ancestor_batch_ids", []):
        if ancestor_id in accepted_contexts:
            context.append(accepted_contexts[ancestor_id])
    return context


def accepted_context_from_fragment(markdown: str, evidence: dict) -> dict:
    metadata = parse_frontmatter(markdown)
    metadata.setdefault("ai_rule_id", metadata.get("batch_id"))
    item = build_knowledge_item(metadata, evidence, extract_review_sections(markdown))
    return {
        "batch_id": item["batch_id"],
        "pattern": item["pattern"],
        "classification_mode": item["classification_mode"],
        "do_not_use_suffix_alone": item["do_not_use_suffix_alone"],
        "default_severity": item["default_severity"],
        "confidence": item["confidence"],
        "core_finding": item["core_finding"],
        "top_split_logic": item["severity_split_logic"][:5],
        "fallback_logic": item["fallback_logic"],
    }


def write_sibling_conflict_report(
    fragments: list[dict],
    evidence_dir: str | Path,
    output_path: str | Path,
) -> Path:
    evidence_root = Path(evidence_dir)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    items = build_knowledge_items(fragments, evidence_root)
    item_by_batch = {item["batch_id"]: item for item in items}
    groups: dict[str, list[dict]] = defaultdict(list)

    for item in items:
        evidence = read_evidence_batch(evidence_root / f"{item['batch_id']}.json")
        graph = evidence.get("graph_context", {})
        group_key = graph.get("parent_batch_id") or graph.get("parent_key") or "__root__"
        groups[group_key].append(item)

    lines = ["# Sibling Conflict Report", ""]
    conflict_count = 0

    for group_key, siblings in sorted(groups.items()):
        if len(siblings) < 2:
            continue
        concrete = [
            item for item in siblings
            if item.get("default_severity") and item.get("classification_mode") in {"simple_default", "weak_default"}
        ]
        severities = sorted({item["default_severity"] for item in concrete})
        if len(severities) > 1:
            conflict_count += 1
            lines.extend([f"## Sibling Default Conflict: {group_key}", ""])
            for item in concrete:
                summary = item["batch_summary"]
                lines.append(
                    f"- {item['ai_rule_id']} `{item['pattern']}` -> {item['default_severity']} "
                    f"(mode={item['classification_mode']}, support={summary['support']}, purity={summary['purity']})"
                )
            lines.append("")

    for item in items:
        evidence = read_evidence_batch(evidence_root / f"{item['batch_id']}.json")
        parent_id = evidence.get("graph_context", {}).get("parent_batch_id")
        parent = item_by_batch.get(parent_id)
        if not parent:
            continue
        if parent.get("default_severity") and item.get("default_severity"):
            if parent["default_severity"] != item["default_severity"]:
                conflict_count += 1
                lines.extend(
                    [
                        f"## Parent/Child Default Difference: {parent['pattern']} -> {item['pattern']}",
                        "",
                        f"- Parent {parent['ai_rule_id']} default: {parent['default_severity']} ({parent['classification_mode']})",
                        f"- Child {item['ai_rule_id']} default: {item['default_severity']} ({item['classification_mode']})",
                        "- Review whether the child is a valid refinement or a contradiction.",
                        "",
                    ]
                )

    if conflict_count == 0:
        lines.append("No deterministic sibling or parent/child default conflicts were detected.")

    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return output


def suffix_depth(pattern: str) -> int:
    return len(tokenize_rule(pattern))


def parent_pattern(pattern: str) -> str | None:
    tokens = tokenize_rule(pattern)
    if len(tokens) <= 1:
        return None
    return "-".join(tokens[1:])


def existing_ancestor_ids(
    pattern: str,
    batch_ids_by_pattern: dict[str, list[str]],
    *,
    exclude: str,
) -> list[str]:
    tokens = tokenize_rule(pattern)
    ancestors = []
    for start in range(len(tokens) - 1, 0, -1):
        ancestor_pattern = "-".join(tokens[start:])
        for batch_id in sorted(batch_ids_by_pattern.get(ancestor_pattern, [])):
            if batch_id != exclude:
                ancestors.append(batch_id)
    return ancestors

