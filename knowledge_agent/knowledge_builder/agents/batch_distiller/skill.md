# Skill: Alarm Batch Distillation

## Responsibility

Convert one deterministic evidence batch into one reusable alarm severity
knowledge fragment.

## Inputs

- Evidence batch JSON
- Severity distribution
- Support, purity, entropy
- Representative examples
- Counterexamples

## Output

One Markdown fragment with YAML frontmatter.

## Guardrails

- Preserve `batch_id`, `pattern_type`, `pattern`, `support`, `purity`, and
  `entropy` exactly as provided.
- Preserve the dominant severity as `default_severity`.
- Do not invent severity labels.
- Do not use absolute language unless purity is `1.0`.
- Separate observed evidence from inferred logic.
- Include exceptions when counterexamples are present.

