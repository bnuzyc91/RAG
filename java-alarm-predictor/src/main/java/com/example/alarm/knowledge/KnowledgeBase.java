package com.example.alarm.knowledge;

import com.example.alarm.RuleTokenizer;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Immutable runtime knowledge base built once at startup from alarm_rule_knowledge.json.
 *
 * Three indexes allow O(depth) lookups instead of scanning all AI rules per prediction:
 *   byPattern       — exact normalized pattern string → AiRule
 *   bySuffix        — any suffix of any pattern → candidate AiRules
 *   bySignalFeature — split-signal feature string → AiRules that declare it
 */
public final class KnowledgeBase {
    private final List<AiRule> rules;
    private final Map<String, AiRule> byAiRuleId;
    private final Map<String, AiRule> byPattern;
    private final Map<String, List<AiRule>> bySuffix;
    private final Map<String, List<AiRule>> bySignalFeature;

    public KnowledgeBase(List<AiRule> rules) {
        this.rules = Collections.unmodifiableList(new ArrayList<>(rules));

        Map<String, AiRule> idIndex = new HashMap<>();
        Map<String, AiRule> patternIndex = new HashMap<>();
        Map<String, List<AiRule>> suffixIndex = new HashMap<>();
        Map<String, List<AiRule>> signalIndex = new HashMap<>();

        for (AiRule rule : rules) {
            idIndex.put(rule.getAiRuleId(), rule);
            patternIndex.put(normalizedPattern(rule.getPatternTokens()), rule);
            buildSuffixEntries(rule, suffixIndex);
            buildSignalEntries(rule, signalIndex);
        }

        this.byAiRuleId = Collections.unmodifiableMap(idIndex);
        this.byPattern = Collections.unmodifiableMap(patternIndex);
        this.bySuffix = Collections.unmodifiableMap(suffixIndex);
        this.bySignalFeature = Collections.unmodifiableMap(signalIndex);
    }

    /** Every suffix of the pattern (including the full pattern) maps to this AI rule. */
    private static void buildSuffixEntries(AiRule rule, Map<String, List<AiRule>> index) {
        List<String> tokens = rule.getPatternTokens();
        for (int start = 0; start < tokens.size(); start++) {
            String key = RuleTokenizer.joinTokens(tokens.subList(start, tokens.size()));
            index.computeIfAbsent(key, ignored -> new ArrayList<>()).add(rule);
        }
    }

    /** Each split-signal feature maps to the AI rule that declares it. */
    private static void buildSignalEntries(AiRule rule, Map<String, List<AiRule>> index) {
        for (SeveritySplitSignal signal : rule.getSeveritySplitLogic()) {
            String key = normalizedPattern(signal.getFeatureTokens());
            index.computeIfAbsent(key, ignored -> new ArrayList<>()).add(rule);
        }
    }

    private static String normalizedPattern(List<String> tokens) {
        return RuleTokenizer.joinTokens(tokens);
    }

    public List<AiRule> getRules() { return rules; }

    public AiRule getByAiRuleId(String id) { return byAiRuleId.get(id); }

    /**
     * Returns the AI rule whose pattern exactly matches the joined token list,
     * or null if none.
     */
    public AiRule getByExactPattern(List<String> tokens) {
        return byPattern.get(normalizedPattern(tokens));
    }

    /**
     * Returns AI rules that include this suffix in their pattern, or empty list.
     * Callers should try from longest suffix to shortest and stop at first hit.
     */
    public List<AiRule> getBySuffix(List<String> suffixTokens) {
        List<AiRule> found = bySuffix.get(normalizedPattern(suffixTokens));
        return found != null ? Collections.unmodifiableList(found) : Collections.emptyList();
    }

    /**
     * Returns AI rules that declare a split-signal whose feature matches these tokens,
     * or empty list.
     */
    public List<AiRule> getBySignalFeature(List<String> featureTokens) {
        List<AiRule> found = bySignalFeature.get(normalizedPattern(featureTokens));
        return found != null ? Collections.unmodifiableList(found) : Collections.emptyList();
    }

    public int size() { return rules.size(); }
}
