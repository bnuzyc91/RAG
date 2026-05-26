package com.example.alarm.knowledge;

public final class ExampleRule {
    private final String sourceRuleId;
    private final String rule;
    private final String severity;

    public ExampleRule(String sourceRuleId, String rule, String severity) {
        this.sourceRuleId = sourceRuleId;
        this.rule = rule;
        this.severity = severity;
    }

    public String getSourceRuleId() { return sourceRuleId; }
    public String getRule() { return rule; }
    public String getSeverity() { return severity; }
}
