# KB Prediction: Implementation Notes

This file documents how `alarm_rule_knowledge.json` is consumed at prediction
time by the Java knowledge-based predictor. The build phase is handled by this
Python pipeline. The prediction phase lives in
`java-alarm-predictor/src/main/java/com/example/alarm/knowledge/`.

---

## Core Principle

Do not scan the full 1.3 MB JSON per prediction. Load it once at startup,
build two in-memory indexes, then query those indexes cheaply per call.

```
startup
  AlarmKnowledgeLoader.load(path)  ← reads JSON once
  builds KnowledgeBase with 2 indexes
  KnowledgeBasedSeverityPredictor wraps it

per prediction
  tokenize input rule
  walk suffixes longest-first → exact pattern match → candidate AI rules
  scan signals only inside matched AI rule → signal hits
  classify + emit votes
```

The `KnowledgeBase` object is immutable after construction. Nothing reads the
file again at runtime.

---

## Two Indexes Built at Startup

### 1. Pattern index (`byPattern`)

Exact normalized pattern string → **list** of `AiRule` objects that share it.

```
BUILDING-TRIP  →  [AIRULE-000010 (suffix_part, purity=0.90),
                   AIRULE-000011 (suffix_part, purity=1.00)]
CURRENT-ALARM  →  [AIRULE-000003 (conditional_split)]
```

The value is a list, not a single rule, because large batches are sometimes
deterministically split into `suffix_part` shards by the build pipeline. Both
shards must be evaluated and both emit votes; the downstream vote merger handles
the aggregation. Silently overwriting one shard with the other would lose
evidence.

### 2. Signal feature index (`bySignalFeature`)

Each split-signal `feature` in `severity_split_logic` → the `AiRule` that
declares it.

```
LOW  →  [AIRULE-000003]
```

This index is built at startup and kept for external lookups. The predictor
itself does **not** use this index at call time — it evaluates signals only
inside the already-matched AI rule (see Step 3 below). This avoids
cross-rule signal contamination.

---

## Prediction Flow

### Step 1 — Tokenize

```java
List<String> tokens = RuleTokenizer.tokenize(newRule);
// "SOMETHING-LOW-CURRENT-ALARM" → [SOMETHING, LOW, CURRENT, ALARM]
```

Uses the same tokenizer as the build pipeline: uppercase, split on `-`,
canonical singular normalization.

### Step 2 — Exact pattern match, longest suffix first

Walk suffixes of the tokenized input from longest to shortest. For each
suffix, query the pattern index for an exact match. Stop at the first hit
and return **all** AI rules for that pattern (handles `suffix_part` shards).

```
[SOMETHING, LOW, CURRENT, ALARM]  → no match
[LOW, CURRENT, ALARM]             → no match
[CURRENT, ALARM]                  → [AIRULE-000003]  ← stop here
```

Only exact matches are accepted. There is no fuzzy suffix fallback at this
level — that role belongs to the existing deterministic `AlarmSeverityPredictor`
which operates on raw master rules.

### Step 3 — Signal scan inside the matched AI rule

For each candidate AI rule from Step 2, iterate its own `severitySplitLogic`
list directly. For each signal, check whether the signal's pre-tokenized
feature tokens appear as a **contiguous subsequence** of the input tokens.

```java
// candidate = AIRULE-000003, signal feature = [LOW]
// input tokens = [SOMETHING, LOW, CURRENT, ALARM]
// [LOW] found at position 1 → hit
```

Signal evaluation is strictly context-bound: only the signals declared by the
matched AI rule are tested. A `LOW` token in the input cannot trigger a signal
from an unrelated AI rule for `BUILDING-TRIP`.

### Step 4 — Classify and emit `SeverityVote`

Dispatch on `classification_mode` for each candidate AI rule.

#### `simple_default` + `doNotUseSuffixAlone: false`

Emit one vote for `default_severity`.

