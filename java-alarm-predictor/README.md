# Java Alarm Severity Predictor

Pure Java implementation for backend severity prediction from master alarm rules.

## Main API

```java
List<MasterRule> masterRules = List.of(
    new MasterRule("NOT-CONNECTED-VIA-TIE-BREAKERS", "Diagnostic")
);

AlarmSeverityPredictor predictor = new AlarmSeverityPredictor(masterRules);

SeverityPrediction prediction = predictor.predict(
    "SESSION-STORAGE-SERVICE-AND-ISOLATED-REDUNDANT-TIE-NOT-CONNECTED-VIA-TIE-BREAKER"
);

String severity = prediction.getPredictedSeverity();
double confidence = prediction.getConfidence();
List<SimilarRule> similarRules = prediction.getSimilarRules();
List<SeverityVote> votes = prediction.getVotes();
```

## Methods Used

- Prefix trie: longest matching start of rule.
- Suffix trie: longest matching end of rule.
- Exact suffix chain: `a-b-c-d-e`, then `b-c-d-e`, `c-d-e`, `d-e`, `e`.
- Canonical token normalization: handles cases like `BREAKERS -> BREAKER`.
- Embedded phrase matching: finds master phrases inside longer new rules.
- Fuzzy suffix phrase matching: allows small structural differences in the end phrase.
- Structural neighbors: scores similar rules by longest common contiguous block, prefix, suffix, and ordered token overlap.

## Notes

The tokenizer intentionally does not blindly remove every trailing `S`; words such as `BUS`, `GAS`, `STATUS`, and `BYPASS` are preserved.
