package com.example.alarm.knowledge;

import com.example.alarm.RuleTokenizer;
import com.example.alarm.SeverityVote;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * Predicts alarm severity from the distilled AI rules in a KnowledgeBase.
 *
 * Emits SeverityVote objects in the same format as AlarmSeverityPredictor so
 * both vote sets can be merged by the same weighted-vote aggregation.
 *
 * Prediction flow:
 *   1. Tokenize input rule.
 *   2. Walk suffixes longest-first; look up candidate AI rules.
 *   3. Scan all input n-grams for split-signal feature matches.
 *   4. Dispatch on classificationMode to emit votes.
 */
public final class KnowledgeBasedSeverityPredictor {
    private static final double WEIGHT_SPLIT_SIGNAL   = 1.5;
    private static final double WEIGHT_SIMPLE_DEFAULT = 1.2;
    private static final double WEIGHT_FALLBACK       = 0.6;
    private static final double WEIGHT_WEAK_DEFAULT   = 0.5;

    private final KnowledgeBase kb;

    public KnowledgeBasedSeverityPredictor(KnowledgeBase kb) {
        this.kb = kb;
    }

    /**
     * Returns knowledge-based SeverityVotes for the given alarm rule string.
     * Returns an empty list when no AI rule matches.
     */
    public List<SeverityVote> votes(String rule) {
        List<String> tokens = RuleTokenizer.tokenize(rule);
        if (tokens.isEmpty()) return Collections.emptyList();

        List<SeverityVote> votes = new ArrayList<>();
        Set<String> seenRuleIds = new HashSet<>();

        AiRule suffixMatch = longestSuffixMatch(tokens);
        List<SignalHit> signalHits = findSignalHits(tokens);

        // Collect candidate AI rules: suffix match first, then signal-hit rules
        List<AiRule> candidates = new ArrayList<>();
        if (suffixMatch != null) {
            candidates.add(suffixMatch);
        }
        for (SignalHit hit : signalHits) {
            if (!seenRuleIds.contains(hit.getRule().getAiRuleId())) {
                candidates.add(hit.getRule());
            }
        }

        for (AiRule candidate : candidates) {
            if (!seenRuleIds.add(candidate.getAiRuleId())) continue;

            List<SignalHit> matchingSignals = new ArrayList<>();
            for (SignalHit hit : signalHits) {
                if (hit.getRule().getAiRuleId().equals(candidate.getAiRuleId())) {
                    matchingSignals.add(hit);
                }
            }

            boolean isSuffixCandidate = suffixMatch != null
                    && suffixMatch.getAiRuleId().equals(candidate.getAiRuleId());
            emitVotes(candidate, matchingSignals, isSuffixCandidate, votes);
        }

        return Collections.unmodifiableList(votes);
    }

    // ---- Step 2: suffix lookup ----

    private AiRule longestSuffixMatch(List<String> tokens) {
        for (int start = 0; start < tokens.size(); start++) {
            List<String> suffix = tokens.subList(start, tokens.size());
            AiRule exact = kb.getByExactPattern(suffix);
            if (exact != null) return exact;
            List<AiRule> candidates = kb.getBySuffix(suffix);
            if (!candidates.isEmpty()) return longestPatternRule(candidates);
        }
        return null;
    }

    private static AiRule longestPatternRule(List<AiRule> rules) {
        AiRule best = null;
        for (AiRule r : rules) {
            if (best == null || r.getPatternTokens().size() > best.getPatternTokens().size()) {
                best = r;
            }
        }
        return best;
    }

    // ---- Step 3: signal feature scan ----

    private List<SignalHit> findSignalHits(List<String> tokens) {
        List<SignalHit> hits = new ArrayList<>();
        for (int len = 1; len <= tokens.size(); len++) {
            for (int start = 0; start <= tokens.size() - len; start++) {
                List<String> ngram = tokens.subList(start, start + len);
                List<AiRule> candidates = kb.getBySignalFeature(ngram);
                for (AiRule candidate : candidates) {
                    for (SeveritySplitSignal signal : candidate.getSeveritySplitLogic()) {
                        if (signal.getFeatureTokens().equals(ngram)) {
                            hits.add(new SignalHit(candidate, signal));
                        }
                    }
                }
            }
        }
        return hits;
    }

    // ---- Step 4–6: emit votes ----

