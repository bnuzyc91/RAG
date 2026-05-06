package com.example.alarm;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

final class TrieNode {
    final Map<String, TrieNode> children = new HashMap<>();
    final Map<String, Integer> severityCounts = new HashMap<>();
    int ruleCount;

    void add(List<String> tokens, String severity) {
        TrieNode node = this;
        node.addSeverity(severity);
        for (String token : tokens) {
            node = node.children.computeIfAbsent(token, ignored -> new TrieNode());
            node.addSeverity(severity);
        }
    }

    TrieMatch matchLongest(List<String> tokens) {
        TrieNode node = this;
        TrieNode best = null;
        int bestLength = 0;

        for (int i = 0; i < tokens.size(); i++) {
            node = node.children.get(tokens.get(i));
            if (node == null) {
                break;
            }
            best = node;
            bestLength = i + 1;
        }

        if (best == null || best.ruleCount == 0) {
            return TrieMatch.noMatch();
        }
        Map.Entry<String, Integer> top = topSeverity(best.severityCounts);
        return new TrieMatch(
                top.getKey(),
                top.getValue() / (double) best.ruleCount,
                bestLength,
                best.ruleCount
        );
    }

    private void addSeverity(String severity) {
        ruleCount++;
        severityCounts.merge(severity, 1, Integer::sum);
    }

    private static Map.Entry<String, Integer> topSeverity(Map<String, Integer> counts) {
        return counts.entrySet().stream()
                .max(Map.Entry.comparingByValue())
                .orElseThrow();
    }
}
