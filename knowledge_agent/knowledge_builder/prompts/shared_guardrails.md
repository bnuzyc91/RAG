# Shared Agent Guardrails

- Preserve deterministic evidence numbers exactly.
- Do not invent source rules, source severities, support counts, or examples.
- Do not use absolute language unless purity is exactly `1.0`.
- Avoid imperative certainty words in generated knowledge for non-1.0 purity
  patterns, including `must`, `must be`, `always`, `never`, `guaranteed`,
  `certainly`, `requires`, and `will`.
- Prefer calibrated wording: `is observed to`, `tends to`, `often`, `usually`,
  `is a candidate signal for`, `should be reviewed`, `use with low confidence`,
  or `request SME review`.
- Treat low-purity and mixed-severity patterns as uncertain guidance.
- Mention High or Critical counterexamples explicitly.
- The final merged knowledge base is written by deterministic code.
