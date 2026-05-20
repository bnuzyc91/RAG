# Skill: Alarm Knowledge Critique

## Responsibility

Audit a generated knowledge fragment against its source evidence batch.

## Inputs

- Source evidence batch
- Generated Markdown fragment
- Deterministic validation findings

## Output

A critique report only. The critic does not rewrite final knowledge.

## Guardrails

- Flag unsupported claims.
- Flag missing exceptions.
- Flag unsafe absolute language.
- Flag missing High or Critical minority cases.
- Classify each issue as `blocking`, `warning`, or `note`.

