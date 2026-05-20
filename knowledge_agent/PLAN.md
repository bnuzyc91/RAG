# Alarm Rule Knowledge Agent Plan

This project is a knowledge-base build pipeline for alarm severity prediction.
The goal is not generic RAG. The goal is to distill the underlying patterns in
existing alarm rules into a durable Markdown knowledge base that can later be
used as reference logic for real-time prediction.

The current deterministic method is valuable because it exposes factual
evidence: suffix matches, prefix matches, support counts, purity, entropy, and
similar examples. The new agentic layer should sit on top of that evidence and
turn it into reusable rule knowledge.

## Core Design

The build phase uses deterministic tools for facts and agents for judgment:

```text
master_rules.csv
   |
   v
Deterministic Evidence Builder
   |
   v
Batch Distiller Agent
   |
   v
Deterministic Validator
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
alarm_rule_knowledge_index.json
```

The final writer is always deterministic. Agents can distill, review, and
curate, but they do not silently change evidence numbers or produce the final
canonical file without deterministic checks.

## Why Batch From Suffix First

Alarm rule strings are usually hyphen-separated hierarchies:

```text
SYSTEM-SUBSYSTEM-COMPONENT-...-EVENT-TYPE
```

The suffix often captures the event/action meaning:

- FAIL
- TRIP
- NOT-CONNECTED
- GOOSE-QUALITY-BIT
- BREAKER

For 10,000 rules, random batching would mix unrelated concepts. Suffix-first
batching creates coherent evidence packets that an agent can summarize well.

Recommended batching strategy:

1. Group by last token.
2. Split broad or mixed groups by last 2 tokens.
3. Continue to last 3-5 tokens when severity remains mixed.
4. Preserve high-support, high-purity suffix groups as strong knowledge.
5. Use prefix/system groupings as secondary evidence when suffix is ambiguous.

## Agent Layout

Each agent is organized as a skill plus tools:

```text
agents/<agent_name>/
  skill.md
  prompt.md
  tools.py
  agent.py
```

The skill explains the agent's responsibility. The tools expose deterministic
functions. The prompt defines the output format and guardrails. The agent file
wires those pieces into Google ADK.

## Agent 1: Batch Distiller

Purpose:

Distill one statistically prepared evidence batch into one Markdown knowledge
fragment.

Inputs:

- evidence batch JSON
- representative examples
- counterexamples
- severity distribution
- purity and entropy

Output:

- one Markdown fragment with YAML frontmatter

Guardrails:

- Preserve support, purity, entropy, and severity distribution exactly.
- Separate observed evidence from inferred logic.
- Do not use "always", "never", or "guaranteed" unless purity is 1.0.
- Include exceptions when the batch is mixed.
- Do not invent severity labels.

## Agent 2: Critic

Purpose:

Audit a generated fragment against the source evidence.

Inputs:

- source evidence batch
- generated Markdown fragment
- deterministic validation findings

Output:

- critique report only

Guardrails:

- Does not rewrite the fragment.
- Flags unsupported claims.
- Flags missing high-severity exceptions.
- Classifies issues as blocking, warning, or note.

The critic is triggered only when the deterministic validator sees risk:

- missing required metadata
- unsupported absolute language
- purity below threshold
- high support but mixed severity
- High/Critical appears as a minority exception

## Agent 3: Curator

Purpose:

Optionally improve organization across validated fragments before final merge.

Inputs:

- validated fragments
- conflict report
- duplicate pattern report

Output:

- curator plan

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
agent mode, the curator creates an organization plan, then the deterministic
merger applies the plan where it can do so safely.

## Deterministic Tools

The shared tools layer owns factual operations:

- load rules CSV
- tokenize alarm rules
- build suffix groups
- compute severity distributions
- compute entropy and purity
- select representative examples
- select counterexamples
- validate knowledge fragments
- detect absolute language
- collect and sort fragments
- build Markdown knowledge base
- build JSON lookup index

## Markdown Fragment Contract

Each distiller output should look like:

```markdown
---
batch_id: suffix__NOT-CONNECTED
pattern_type: suffix
pattern: NOT-CONNECTED
default_severity: Diagnostic
support: 184
purity: 0.82
entropy: 0.81
confidence: Medium
---

## Pattern: NOT-CONNECTED

### Observed Evidence

...

### Core Logic

...

### Escalation Conditions

...

### Exceptions

...
```

## Final Knowledge Base Shape

The merged knowledge base should contain:

- Severity philosophy
- Strong suffix patterns
- Mixed suffix patterns
- Prefix/system patterns
- Component-specific patterns
- Escalation rules
- Exceptions and conflicts
- Low-confidence areas
- Prediction checklist

The merged JSON index lets a future prediction service retrieve relevant
sections by suffix, prefix, or pattern without parsing the full Markdown file.

## Current Sample Code

This folder contains a working deterministic scaffold plus ADK agent wrappers.
The deterministic mode is useful for local testing before Gemini credentials and
the final ADK runtime choices are configured.

Example direct build:

```bash
python -m knowledge_builder.pipeline.run_build_kb \
  --master master_rules.csv \
  --out knowledge_base/alarm_rule_knowledge.md \
  --distill-mode template \
  --curation-mode direct
```

Example ADK distillation build:

```bash
python -m knowledge_builder.pipeline.run_build_kb \
  --master master_rules.csv \
  --out knowledge_base/alarm_rule_knowledge.md \
  --distill-mode adk \
  --curation-mode agent
```