```
severity   = defaultSeverity
confidence = batchSummary.purity
weight     = 1.2  (flat)
method     = KB_SIMPLE_DEFAULT
```

For `suffix_part` shards both rules emit independently. Example:
`CENTRAL-UTILITY-BUILDING-TRIP` → suffix `BUILDING-TRIP` hits two shards →
two `KB_SIMPLE_DEFAULT` votes for `High` (purity 0.90 and 1.00) feed the
merger together.

#### `conditional_split` or `doNotUseSuffixAlone: true`

Never vote on the suffix alone.

If a signal fired in Step 3, pick the signal with the highest
`lift × purity` and emit one vote:

```
severity   = signal.predictsSeverity
confidence = signal.purity
weight     = 1.5
method     = KB_SPLIT_SIGNAL
```

If no signal fired, emit a fallback vote:

```
severity   = fallbackLogic.severity
confidence = Low (0.35)
weight     = 0.6
method     = KB_FALLBACK
```

Example: `SOMETHING-LOW-CURRENT-ALARM` → suffix matches `CURRENT-ALARM`
(conditional_split), `LOW` signal fires → `KB_SPLIT_SIGNAL` High at
signal purity 1.00, weight 1.5.

#### `taxonomy_container`

Suppress the suffix vote entirely. Emit one `KB_SPLIT_SIGNAL` vote per
signal that fired. If no signal fires, emit nothing.

Broad patterns like bare `ALARM` or `FAIL` are taxonomy containers because
their distribution is too mixed to use suffix alone. Only internal signal
evidence is meaningful.

#### `weak_default`

Emit one low-weight vote (`KB_WEAK_DEFAULT`, weight 0.5). Flag for review.

### Step 5 — Vote weight table

| Method | Weight | Confidence source |
|---|---|---|
| `KB_SPLIT_SIGNAL` | 1.5 | `signal.purity` |
| `KB_SIMPLE_DEFAULT` | 1.2 | `batchSummary.purity` |
| `KB_FALLBACK` | 0.6 | hardcoded 0.35 (Low) |
| `KB_WEAK_DEFAULT` | 0.5 | `batchSummary.purity` |

### Step 6 — Evidence string on each vote

Every `SeverityVote` carries a traceable evidence string:

```
aiRuleId=AIRULE-000003 pattern=CURRENT-ALARM mode=conditional_split
purity=0.56 support=16 signal='contains LOW' signalPurity=1.00 lift=1.70
```

---

## Why No Broad Suffix Index

An earlier design built a `bySuffix` index that mapped every sub-suffix of
every pattern to candidate AI rules. This was removed for two reasons:

1. **Noise**: a single-token suffix like `ALARM` returned dozens of candidates
   from unrelated patterns, all of which needed evaluation and produced
   spurious votes.

2. **Redundancy**: the existing `AlarmSeverityPredictor` already covers
   fuzzy and partial-suffix matching over raw master rules. The knowledge
   predictor's job is to add **structured reasoning** on top of exact pattern
   matches, not to duplicate approximate matching.

The result is a stricter but more precise predictor. Unknown suffixes produce
zero knowledge votes; the deterministic predictor's structural votes still
cover those cases.

---

## How This Differs From the Deterministic Java Predictor

The existing `AlarmSeverityPredictor` asks:

> Which raw master rules look most similar to this input string?

It indexes every individual `MasterRule` (N ≈ 10K+ rows) and runs five
structural-similarity signals across them: `PREFIX_TRIE`, `SUFFIX_TRIE`,
`EXACT_SUFFIX_CHAIN`, `EMBEDDED_PHRASE`, `STRUCTURAL_NEIGHBORS`.

The knowledge-based predictor asks:

> What did the build pipeline learn about this pattern class — its dominant
> severity, its split conditions, and its exceptions?

It indexes ~200 distilled AI rules. Key differences:

