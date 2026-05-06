package com.example.alarm;

import java.util.List;

public final class MasterRule {
    private final String rule;
    private final String severity;
    private final List<String> tokens;

    public MasterRule(String rule, String severity) {
        this.rule = rule;
        this.severity = severity == null ? "" : severity.trim();
        this.tokens = RuleTokenizer.tokenize(rule);
    }

    public String getRule() {
        return rule;
    }

    public String getSeverity() {
        return severity;
    }

    public List<String> getTokens() {
        return tokens;
    }
}
