package com.example.alarm;

final class SuffixPhraseMatch {
    final MasterRule masterRule;
    final String severity;
    final double confidence;
    final double score;
    final int matchLength;
    final String matchedPhrase;
    final String method;

    SuffixPhraseMatch(
            MasterRule masterRule,
            String severity,
            double confidence,
            double score,
            int matchLength,
            String matchedPhrase,
            String method
    ) {
        this.masterRule = masterRule;
        this.severity = severity;
        this.confidence = confidence;
        this.score = score;
        this.matchLength = matchLength;
        this.matchedPhrase = matchedPhrase;
        this.method = method;
    }

    static SuffixPhraseMatch noMatch() {
        return new SuffixPhraseMatch(null, null, 0.0, 0.0, 0, "", "NO_MATCH");
    }

    boolean hasMatch() {
        return severity != null;
    }
}
