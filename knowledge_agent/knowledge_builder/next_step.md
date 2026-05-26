# KB Prediction: Implementation Notes

This file documents how `alarm_rule_knowledge.json` is consumed at prediction
time by the Java knowledge-based predictor. The build phase is handled by this
Python pipeline. The prediction phase lives in
`java-alarm-predictor/src/main/java/com/example/alarm/knowledge/`.

---

## Core Principle

Do not scan the full 1.3 MB JSON per prediction. Load it once at startup,
build three in-memory indexes, then query those indexes cheaply per call.

```
startup
  AlarmKnowledgeLoader.load(path)  ← reads JSON once
  builds KnowledgeBase with 3 indexes
  KnowledgeBasedSeverityPredictor wraps it

per prediction
  tokenize input rule
  suffix index lookup   → candidate AI rules
  n-gram scan           → signal feature hits
  classify + emit votes
```

The `KnowledgeBase` object is immutable after construction. Nothing reads the
file again at runtime.

---

## Three Indexes Built at Startup

### 1. Pattern index (`byPattern`)

Exact normalized pattern string → the single `AiRule` that owns it.

```
BUILDING-TRIP  →  alarm-rule-0002
CURRENT-ALARM  →  alarm-rule-0003
```

Checked first when a suffix of the input exactly matches a learned pattern.

### 2. Suffix index (`bySuffix`)

Every suffix of every pattern → list of candidate `AiRule` objects.

For `CURRENT-ALARM` (tokens `[CURRENT, ALARM]`):

```
CURRENT-ALARM  →  [alarm-rule-0003]
ALARM          →  [alarm-rule-0003, ...]
```

This lets a long input rule (`UNIT-GROUND-CURRENT-ALARM`) find the right AI
rule by walking its own suffixes from longest to shortest.

### 3. Signal feature index (`bySignalFeature`)

Each split-signal `feature` from `severity_split_logic` → the `AiRule` that
declares it.

```
GROUND-CURRENT-ALARM  →  [alarm-rule-0003]
BATTERY-CHARGER-HIGH  →  [alarm-rule-0003]
```

Enables signal detection even when the matching suffix is a broad container
like `ALARM` that is marked `do_not_use_suffix_alone: true`.

All three indexes are built in a single pass over `ai_rules` at load time.
Pattern tokens and signal feature tokens are pre-tokenized during loading so
`RuleTokenizer` is never called on the same string twice.

---

## Prediction Flow

### Step 1 — Tokenize

```java
List<String> tokens = RuleTokenizer.tokenize(newRule);
// "UNIT-GROUND-CURRENT-ALARM" → [UNIT, GROUND, CURRENT, ALARM]
```

Uses the same tokenizer as the build pipeline: uppercase, split on `-`,
canonical singular normalization.

### Step 2 — Suffix lookup (longest first)

Walk suffixes of the tokenized input from longest to shortest. For each
suffix, check the pattern index first (exact match wins), then the suffix
index (first hit, longest AI rule pattern wins).

```
[UNIT, GROUND, CURRENT, ALARM]  → no match
[GROUND, CURRENT, ALARM]        → no match
[CURRENT, ALARM]                → alarm-rule-0003  ← stopped here
```

Result is the `suffixMatch` AI rule (may be null for unknown patterns).

### Step 3 — Signal feature scan

Enumerate every contiguous n-gram of the input tokens. For each n-gram, query
the signal feature index.

```
[UNIT]                      → no hit
[GROUND]                    → no hit
[CURRENT]                   → no hit
[ALARM]                     → no hit
[UNIT, GROUND]              → no hit
[GROUND, CURRENT]           → no hit
[CURRENT, ALARM]            → no hit
[UNIT, GROUND, CURRENT]     → no hit
[GROUND, CURRENT, ALARM]    → alarm-rule-0003, signal GROUND-CURRENT-ALARM → High
[UNIT, GROUND, CURRENT, ALARM] → no hit
```

Result is a list of `SignalHit` pairs `(AiRule, SeveritySplitSignal)`.

### Step 4 — Classify and emit `SeverityVote`

Dispatch on `classification_mode` for each candidate AI rule.

#### `simple_default` + `doNotUseSuffixAlone: false`

Emit a direct vote for `default_severity` weighted by purity.

```
severity   = defaultSeverity
confidence = batchSummary.purity
weight     = 1.2 × purity
method     = KB_SIMPLE_DEFAULT
```

Example: `MEGA-CENTRAL-UTILITY-BUILDING-TRIP` → suffix matches `BUILDING-TRIP`
(alarm-rule-0002, purity 0.9) → vote `High` at confidence 0.90.

#### `conditional_split` or `doNotUseSuffixAlone: true`

Never vote on the suffix alone.

If a split signal fired in Step 3, pick the signal with the highest
`lift × purity` and vote for its `predicts_severity`:

```
severity   = signal.predictsSeverity
confidence = signal.purity
weight     = 1.5
method     = KB_SPLIT_SIGNAL
```

If no signal fired but the suffix matched, emit a fallback vote:

```
severity   = fallbackLogic.severity
confidence = Low (0.35)
weight     = 0.6
method     = KB_FALLBACK
```

Example: `UNIT-GROUND-CURRENT-ALARM` → suffix matches `CURRENT-ALARM`
(conditional_split), signal `GROUND-CURRENT-ALARM` fires → vote `High` at
signal purity 0.90, weight 1.5.

