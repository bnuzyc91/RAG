package com.example.alarm;

final class TrieMatch {
    final String severity;
    final double confidence;
    final int matchLength;
    final int support;

    TrieMatch(String severity, double confidence, int matchLength, int support) {
        this.severity = severity;
        this.confidence = confidence;
        this.matchLength = matchLength;
        this.support = support;
    }

    static TrieMatch noMatch() {
        return new TrieMatch(null, 0.0, 0, 0);
    }

    boolean hasMatch() {
        return severity != null;
    }
}
