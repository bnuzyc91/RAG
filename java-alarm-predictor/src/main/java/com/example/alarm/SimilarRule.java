package com.example.alarm;

public final class SimilarRule {
    private final String rule;
    private final String severity;
    private final double score;
    private final int longestCommonBlock;
    private final int prefixMatchLength;
    private final int suffixMatchLength;
    private final String method;

    public SimilarRule(
            String rule,
            String severity,
            double score,
            int longestCommonBlock,
            int prefixMatchLength,
            int suffixMatchLength,
            String method
    ) {
        this.rule = rule;
        this.severity = severity;
        this.score = score;
        this.longestCommonBlock = longestCommonBlock;
        this.prefixMatchLength = prefixMatchLength;
        this.suffixMatchLength = suffixMatchLength;
        this.method = method;
    }

    public String getRule() {
        return rule;
    }

    public String getSeverity() {
        return severity;
    }

    public double getScore() {
        return score;
    }

    public int getLongestCommonBlock() {
        return longestCommonBlock;
    }

    public int getPrefixMatchLength() {
        return prefixMatchLength;
    }

    public int getSuffixMatchLength() {
        return suffixMatchLength;
    }

    public String getMethod() {
        return method;
    }
}