Example: `UNKNOWN-SUBSYSTEM-CURRENT-ALARM` → suffix matches `CURRENT-ALARM`
(conditional_split), no signal fires → fallback `High` at confidence 0.35.

#### `taxonomy_container`

Suppress the suffix vote entirely. Emit split-signal votes only.

Broad patterns like `ALARM`, `FAIL`, `STATUS` are marked taxonomy containers
because their severity distribution is too mixed to use the suffix alone. The
signal feature index still reaches them when an internal phrase fires.

#### `weak_default`

Emit a low-weight vote (`KB_WEAK_DEFAULT`, weight 0.5). Flag for review.

### Step 5 — Vote weight table

| Method | Weight | When |
|---|---|---|
| `KB_SPLIT_SIGNAL` | 1.5 | Explicit count-backed signal matched |
| `KB_SIMPLE_DEFAULT` | 1.2 × purity | Stable pattern, suffix safe to use directly |
| `KB_FALLBACK` | 0.6 | Conditional pattern, no signal matched |
| `KB_WEAK_DEFAULT` | 0.5 | Low-evidence pattern |

### Step 6 — Evidence string on each vote

Every `SeverityVote` carries a traceable evidence string:

```
aiRuleId=alarm-rule-0003 pattern=CURRENT-ALARM mode=conditional_split
purity=0.56 support=16 signal='contains GROUND-CURRENT-ALARM'
signalPurity=0.90 lift=1.60
```

---

## How This Differs From the Deterministic Java Predictor

The existing `AlarmSeverityPredictor` asks:

> Which raw master rules look most similar to this input string?

It builds a prefix trie, suffix trie, and exact-suffix index over every
individual `MasterRule` (N ≈ 10K+ rows), then runs a weighted vote across
five structural-similarity signals: `PREFIX_TRIE`, `SUFFIX_TRIE`,
`EXACT_SUFFIX_CHAIN`, `EMBEDDED_PHRASE`, `STRUCTURAL_NEIGHBORS`.

The knowledge-based predictor asks:

> What did the build pipeline learn about this pattern class — its dominant
> severity, its split conditions, and its exceptions?

It indexes ~200 distilled AI rules instead of N raw rules. Key differences:

| | `AlarmSeverityPredictor` | `KnowledgeBasedSeverityPredictor` |
|---|---|---|
| Knowledge unit | Raw `MasterRule` (N rows) | Distilled `AiRule` (~200 rules) |
| Suffix match cost | O(depth) trie, but neighbor scan is O(N) | O(depth) index lookup |
| Ambiguity model | Implicit: conflicting raw-rule votes cancel | Explicit: `conditional_split` with count-backed signals |
| Mixed pattern | `CURRENT-ALARM` → highest raw-rule vote wins | `CURRENT-ALARM` → suffix blocked; inspect internal tokens |
| Explainability | "matched last 3 tokens; support=9" | "signal GROUND-CURRENT-ALARM → High; purity=0.90 lift=1.60" |
| Unknown input | Fuzzy similarity to nearest raw rule | Fallback vote + `manual_review_recommended` |
| Uncertainty encoding | Confidence = vote weight ratio | Explicit: purity, entropy, `doNotUseSuffixAlone`, fallback logic |

The critical behavioral difference is on mixed patterns. For `CURRENT-ALARM`:

- Deterministic predictor sees suffix evidence and votes based on majority raw
  labels. It has no way to know the suffix is unreliable.
- Knowledge predictor knows `do_not_use_suffix_alone: true`, suppresses the
  suffix vote, and waits for a split signal. If the signal fires, the
  prediction is both more accurate and more explainable. If it does not fire,
  the fallback vote carries a low weight and confidence that signals uncertainty
  to downstream consumers.

---

## Composing Both Vote Sets

The two predictors emit the same `SeverityVote` type. The existing
`AlarmSeverityPredictor.decide()` method aggregates votes by weighted sum and
is reusable as-is.

Planned hybrid architecture:

```
new alarm rule
  │
  ├── AlarmSeverityPredictor        (raw-rule structural votes)
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
        └── decide()   ← same weighted-vote merger
              │
              └── SeverityPrediction
                    predicted_severity
                    confidence
                    votes (all sources)
                    manual_review_recommended  ← true if votes conflict
```

If both sources agree, confidence rises. If they conflict, set
`manual_review_recommended: true` and surface the disagreement in the evidence
strings.

---

## Startup Usage

```java
KnowledgeBase kb =
    AlarmKnowledgeLoader.load(Path.of("alarm_rule_knowledge.json"));

KnowledgeBasedSeverityPredictor kbPredictor =
    new KnowledgeBasedSeverityPredictor(kb);

// At prediction time
List<SeverityVote> kbVotes = kbPredictor.votes(inputRule);
```

`AlarmKnowledgeLoader` contains a self-contained recursive-descent JSON parser
with no external dependencies. Every pattern and signal feature is
pre-tokenized at load time.

---

## Files

```
java-alarm-predictor/src/main/java/com/example/alarm/knowledge/
  AlarmKnowledgeLoader.java           loads JSON → KnowledgeBase; includes JSON parser
  KnowledgeBase.java                  3 indexes, immutable after construction
  KnowledgeBasedSeverityPredictor.java  prediction logic, emits SeverityVote
  AiRule.java                         parsed AI rule
  BatchSummary.java                   support, purity, entropy, distribution
  SeveritySplitSignal.java            one split-signal row (pre-tokenized)
  FallbackLogic.java                  fallback severity + confidence
  ExampleRule.java                    source_rule_id, rule, severity
```
