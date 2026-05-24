# Knowledge Agent

Python pipeline for building an alarm severity knowledge base from existing
master alarm rules.

This project is not generic RAG. It is a knowledge distillation workflow:
deterministic tools extract factual evidence, and ADK agents turn that evidence
into reusable Markdown rule knowledge.

See [PLAN.md](PLAN.md) for the full architecture.

## What It Builds

Input:

```text
master_rules.csv
```

Required columns:

- `Rule`
- `Severity`

Outputs:

- `alarm_rule_knowledge.md`
- `alarm_rule_knowledge.json`
- `alarm_rule_knowledge_index.json`
- `sme_review_evidence.csv`
- `master_rules_with_ids.csv`
- `coverage_report.md`
- `sibling_conflict_report.md`

## Architecture

```text
master_rules.csv
   |
   v
Deterministic Evidence Builder
   |
   |-- suffix-first quality batches
   |-- structural context
   |-- contrastive severity signals
   |-- cross-batch structural neighbors
   v
Batch Distiller Agent
   |
   v
Deterministic Validator
   |
   v
Critic Agent for risky fragments
   |
   v
direct merge OR curator agent plan
   |
   v
Deterministic Markdown + JSON Index Merger
```

The final knowledge base is always written by deterministic code. Agents may
distill, critique, or curate, but they do not silently change evidence numbers
or write the final canonical file.

`alarm_rule_knowledge.md` and `alarm_rule_knowledge.json` are rendered as
decision knowledge. Mixed batches use `classification_mode:
conditional_split`, with count-backed `severity_split_logic`, instead of one
large default rule with a long exception list.

The build uses lightweight graph context:

- suffix batches are processed from broad to specific
- accepted ancestor summaries are injected into child distillation
- deterministic virtual ancestor summaries are included even when a parent
  suffix was not emitted as its own batch
- failed validation can retry with critic/validator feedback
- sibling and parent/child default conflicts are reported deterministically

## Install

```bash
cd /Users/yichenzhou/Documents/GitHub/RAG/knowledge_agent
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`google-adk` is only needed for:

- `--distill-mode adk`
- `--critic-mode adk`
- `--curation-mode agent`

Template mode uses only local deterministic code and is useful for smoke tests.

## Recommended Build

Use the quality profile and resume support for a real 9,900-rule build:

```bash
PYTHONPATH=/Users/yichenzhou/Documents/GitHub/RAG/knowledge_agent \
python -m knowledge_builder.pipeline.run_build_kb \
  --master /path/to/master_rules.csv \
  --out /path/to/alarm_rule_knowledge.md \
  --work-dir /path/to/knowledge_build_work_quality \
  --batch-profile quality \
  --distill-mode adk \
  --critic-mode adk \
  --curation-mode direct \
  --resume
```

Use `--curation-mode agent` when you want the curator agent to suggest ordering
before deterministic merge:

```bash
PYTHONPATH=/Users/yichenzhou/Documents/GitHub/RAG/knowledge_agent \
python -m knowledge_builder.pipeline.run_build_kb \
  --master /path/to/master_rules.csv \
  --out /path/to/alarm_rule_knowledge.md \
  --work-dir /path/to/knowledge_build_work_quality \
  --batch-profile quality \
  --distill-mode adk \
  --critic-mode adk \
  --curation-mode agent \
  --resume
```

## Estimate Batch Count

Use `--plan-only` to create evidence batches and report the count without
calling the LLM:

```bash
PYTHONPATH=/Users/yichenzhou/Documents/GitHub/RAG/knowledge_agent \
python -m knowledge_builder.pipeline.run_build_kb \
  --master /path/to/master_rules.csv \
  --out /tmp/alarm_rule_knowledge.md \
  --work-dir /tmp/alarm_kb_quality_work \
  --batch-profile quality \
  --plan-only
