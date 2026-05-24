# Alarm Rule Knowledge Agent Plan

This project builds a Markdown knowledge base for alarm severity prediction.
The goal is not generic RAG. The goal is to distill the underlying patterns in
existing alarm rules into durable reference logic that can later support
real-time prediction.

The build phase uses deterministic code for facts and agents for judgment:

- deterministic tools compute batches, support, purity, entropy, structural
  context, validation, and final merge
- ADK agents distill, critique, and optionally curate knowledge
- the final canonical Markdown and JSON index are always written by deterministic
  code

## Current Workflow

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
Deterministic Fragment Validator
   |
   v
Critic Agent for risky or failed fragments
   |
   v
Merge mode:
   |
   +--> direct deterministic merge
   |
   +--> curator agent plan -> deterministic merge
   |
   v
alarm_rule_knowledge.md
alarm_rule_knowledge.json
alarm_rule_knowledge_index.json
sme_review_evidence.csv
master_rules_with_ids.csv
coverage_report.md
sibling_conflict_report.md
```

The build also carries lightweight suffix graph context. Batches are processed
from broad to specific, accepted ancestor summaries are injected into child
distillation, deterministic virtual ancestor summaries are included when parent
suffixes were not emitted as their own batches, validation failures can retry
with prior critique, and sibling conflicts are reported deterministically after
merge.

## Batch Strategy

The pipeline is still suffix-first because alarm rules usually end with the
event/action phrase:

```text
SYSTEM-SUBSYSTEM-COMPONENT-...-EVENT-TYPE
```

Useful suffixes include examples like:

- FAIL
- TRIP
- NOT-CONNECTED
- BATTERY-VOLTAGE-ALARM
- GOOSE-QUALITY-BIT

But the system should not treat suffix as the only knowledge signal. Each batch
now includes structural context from the full rule strings so the distiller can
learn patterns such as:

```text
PROTECTION + BATTERY + VOLTAGE -> possible escalation
UPS/DC-SYSTEM + BATTERY-VOLTAGE-ALARM -> often diagnostic monitoring
LOW-VOLTAGE-ALARM structural neighbor -> useful high-severity comparison
```

The distinction is:

```text
batch records:
  rules that share the selected suffix pattern

structural context:
  repeated prefixes, repeated phrases, tokens, severity contrast, and similar
  rules from outside the batch
```

## Batch Profiles

The pipeline supports two batch profiles.

### Detailed Profile

This profile is close to the original behavior. It produces more, smaller
suffix batches.

```text
max_depth: 3
min_support: 3
pure_threshold: 0.9
min_split_support: 0
min_information_gain: 0.0
min_child_coverage: 0.0
```

### Quality Profile

This profile is recommended for higher-quality knowledge-base builds. It
produces fewer, broader batches and only splits suffix groups when the split is
statistically useful.

```text
max_depth: 5
min_support: 10
pure_threshold: 0.85
max_batch_support: 150
min_split_support: 30
min_information_gain: 0.08
min_child_coverage: 0.70
```

Meaning:

- `min_support`: a final emitted batch must have at least this many records
- `pure_threshold`: if a group is this pure, keep it as a batch
- `max_batch_support`: force very large broad groups to split when supported
  child suffixes exist
- `min_split_support`: do not split a parent group unless the parent has enough
  records
- `min_information_gain`: split only when child groups improve severity
  separation enough
- `min_child_coverage`: split only when supported child groups cover enough of
  the parent
- `max_depth`: do not split beyond this suffix-token depth

The current batch boundary is still suffix-based. Structural context helps the
agent reason beyond suffix, but records inside a batch are still selected by
suffix. A future improvement could add true `structural_cluster` batches across
suffixes.

## Evidence Batch Contents

Each evidence batch contains:

```text
batch_id
pattern_type
pattern
support
severity_distribution
dominant_severity
purity
entropy
examples
counterexamples
structural_context
```

`structural_context` includes:

- common prefixes
- common suffixes
- common contiguous phrases
- common tokens
- severity-specific contrast
- child suffix distributions
- contrastive severity signals with support, purity, and lift
- cross-batch structural neighbors

This prevents the distiller from producing only a suffix/statistics summary.
For low-support or low-purity batches, the agent should explicitly treat the
suffix as weak evidence and explain the structural uncertainty.

For broad low-purity suffixes such as `ALARM`, the agent should treat the suffix
as a container/taxonomy rather than a standalone severity rule. The useful
knowledge should come from child suffixes, internal phrases, high-signal tokens,
and exception patterns.

Mixed batches include deterministic contrastive feature mining. The builder
counts tokens and contiguous phrases by severity and exposes only count-backed
signals, such as:

```text
PRIMARY-MASTER -> Diagnostic, support=N, purity=P
MULTIMEDIA-MESSAGING-SERVICE -> Medium, support=N, purity=P
```

The distiller should use those signals to write severity split logic, while the
critic checks that claims are supported by evidence counts.

`max_batch_support` is enforced as a hard cap on emitted LLM batches. If a
large group cannot be split further by suffix, the builder emits deterministic
`suffix_part` mini-batches ordered by structural suffix. These overflow parts
prevent one large mixed call while keeping all source rules traceable in the SME
review CSV.

## Agent Organization

Each agent is organized as a skill plus tools:

```text
agents/<agent_name>/
  skill.md
  prompt.md
  tools.py
  agent.py
