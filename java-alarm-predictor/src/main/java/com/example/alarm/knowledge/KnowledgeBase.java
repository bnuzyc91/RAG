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
 * Indexes allow O(depth) pattern lookup instead of scanning all AI rules per prediction:
 *   byPattern       — exact normalized pattern string → candidate AiRules
 *   bySignalFeature — split-signal feature string → AiRules that declare it
 */
public final class KnowledgeBase {
    private final List<AiRule> rules;
    private final Map<String, AiRule> byAiRuleId;
    private final Map<String, List<AiRule>> byPattern;
    private final Map<String, List<AiRule>> bySignalFeature;

    public KnowledgeBase(List<AiRule> rules) {
        this.rules = Collections.unmodifiableList(new ArrayList<>(rules));

        Map<String, AiRule> idIndex = new HashMap<>();
        Map<String, List<AiRule>> patternIndex = new HashMap<>();
        Map<String, List<AiRule>> signalIndex = new HashMap<>();

        for (AiRule rule : rules) {
            idIndex.put(rule.getAiRuleId(), rule);
            patternIndex.computeIfAbsent(normalizedPattern(rule.getPatternTokens()), ignored -> new ArrayList<>()).add(rule);
            buildSignalEntries(rule, signalIndex);
        }

        this.byAiRuleId = Collections.unmodifiableMap(idIndex);
        this.byPattern = freezeListMap(patternIndex);
        this.bySignalFeature = freezeListMap(signalIndex);
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
     * Returns AI rules whose pattern exactly matches the joined token list.
     *
     * Multiple rules may share a pattern when a large evidence batch was split
     * into deterministic suffix_part shards. Prediction must preserve those
     * shards instead of silently overwriting them.
     */
    public List<AiRule> getByExactPattern(List<String> tokens) {
        List<AiRule> found = byPattern.get(normalizedPattern(tokens));
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

    private static Map<String, List<AiRule>> freezeListMap(Map<String, List<AiRule>> source) {
        Map<String, List<AiRule>> frozen = new HashMap<>();
        for (Map.Entry<String, List<AiRule>> entry : source.entrySet()) {
            frozen.put(entry.getKey(), Collections.unmodifiableList(new ArrayList<>(entry.getValue())));
        }
        return Collections.unmodifiableMap(frozen);
    }
}