    private void emitVotes(
            AiRule candidate,
            List<SignalHit> signalHits,
            boolean isSuffixCandidate,
            List<SeverityVote> out
    ) {
        String mode = candidate.getClassificationMode();
        if (mode == null) return;

        if ("simple_default".equals(mode)) {
            if (isSuffixCandidate && !candidate.isDoNotUseSuffixAlone()) {
                double purity = candidate.getBatchSummary().getPurity();
                out.add(new SeverityVote(
                        candidate.getDefaultSeverity(),
                        purity,
                        WEIGHT_SIMPLE_DEFAULT * purity,
                        "KB_SIMPLE_DEFAULT",
                        evidence(candidate, null)
                ));
            }

        } else if ("conditional_split".equals(mode)) {
            if (!signalHits.isEmpty()) {
                SignalHit best = bestSignal(signalHits);
                out.add(new SeverityVote(
                        best.getSignal().getPredictsSeverity(),
                        best.getSignal().getPurity(),
                        WEIGHT_SPLIT_SIGNAL,
                        "KB_SPLIT_SIGNAL",
                        evidence(candidate, best.getSignal())
                ));
            } else if (isSuffixCandidate) {
                FallbackLogic fallback = candidate.getFallbackLogic();
                if (fallback != null && fallback.getSeverity() != null) {
                    out.add(new SeverityVote(
                            fallback.getSeverity(),
                            confidenceToDouble(fallback.getConfidence()),
                            WEIGHT_FALLBACK,
                            "KB_FALLBACK",
                            evidence(candidate, null) + " (no split signal matched; fallback)"
                    ));
                }
            }

        } else if ("taxonomy_container".equals(mode)) {
            // Never emit a suffix-only vote; only emit when a split signal fires
            for (SignalHit hit : signalHits) {
                out.add(new SeverityVote(
                        hit.getSignal().getPredictsSeverity(),
                        hit.getSignal().getPurity(),
                        WEIGHT_SPLIT_SIGNAL,
                        "KB_SPLIT_SIGNAL",
                        evidence(candidate, hit.getSignal())
                ));
            }

        } else if ("weak_default".equals(mode)) {
            if (isSuffixCandidate && candidate.getDefaultSeverity() != null) {
                double purity = candidate.getBatchSummary().getPurity();
                out.add(new SeverityVote(
                        candidate.getDefaultSeverity(),
                        purity,
                        WEIGHT_WEAK_DEFAULT,
                        "KB_WEAK_DEFAULT",
                        evidence(candidate, null) + " (weak evidence; review recommended)"
                ));
            }
        }
    }

    private static SignalHit bestSignal(List<SignalHit> hits) {
        SignalHit best = hits.get(0);
        for (SignalHit hit : hits) {
            double score = hit.getSignal().getLift() * hit.getSignal().getPurity();
            double bestScore = best.getSignal().getLift() * best.getSignal().getPurity();
            if (score > bestScore) best = hit;
        }
        return best;
    }

    private static String evidence(AiRule rule, SeveritySplitSignal signal) {
        StringBuilder sb = new StringBuilder();
        sb.append("aiRuleId=").append(rule.getAiRuleId());
        sb.append(" pattern=").append(rule.getPattern());
        sb.append(" mode=").append(rule.getClassificationMode());
        sb.append(String.format(" purity=%.2f", rule.getBatchSummary().getPurity()));
        sb.append(" support=").append(rule.getBatchSummary().getSupport());
        if (signal != null) {
            sb.append(" signal='").append(signal.getCondition()).append("'");
            sb.append(String.format(" signalPurity=%.2f", signal.getPurity()));
            sb.append(String.format(" lift=%.2f", signal.getLift()));
        }
        return sb.toString();
    }

    private static double confidenceToDouble(String confidence) {
        if (confidence == null) return 0.5;
        switch (confidence.toLowerCase()) {
            case "high":   return 0.85;
            case "medium": return 0.60;
            case "low":    return 0.35;
            default:       return 0.50;
        }
    }

    // ---- inner types ----

    private static final class SignalHit {
        private final AiRule rule;
        private final SeveritySplitSignal signal;

        SignalHit(AiRule rule, SeveritySplitSignal signal) {
            this.rule = rule;
            this.signal = signal;
        }

        AiRule getRule() { return rule; }
        SeveritySplitSignal getSignal() { return signal; }
    }
}
