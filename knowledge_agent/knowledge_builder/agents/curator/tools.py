from __future__ import annotations

import json
from pathlib import Path

from knowledge_builder.tools.merge_tools import collect_fragments


def load_validated_fragments(fragment_dir: str) -> dict:
    """Load metadata and brief text previews for validated fragments."""
    fragments = collect_fragments(fragment_dir)
    previews = []
    for fragment in fragments:
        previews.append(
            {
                "path": fragment["path"],
                "metadata": fragment["metadata"],
                "preview": fragment["markdown"][:1200],
            }
        )
    return {"fragments": previews}


def write_curator_plan(plan_path: str, plan_json: str) -> dict:
    """Write a curator JSON plan after checking that it is valid JSON."""
    payload = json.loads(plan_json)
    path = Path(plan_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"path": str(path)}

