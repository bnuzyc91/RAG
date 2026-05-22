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
    write_master_rules_with_ids,
    write_evidence_batches,
)
from knowledge_builder.tools.fragment_tools import render_template_fragment, write_knowledge_fragment
from knowledge_builder.tools.merge_tools import (
    assign_ai_rule_ids,
    collect_fragments,
    read_curator_order,
    sort_fragments,
    write_merged_outputs,
)
from knowledge_builder.tools.review_outputs import write_coverage_report, write_sme_review_evidence
from knowledge_builder.tools.validation_tools import needs_critic, validate_fragment
from knowledge_builder.tools.fragment_tools import read_knowledge_fragment


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
    parser.add_argument("--batch-profile", choices=["detailed", "quality"], default="detailed")
    parser.add_argument("--max-depth", type=int, default=None)
    parser.add_argument("--min-support", type=int, default=None)
    parser.add_argument("--pure-threshold", type=float, default=None)
    parser.add_argument("--max-batch-support", type=int, default=None)
    parser.add_argument("--min-split-support", type=int, default=None)
    parser.add_argument("--min-information-gain", type=float, default=None)
    parser.add_argument("--min-child-coverage", type=float, default=None)
    parser.add_argument("--limit-batches", type=int, default=0)
    parser.add_argument("--resume", action="store_true", help="Skip already-valid fragments in work dir.")
    parser.add_argument("--force", action="store_true", help="Regenerate fragments even when --resume is set.")
    parser.add_argument("--plan-only", action="store_true", help="Only create evidence batches and print count.")
    return parser.parse_args()


async def run_pipeline(args: argparse.Namespace) -> dict:
    out_path = Path(args.out)
    work_dir = Path(args.work_dir) if args.work_dir else out_path.parent / "knowledge_build_work"
    evidence_dir = work_dir / "evidence_batches"
    fragment_dir = work_dir / "fragments"
    rejected_dir = work_dir / "rejected_fragments"
    critique_dir = work_dir / "critiques"
    curator_plan_path = work_dir / "curator_plan.json"
    progress_path = work_dir / "progress.jsonl"
    output_dir = out_path.parent

    rules = load_rules_csv(args.master)
    master_rules_with_ids_path = write_master_rules_with_ids(
        rules,
        output_dir / "master_rules_with_ids.csv",
    )
    batch_config = resolve_batch_config(args)
    batches = build_suffix_batches(
        rules,
        max_depth=batch_config["max_depth"],
        min_support=batch_config["min_support"],
        pure_threshold=batch_config["pure_threshold"],
        max_batch_support=batch_config["max_batch_support"],
        min_split_support=batch_config["min_split_support"],
        min_information_gain=batch_config["min_information_gain"],
        min_child_coverage=batch_config["min_child_coverage"],
    )
    if args.limit_batches:
        batches = batches[: args.limit_batches]
    batch_paths = write_evidence_batches(batches, evidence_dir)

    if args.plan_only:
        return {
            "rules_loaded": len(rules),
            "batches_created": len(batch_paths),
            "batch_profile": args.batch_profile,
            "batch_config": batch_config,
            "work_dir": str(work_dir),
            "evidence_dir": str(evidence_dir),
            "master_rules_with_ids": str(master_rules_with_ids_path),
        }

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
        fragment_path = fragment_dir / f"{evidence['batch_id']}.md"

        if args.resume and not args.force and fragment_path.exists():
            existing = read_knowledge_fragment(fragment_path)
            existing_validation = validate_fragment(existing, evidence)
            if existing_validation.ok:
                result = {
                    "batch_id": evidence["batch_id"],
                    "fragment_path": str(fragment_path),
                    "ok": True,
                    "skipped": True,
                    "blocking": [],
                    "warnings": existing_validation.warnings,
                    "critique_path": None,
                }
                fragment_results.append(result)
                append_progress(progress_path, {"status": "skipped", **result})
                continue

        try:
            markdown = await distill_fragment(
                evidence=evidence,
                batch_path=batch_path,
                mode=args.distill_mode,
                agent=distill_agent,
            )
        except Exception as exc:
            append_progress(
                progress_path,
                {
                    "status": "failed",
                    "batch_id": evidence["batch_id"],
                    "batch_path": str(batch_path),
                    "error": repr(exc),
                },
            )
            raise

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

        result = {
            "batch_id": evidence["batch_id"],
            "fragment_path": str(fragment_path),
            "ok": validation.ok,
            "skipped": False,
            "blocking": validation.blocking,
            "warnings": validation.warnings,
            "critique_path": str(critique_path) if critique_path else None,
        }
        fragment_results.append(result)
        append_progress(progress_path, {"status": "completed" if validation.ok else "rejected", **result})

    if args.curation_mode == "agent":
        await curate_fragments(fragment_dir, curator_plan_path, args.model)
        curator_order = read_curator_order(curator_plan_path)
    else:
        curator_order = []

    fragments = assign_ai_rule_ids(sort_fragments(collect_fragments(fragment_dir), curator_order))
    merged = write_merged_outputs(fragments, out_path, args.index_out)
    sme_review_path = write_sme_review_evidence(
        fragments,
        evidence_dir,
        output_dir / "sme_review_evidence.csv",
    )
    coverage_report_path = write_coverage_report(
        fragments,
        evidence_dir,
        rules,
        output_dir / "coverage_report.md",
    )

    return {
        "rules_loaded": len(rules),
        "batches_created": len(batch_paths),
        "fragments_merged": len(fragments),
        "batch_profile": args.batch_profile,
        "batch_config": batch_config,
        "work_dir": str(work_dir),
        "progress": str(progress_path),
        "knowledge_base": merged["markdown"],
        "index": merged["index"],
        "sme_review_evidence": str(sme_review_path),
        "master_rules_with_ids": str(master_rules_with_ids_path),
        "coverage_report": str(coverage_report_path),
        "fragment_results": fragment_results,
    }


def resolve_batch_config(args: argparse.Namespace) -> dict:
    profiles = {
        "detailed": {
            "max_depth": 3,
            "min_support": 3,
            "pure_threshold": 0.9,
            "max_batch_support": 0,
            "min_split_support": 0,
            "min_information_gain": 0.0,
            "min_child_coverage": 0.0,
        },
        "quality": {
            "max_depth": 5,
            "min_support": 10,
            "pure_threshold": 0.85,
            "max_batch_support": 150,
            "min_split_support": 30,
            "min_information_gain": 0.08,
            "min_child_coverage": 0.70,
        },
    }
    config = dict(profiles[args.batch_profile])
    for key in (
        "max_depth",
        "min_support",
        "pure_threshold",
        "max_batch_support",
        "min_split_support",
        "min_information_gain",
        "min_child_coverage",
    ):
        value = getattr(args, key)
        if value is not None:
            config[key] = value
    return config


def append_progress(progress_path: Path, payload: dict) -> None:
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    with progress_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


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
