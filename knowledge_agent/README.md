# Knowledge Agent

Python scaffold for building an alarm severity knowledge base from existing
alarm rules.

The design uses deterministic evidence extraction plus Google ADK agents:

- Batch Distiller Agent: required for semantic knowledge extraction.
- Critic Agent: conditional review for risky fragments.
- Curator Agent: optional organization plan before final deterministic merge.
- Deterministic Merger: always writes the final Markdown and JSON index.

See [PLAN.md](PLAN.md) for the full architecture.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`google-adk` is only required for `--distill-mode adk` or
`--curation-mode agent`. The deterministic template path uses only the Python
standard library.

## Run Direct Template Mode

```bash
PYTHONPATH=/Users/yichenzhou/Documents/GitHub/RAG/knowledge_agent \
python -m knowledge_builder.pipeline.run_build_kb \
  --master /path/to/master_rules.csv \
  --out /tmp/alarm_rule_knowledge.md \
  --distill-mode template \
  --curation-mode direct
```

## Run ADK Mode

Configure Gemini/ADK credentials according to your environment, then run:

```bash
PYTHONPATH=/Users/yichenzhou/Documents/GitHub/RAG/knowledge_agent \
python -m knowledge_builder.pipeline.run_build_kb \
  --master /path/to/master_rules.csv \
  --out /tmp/alarm_rule_knowledge.md \
  --distill-mode adk \
  --curation-mode agent \
  --model gemini-2.0-flash
```

## Fewer Higher-Quality Batches

Use the quality batch profile to avoid creating many tiny suffix-only batches:

```bash
PYTHONPATH=/Users/yichenzhou/Documents/GitHub/RAG/knowledge_agent \
python -m knowledge_builder.pipeline.run_build_kb \
  --master /path/to/master_rules.csv \
  --out /tmp/alarm_rule_knowledge.md \
  --work-dir /tmp/alarm_kb_quality_work \
  --batch-profile quality \
  --distill-mode adk \
  --curation-mode direct \
  --resume
```

The quality profile uses broader batch gates:

- `min_support`: 10
- `min_split_support`: 30
- `min_information_gain`: 0.08
- `min_child_coverage`: 0.70
- `pure_threshold`: 0.85

This means a suffix group is only split into more specific batches when the
split has enough support, covers enough of the parent group, and improves the
severity signal. The result should be fewer, stronger batches than the detailed
profile.

To estimate the batch count without making LLM calls:

```bash
PYTHONPATH=/Users/yichenzhou/Documents/GitHub/RAG/knowledge_agent \
python -m knowledge_builder.pipeline.run_build_kb \
  --master /path/to/master_rules.csv \
  --out /tmp/alarm_rule_knowledge.md \
  --work-dir /tmp/alarm_kb_quality_work \
  --batch-profile quality \
  --plan-only
```

## Resume After API Failure

Use the same `--work-dir` and add `--resume`. The pipeline skips any existing
fragment that still passes validation and continues with the remaining batches.

Progress is appended to:

```text
<work-dir>/progress.jsonl
```

Use `--force` with `--resume` when you intentionally want to regenerate all
fragments in the work directory.

## Expected Input

CSV with columns:

- `Rule`
- `Severity`

## Output

- `alarm_rule_knowledge.md`
- `alarm_rule_knowledge_index.json`
- evidence batches under the selected work directory
- generated fragments under the selected work directory
- critique reports for risky fragments
- optional curator plan
