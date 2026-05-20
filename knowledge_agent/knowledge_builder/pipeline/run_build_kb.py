from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path

from knowledge_builder.tools.evidence_tools import (
    build_suffix_batches,
    load_rules_csv,
    read_evidence_batch,
    write_evidence_batches,
)
from knowledge_builder.tools.fragment_tools import render_template_fragment, write_knowledge_fragment
from knowledge_builder.tools.merge_tools import (
    collect_fragments,
    read_curator_order,
    sort_fragments,
    write_merged_outputs,
)
from knowledge_builder.tools.validation_tools import needs_critic, validate_fragment


def main() -> None:
    args = parse_args()
    result = asyncio.run(run_pipeline(args))
    print(json.dumps(result, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build alarm severity Markdown knowledge base.")
    parser.add_argument("--master", required=True, help="CSV with Rule and Severity columns.")
    parser.add_argument("--out", required=True, help="Final Markdown knowledge base path.")
    parser.add_argument("--index-out", default=None, help="Optional JSON index path.")
    parser.add_argument("--work-dir", default=None, help="Intermediate output directory.")
    parser.add_argument("--distill-mode", choices=["template", "adk"], default="template")
    parser.add_argument("--critic-mode", choices=["template", "adk", "off"], default="template")
    parser.add_argument("--curation-mode", choices=["direct", "agent"], default="direct")
    parser.add_argument("--model", default="gemini-2.0-flash")
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--min-support", type=int, default=3)
    parser.add_argument("--pure-threshold", type=float, default=0.9)
    parser.add_argument("--limit-batches", type=int, default=0)
    return parser.parse_args()


async def run_pipeline(args: argparse.Namespace) -> dict:
    out_path = Path(args.out)
    work_dir = Path(args.work_dir) if args.work_dir else out_path.parent / "knowledge_build_work"
    evidence_dir = work_dir / "evidence_batches"
    fragment_dir = work_dir / "fragments"
    rejected_dir = work_dir / "rejected_fragments"
    critique_dir = work_dir / "critiques"
    curator_plan_path = work_dir / "curator_plan.json"

    rules = load_rules_csv(args.master)
    batches = build_suffix_batches(
        rules,
        max_depth=args.max_depth,
        min_support=args.min_support,
        pure_threshold=args.pure_threshold,
    )
    if args.limit_batches:
        batches = batches[: args.limit_batches]
    batch_paths = write_evidence_batches(batches, evidence_dir)

    distill_agent = None
    if args.distill_mode == "adk":
        from knowledge_builder.agents.batch_distiller.agent import create_agent

        distill_agent = create_agent(args.model)

    critic_agent = None
    if args.critic_mode == "adk":
        from knowledge_builder.agents.critic.agent import create_agent

        critic_agent = create_agent(args.model)

    fragment_results = []
    for batch_path in batch_paths:
        evidence = read_evidence_batch(batch_path)
        markdown = await distill_fragment(
            evidence=evidence,
            batch_path=batch_path,
            mode=args.distill_mode,
            agent=distill_agent,
        )
        fragment_path = fragment_dir / f"{evidence['batch_id']}.md"
        write_knowledge_fragment(fragment_path, markdown)

        validation = validate_fragment(markdown, evidence)
        critique_path = None
        if args.critic_mode != "off" and needs_critic(validation, evidence):
            critique_path = critique_dir / f"{evidence['batch_id']}.md"
            report = await critique_fragment(
                evidence=evidence,
                batch_path=batch_path,
                fragment_path=fragment_path,
                validation=validation,
                mode=args.critic_mode,
                agent=critic_agent,
            )
            write_knowledge_fragment(critique_path, report)

        if not validation.ok:
            rejected_dir.mkdir(parents=True, exist_ok=True)
            rejected_path = rejected_dir / fragment_path.name
            rejected_path.write_text(markdown, encoding="utf-8")
            fragment_path.unlink(missing_ok=True)

        fragment_results.append(
            {
                "batch_id": evidence["batch_id"],
                "fragment_path": str(fragment_path),
                "ok": validation.ok,
                "blocking": validation.blocking,
                "warnings": validation.warnings,
                "critique_path": str(critique_path) if critique_path else None,
            }
        )

    if args.curation_mode == "agent":
        await curate_fragments(fragment_dir, curator_plan_path, args.model)
        curator_order = read_curator_order(curator_plan_path)
    else:
        curator_order = []

    fragments = sort_fragments(collect_fragments(fragment_dir), curator_order)
    merged = write_merged_outputs(fragments, out_path, args.index_out)

    return {
        "rules_loaded": len(rules),
        "batches_created": len(batch_paths),
        "fragments_merged": len(fragments),
        "work_dir": str(work_dir),
        "knowledge_base": merged["markdown"],
        "index": merged["index"],
        "fragment_results": fragment_results,
    }


async def distill_fragment(
    *,
    evidence: dict,
    batch_path: Path,
    mode: str,
    agent,
) -> str:
    if mode == "template":
        return render_template_fragment(evidence)

    from knowledge_builder.tools.adk_runtime import call_agent_text

    prompt = (
        "Distill this evidence batch into the required Markdown fragment.\n\n"
        f"Evidence batch path: {batch_path}\n\n"
        "Evidence JSON:\n"
        f"{json.dumps(evidence, indent=2)}"
    )
    return await call_agent_text(agent, prompt)


async def critique_fragment(
    *,
    evidence: dict,
    batch_path: Path,
    fragment_path: Path,
    validation,
    mode: str,
    agent,
) -> str:
    if mode == "template":
        return render_template_critique(evidence, validation)

    from knowledge_builder.tools.adk_runtime import call_agent_text

    prompt = (
        "Critique this generated fragment. Return a critique report only.\n\n"
        f"Evidence batch path: {batch_path}\n"
        f"Fragment path: {fragment_path}\n\n"
        "Evidence JSON:\n"
        f"{json.dumps(evidence, indent=2)}\n\n"
        "Deterministic validation:\n"
        f"{json.dumps({'blocking': validation.blocking, 'warnings': validation.warnings}, indent=2)}"
    )
    return await call_agent_text(agent, prompt)


async def curate_fragments(fragment_dir: Path, plan_path: Path, model: str) -> None:
    from knowledge_builder.agents.curator.agent import create_agent
    from knowledge_builder.tools.adk_runtime import call_agent_text

    agent = create_agent(model)
    fragments = collect_fragments(fragment_dir)
    metadata = [fragment["metadata"] for fragment in fragments]
    prompt = (
        "Create a curator JSON plan for these validated fragments. "
        "Return JSON only.\n\n"
        f"Fragment directory: {fragment_dir}\n\n"
        f"Fragment metadata:\n{json.dumps(metadata, indent=2)}"
    )
    response = await call_agent_text(agent, prompt)
    payload = extract_json_object(response)
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def render_template_critique(evidence: dict, validation) -> str:
    blocking = "\n".join(f"- {item}" for item in validation.blocking) or "- None."
    warnings = "\n".join(f"- {item}" for item in validation.warnings) or "- None."
    return f"""# Critique Report

Batch: {evidence["batch_id"]}

## Blocking Issues

{blocking}

## Warnings

{warnings}

## Notes

- Template critic only reports deterministic validation findings.

## Required Fix Direction

If blocking issues exist, regenerate the fragment from the source evidence and
preserve all frontmatter evidence fields exactly.
"""


def extract_json_object(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if not match:
            return {"batch_order": [], "section_notes": [], "conflicts": []}
        payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        return {"batch_order": [], "section_notes": [], "conflicts": []}
    payload.setdefault("batch_order", [])
    payload.setdefault("section_notes", [])
    payload.setdefault("conflicts", [])
    return payload


if __name__ == "__main__":
    main()