| | `AlarmSeverityPredictor` | `KnowledgeBasedSeverityPredictor` |
|---|---|---|
| Knowledge unit | Raw `MasterRule` (N rows) | Distilled `AiRule` (~200 rules) |
| Match type | Structural similarity (prefix, suffix, LCS, fuzzy phrase) | Exact suffix-to-pattern only |
| Ambiguity model | Implicit: conflicting raw-rule votes cancel | Explicit: `conditional_split` with named signal conditions |
| Mixed pattern (e.g. `CURRENT-ALARM`) | Suffix evidence → majority label wins | Suffix blocked; internal signal decides; fallback if none |
| `suffix_part` shards | Not aware of shards | Both shards emit votes; merger aggregates |
| No-match behaviour | Fuzzy fallback always finds neighbors | Returns empty; deterministic predictor covers the gap |
| Explainability | "matched last N tokens; support=K" | "signal 'contains LOW' → High; purity=1.00 lift=1.70" |
| Uncertainty encoding | Confidence = weighted vote ratio | Explicit: purity, entropy, `doNotUseSuffixAlone`, fallback |

The critical behavioral difference is on mixed patterns. For `CURRENT-ALARM`
the deterministic predictor sees suffix evidence and votes based on the
majority raw labels — it has no way to know the suffix is unreliable. The
knowledge predictor sets `do_not_use_suffix_alone: true`, suppresses the
suffix vote entirely, and waits for a named signal to fire.

---

## Composing Both Vote Sets

Both predictors emit the same `SeverityVote` type. The existing
`AlarmSeverityPredictor.decide()` method aggregates votes by weighted sum and
is reusable as-is.

Planned hybrid architecture:

```
new alarm rule
  │
  ├── AlarmSeverityPredictor           (raw-rule structural votes)
  │     PREFIX_TRIE
  │     SUFFIX_TRIE
  │     EXACT_SUFFIX_CHAIN
  │     EMBEDDED_PHRASE
  │     STRUCTURAL_NEIGHBORS
  │
  └── KnowledgeBasedSeverityPredictor  (knowledge votes)
        KB_SIMPLE_DEFAULT
        KB_SPLIT_SIGNAL
        KB_FALLBACK
        KB_WEAK_DEFAULT
              │
              └── decide()  ← same weighted-vote merger
                    │
                    └── SeverityPrediction
                          predicted_severity
                          confidence
                          votes  (all sources, all evidence strings)
                          manual_review_recommended
```

When both sources agree, confidence rises. When they conflict, surface
`manual_review_recommended: true` and return the full vote list so the caller
can inspect the disagreement.

---

## Startup Usage

```java
KnowledgeBase kb =
    AlarmKnowledgeLoader.load(Path.of("alarm_rule_knowledge.json"));

KnowledgeBasedSeverityPredictor kbPredictor =
    new KnowledgeBasedSeverityPredictor(kb);

// At prediction time — returns SeverityVote list, never throws on no-match
List<SeverityVote> kbVotes = kbPredictor.votes(inputRule);
```

`AlarmKnowledgeLoader` contains a self-contained recursive-descent JSON parser
(no external dependencies). All pattern tokens and signal feature tokens are
pre-tokenized at load time.

---

## Files

```
java-alarm-predictor/src/main/java/com/example/alarm/knowledge/
  AlarmKnowledgeLoader.java             reads JSON once; self-contained JSON parser
  KnowledgeBase.java                    2 indexes (byPattern, bySignalFeature), immutable
  KnowledgeBasedSeverityPredictor.java  prediction logic; emits SeverityVote
  AiRule.java                           parsed AI rule from json ai_rules[]
  BatchSummary.java                     support, purity, entropy, severity_distribution
  SeveritySplitSignal.java              one split-signal row; pre-tokenized feature
  FallbackLogic.java                    fallback severity + confidence + use_when
  ExampleRule.java                      source_rule_id, rule, severity
```