```

This is the best first command after changing batch constraints.

## Batch Profiles

`detailed` produces more, smaller suffix batches:

```text
max_depth: 3
min_support: 3
pure_threshold: 0.9
min_split_support: 0
min_information_gain: 0.0
min_child_coverage: 0.0
```

`quality` produces fewer, broader, higher-signal batches:

```text
max_depth: 5
min_support: 10
pure_threshold: 0.85
max_batch_support: 150
min_split_support: 30
min_information_gain: 0.08
min_child_coverage: 0.70
```

You can override profile values from the CLI:

```bash
--min-support 20
--pure-threshold 0.8
--max-batch-support 200
--min-split-support 50
--min-information-gain 0.12
--min-child-coverage 0.8
--max-depth 4
```

## Structural Context

Batches are still suffix-first, but every batch now includes structural context
so the distiller does not only summarize suffix statistics.

Each evidence batch includes:

- severity distribution
- support, purity, entropy
- representative examples
- counterexamples
- common prefixes
- common suffixes
- common contiguous phrases
- common tokens
- severity-specific contrast
- child suffix distributions
- contrastive severity signals with support, purity, and lift
- cross-batch structural neighbors

This helps the agent learn patterns such as:

```text
PROTECTION + BATTERY + VOLTAGE -> possible escalation
UPS/DC-SYSTEM + BATTERY-VOLTAGE-ALARM -> often diagnostic monitoring
LOW-VOLTAGE-ALARM neighbor -> useful high-severity comparison
```

Broad low-purity suffixes such as `ALARM` are not good standalone rules. The
quality profile now forces very large groups to split when supported child
suffixes exist, and the evidence includes child suffix distributions so the
agent can learn an internal taxonomy rather than one generic default.

Mixed batches also include contrastive feature mining. The evidence builder
counts tokens and contiguous phrases by severity, then provides count-backed
signals such as:

```text
PRIMARY-MASTER -> Diagnostic, support=N, purity=P
MULTIMEDIA-MESSAGING-SERVICE -> Medium, support=N, purity=P
```

The distiller should use these signals for `Severity Split Logic` instead of
inventing unsupported differences between severity groups.

`max_batch_support` is a hard cap for emitted LLM batches. If a group is still
too large after suffix splitting reaches `max_depth`, the builder creates
deterministic `suffix_part` mini-batches ordered by structural suffix. These
overflow parts are a last resort to avoid one large, complex, mixed LLM call.

## Resume After API Failure

Use the same `--work-dir` and add:

```bash
--resume
```

The pipeline skips any existing fragment that still validates against the
current evidence batch. If the LLM call fails midway, rerun the same command and
it continues from unfinished or invalid batches.

Progress is appended to:

```text
<work-dir>/progress.jsonl
```

Use:

```bash
--force
```

when you intentionally want to regenerate fragments even if valid fragments
already exist.

## Work Directory

The selected `--work-dir` contains:

```text
evidence_batches/
  deterministic JSON packets sent to the distiller

fragments/
  validated Markdown knowledge fragments

critiques/
  critic reports for risky or failed fragments

rejected_fragments/
  fragments that failed deterministic validation

curator_plan.json
  optional organization plan from curator agent

progress.jsonl
  append-only status log for resumable runs
```

The final output folder also includes `sibling_conflict_report.md`, which flags
deterministic default-severity conflicts between sibling batches or parent/child
batches. It is a review report, not an automatic resolver.

Do not rebuild from the final `alarm_rule_knowledge.md`. It is already
distilled and lossy. Rebuild from the original CSV plus the work directory.

## SME Review Evidence CSV

The SME review file is long format:

```text
one row = one AI rule + one original source rule evidence row
```

Columns:

```text
ai_rule_id
batch_id
pattern_type
pattern
default_severity
confidence
support
purity
entropy
core_logic
severity_split_logic
escalation_conditions
exception_logic
evidence_role
source_rule_id
source_rule
source_severity
source_relation
structural_similarity_score
shared_phrase
sme_review_status
sme_corrected_default_severity
sme_comment
```

Evidence roles:

- `representative`: in-batch source rule whose severity agrees with the AI
  default severity
- `exception`: in-batch source rule whose severity does not agree with the AI
  default severity
- `structural_neighbor`: out-of-batch source rule that is structurally similar
  and useful review context

`master_rules_with_ids.csv` is the traceable source-of-truth file for
`source_rule_id`.

## Agent Layout

Each agent is organized as:

```text
agents/<agent_name>/
  skill.md
  prompt.md
  tools.py
  agent.py
```

At runtime, the ADK instruction is composed from:

```text
skill.md
+ prompts/shared_guardrails.md
+ prompt.md
```

Current agents:

- `batch_distiller`: writes one Markdown knowledge fragment from one evidence
  batch
- `critic`: audits risky fragments against source evidence
- `curator`: optionally proposes final organization before deterministic merge

## Local Template Smoke Test

Use this when you want to verify batching, validation, merging, and output paths
without ADK calls:

```bash
PYTHONPATH=/Users/yichenzhou/Documents/GitHub/RAG/knowledge_agent \
python -m knowledge_builder.pipeline.run_build_kb \
  --master /path/to/master_rules.csv \
  --out /tmp/alarm_rule_knowledge.md \
  --work-dir /tmp/alarm_kb_template_work \
  --batch-profile quality \
  --distill-mode template \
  --critic-mode template \
  --curation-mode direct
```

## Known Limitation

The current batch boundary is still suffix-based. Structural context and
neighbors reduce suffix tunnel vision, but they do not fully replace true
cross-suffix structural clustering.

Recommended future extension:

```text
hybrid batch builder:
  1. suffix_quality batches
  2. structural_phrase batches
  3. severity_exception batches
```