```

At runtime, each ADK agent instruction is composed from:

```text
skill.md
+ prompts/shared_guardrails.md
+ prompt.md
```

This makes the skill file operational, not just documentation.

## Agent 1: Batch Distiller

Purpose:

Distill one evidence batch into one Markdown knowledge fragment.

Inputs:

- evidence batch JSON
- severity distribution
- purity and entropy
- representative examples
- counterexamples
- structural context
- cross-batch structural neighbors

Output:

- one Markdown fragment with YAML frontmatter

Guardrails:

- Preserve support, purity, entropy, and severity distribution exactly.
- Preserve the dominant severity as `default_severity`.
- Separate observed evidence from inferred logic.
- Do not use absolute language unless purity is exactly `1.0`.
- Include exceptions when the batch is mixed.
- Mention High/Critical counterexamples explicitly.
- Explain whether the useful signal comes from suffix, full-rule structure, or
  both.

## Agent 2: Critic

Purpose:

Audit a generated fragment against the source evidence and deterministic
validation findings.

Inputs:

- source evidence batch
- generated Markdown fragment
- validation findings

Output:

- critique report only

Guardrails:

- Does not rewrite the final knowledge directly.
- Flags unsupported claims.
- Flags missing exceptions.
- Flags unsafe absolute language.
- Flags missing High/Critical minority cases.
- Classifies issues as blocking, warning, or note.

The critic is triggered when deterministic validation sees risk:

- missing required metadata
- metadata does not match source evidence
- unsupported absolute language
- low purity
- high support but mixed severity
- High/Critical appears as a minority exception

## Agent 3: Curator

Purpose:

Optionally improve organization across validated fragments before final merge.

Inputs:

- validated fragments
- fragment metadata
- duplicate/conflict context

Output:

- curator JSON plan

Guardrails:

- Cannot change severity labels.
- Cannot change support, purity, entropy, or distributions.
- Cannot silently resolve conflicts.
- Leaves final writing to the deterministic merger.

The main pipeline supports:

```bash
--curation-mode direct
--curation-mode agent
```

In direct mode, validated fragments go straight to the deterministic merger. In
agent mode, the curator suggests ordering and notes, then the deterministic
merger applies what it can safely apply.

## Deterministic Components

The shared tools layer owns factual operations:

- load rules CSV
- tokenize alarm rules
- build suffix groups
- compute severity distributions
- compute entropy and purity
- compute information gain
- decide whether a suffix split is worthwhile
- select representative examples
- select counterexamples
- compute structural context
- compute cross-batch structural neighbors
- validate knowledge fragments
- normalize LLM Markdown output
- detect absolute language
- collect and sort fragments
- build final Markdown knowledge base
- build JSON lookup index
- append progress records for resumable runs

## Markdown Fragment Contract

Each distiller output must start with YAML frontmatter:

```markdown
---
batch_id: suffix__BATTERY-VOLTAGE-ALARM
pattern_type: suffix
pattern: BATTERY-VOLTAGE-ALARM
default_severity: Diagnostic
support: 3
purity: 0.6667
entropy: 0.9183
confidence: Low
---

## Pattern: BATTERY-VOLTAGE-ALARM

### Observed Evidence

...

### Core Logic

...

### Structural Context

...

### Escalation Conditions

...

### Exceptions

...

### Representative Examples

