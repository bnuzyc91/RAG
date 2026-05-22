from __future__ import annotations

import json
from pathlib import Path

from knowledge_builder.tools.fragment_tools import read_knowledge_fragment
from knowledge_builder.tools.knowledge_model import (
    build_knowledge_items,
    render_knowledge_markdown,
    write_knowledge_json,
)
from knowledge_builder.tools.validation_tools import parse_frontmatter


def collect_fragments(fragment_dir: str | Path) -> list[dict]:
    fragments = []
    for path in sorted(Path(fragment_dir).glob("*.md")):
        markdown = read_knowledge_fragment(path)
        metadata = parse_frontmatter(markdown)
        fragments.append({"path": str(path), "metadata": metadata, "markdown": markdown})
    return fragments


def read_curator_order(curator_plan_path: str | Path | None) -> list[str]:
    if not curator_plan_path:
        return []
    path = Path(curator_plan_path)
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in payload.get("batch_order", [])]


def sort_fragments(fragments: list[dict], curator_order: list[str] | None = None) -> list[dict]:
    order = {batch_id: index for index, batch_id in enumerate(curator_order or [])}

    def key(fragment: dict) -> tuple[int, str, str]:
        metadata = fragment["metadata"]
        batch_id = metadata.get("batch_id", "")
        return (
            order.get(batch_id, 10_000),
            metadata.get("pattern_type", ""),
            metadata.get("pattern", ""),
        )

    return sorted(fragments, key=key)


def assign_ai_rule_ids(fragments: list[dict]) -> list[dict]:
    assigned = []
    for index, fragment in enumerate(fragments, start=1):
        copied = dict(fragment)
        metadata = dict(copied.get("metadata", {}))
        metadata["ai_rule_id"] = f"AIRULE-{index:06d}"
        copied["metadata"] = metadata
        assigned.append(copied)
    return assigned


def build_index(fragments: list[dict]) -> dict:
    items = []
    for fragment in fragments:
        metadata = fragment["metadata"]
        items.append(
            {
                "ai_rule_id": metadata.get("ai_rule_id"),
                "batch_id": metadata.get("batch_id"),
                "pattern_type": metadata.get("pattern_type"),
                "pattern": metadata.get("pattern"),
                "default_severity": metadata.get("default_severity"),
                "support": _int(metadata.get("support")),
                "purity": _float(metadata.get("purity")),
                "entropy": _float(metadata.get("entropy")),
                "confidence": metadata.get("confidence"),
                "fragment_path": fragment["path"],
            }
        )
    return {"patterns": items}


def write_merged_outputs(
    fragments: list[dict],
    markdown_out: str | Path,
    evidence_dir: str | Path,
    index_out: str | Path | None = None,
) -> dict:
    markdown_path = Path(markdown_out)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    knowledge_items = build_knowledge_items(fragments, evidence_dir)
    markdown_path.write_text(render_knowledge_markdown(knowledge_items), encoding="utf-8")

    index_path = Path(index_out) if index_out else markdown_path.with_name(f"{markdown_path.stem}_index.json")
    index_path.write_text(json.dumps(build_index(fragments), indent=2), encoding="utf-8")

    knowledge_json_path = markdown_path.with_suffix(".json")
    write_knowledge_json(knowledge_items, knowledge_json_path)
    return {
        "markdown": str(markdown_path),
        "index": str(index_path),
        "knowledge_json": str(knowledge_json_path),
    }


def _int(value: str | None) -> int:
    try:
        return int(value or "0")
    except ValueError:
        return 0


def _float(value: str | None) -> float:
    try:
        return float(value or "0")
    except ValueError:
        return 0.0