...
```

The validator rejects fragments when required frontmatter fields are missing or
do not match the evidence batch.

## Resume And Rerun Behavior

LLM/API calls can fail partway through a large run. The pipeline is designed to
resume using the same work directory.

Use:

```bash
--resume
```

When resume is enabled, the pipeline checks whether the fragment for a batch
already exists and still validates against the current evidence batch. If it
does, the batch is skipped. If not, it is regenerated.

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

Important: if the evidence schema or batch profile changes, old fragments may
not validate against the new evidence. In that case the pipeline will regenerate
them rather than silently reusing stale knowledge.

## Plan-Only Mode

To estimate batch count without making LLM calls:

```bash
python -m knowledge_builder.pipeline.run_build_kb \
  --master master_rules.csv \
  --out knowledge_base/alarm_rule_knowledge.md \
  --work-dir knowledge_base/work_quality \
  --batch-profile quality \
  --plan-only
```

This writes evidence batches and returns the count, but does not call the
distiller agent.

## Recommended Build Commands

Quality-profile ADK build with resumability:

```bash
PYTHONPATH=/Users/yichenzhou/Documents/GitHub/RAG/knowledge_agent \
python -m knowledge_builder.pipeline.run_build_kb \
  --master master_rules.csv \
  --out knowledge_base/alarm_rule_knowledge.md \
  --work-dir knowledge_base/work_quality \
  --batch-profile quality \
  --distill-mode adk \
  --critic-mode adk \
  --curation-mode direct \
  --resume
```

Optional curator-assisted merge:

```bash
PYTHONPATH=/Users/yichenzhou/Documents/GitHub/RAG/knowledge_agent \
python -m knowledge_builder.pipeline.run_build_kb \
  --master master_rules.csv \
  --out knowledge_base/alarm_rule_knowledge.md \
  --work-dir knowledge_base/work_quality \
  --batch-profile quality \
  --distill-mode adk \
  --critic-mode adk \
  --curation-mode agent \
  --resume
```

Template mode for local testing without ADK:

```bash
PYTHONPATH=/Users/yichenzhou/Documents/GitHub/RAG/knowledge_agent \
python -m knowledge_builder.pipeline.run_build_kb \
  --master master_rules.csv \
  --out /tmp/alarm_rule_knowledge.md \
  --batch-profile quality \
  --distill-mode template \
  --curation-mode direct
```

## Final Knowledge Base Shape

The final user-facing output set is:

```text
knowledge_base/
  alarm_rule_knowledge.md
  alarm_rule_knowledge.json
  alarm_rule_knowledge_index.json
  sme_review_evidence.csv
  master_rules_with_ids.csv
  coverage_report.md
  sibling_conflict_report.md
```

`alarm_rule_knowledge.md` is the agent-facing reasoning file. It contains:

- prediction checklist
- distilled pattern sections
- observed evidence
- core logic
- severity split logic
- structural context
- escalation conditions
- exceptions
- representative examples

`alarm_rule_knowledge_index.json` lets a future prediction service retrieve
relevant sections by suffix or pattern without parsing the full Markdown file.

`alarm_rule_knowledge.json` is the structured agent-facing version. Each AI rule
contains:

- `classification_mode`
- `do_not_use_suffix_alone`
- `batch_summary`
- `core_finding`
- `severity_split_logic`
- `fallback_logic`
- examples, exceptions, and SME review questions

`sme_review_evidence.csv` is the human review dashboard. It is long format:

```text
one row = one AI rule + one original source rule evidence row
```

Evidence roles:

- `representative`: in-batch source rule whose severity agrees with the AI
  default severity
- `exception`: in-batch source rule whose severity does not agree with the AI
  default severity
- `structural_neighbor`: out-of-batch source rule that is structurally similar
  and useful review context

`master_rules_with_ids.csv` assigns stable source IDs to the original
`Rule, Severity` rows. `coverage_report.md` summarizes total rules, AI rules,
coverage, low-confidence rules, and High/Critical exceptions.
`sibling_conflict_report.md` flags default-severity conflicts between sibling
or parent/child batches for SME or engineering review.

## Known Limitation And Next Improvement

The current batch boundary is still suffix-based. Structural context and
neighbors help reduce suffix tunnel vision, but they do not fully replace a true
structural clustering phase.

Recommended next improvement:

```text
hybrid batch builder:
  1. suffix_quality batches
  2. structural_phrase batches
  3. severity_exception batches
```

That would let the knowledge base learn patterns that cut across suffixes, such
as protection-related escalation, power-delivery escalation, or component-level
severity rules.
