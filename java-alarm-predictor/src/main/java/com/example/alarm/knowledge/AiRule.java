package com.example.alarm.knowledge;

import java.util.Collections;
import java.util.List;

public final class AiRule {
    private final String aiRuleId;
    private final String batchId;
    private final String patternType;
    private final String pattern;
    private final String classificationMode;
    private final boolean doNotUseSuffixAlone;
    private final String defaultSeverity;
    private final String confidence;
    private final BatchSummary batchSummary;
    private final String coreFinding;
    private final List<SeveritySplitSignal> severitySplitLogic;
    private final FallbackLogic fallbackLogic;
    private final List<ExampleRule> representativeExamples;
    private final List<ExampleRule> exceptions;
    /** Pre-tokenized pattern tokens for index construction. */
    private final List<String> patternTokens;

    public AiRule(
            String aiRuleId,
            String batchId,
            String patternType,
            String pattern,
            String classificationMode,
            boolean doNotUseSuffixAlone,
            String defaultSeverity,
            String confidence,
            BatchSummary batchSummary,
            String coreFinding,
            List<SeveritySplitSignal> severitySplitLogic,
            FallbackLogic fallbackLogic,
            List<ExampleRule> representativeExamples,
            List<ExampleRule> exceptions,
            List<String> patternTokens
    ) {
        this.aiRuleId = aiRuleId;
        this.batchId = batchId;
        this.patternType = patternType;
        this.pattern = pattern;
        this.classificationMode = classificationMode;
        this.doNotUseSuffixAlone = doNotUseSuffixAlone;
        this.defaultSeverity = defaultSeverity;
        this.confidence = confidence;
        this.batchSummary = batchSummary;
        this.coreFinding = coreFinding;
        this.severitySplitLogic = Collections.unmodifiableList(severitySplitLogic);
        this.fallbackLogic = fallbackLogic;
        this.representativeExamples = Collections.unmodifiableList(representativeExamples);
        this.exceptions = Collections.unmodifiableList(exceptions);
        this.patternTokens = Collections.unmodifiableList(patternTokens);
    }

    public String getAiRuleId() { return aiRuleId; }
    public String getBatchId() { return batchId; }
    public String getPatternType() { return patternType; }
    public String getPattern() { return pattern; }
    public String getClassificationMode() { return classificationMode; }
    public boolean isDoNotUseSuffixAlone() { return doNotUseSuffixAlone; }
    public String getDefaultSeverity() { return defaultSeverity; }
    public String getConfidence() { return confidence; }
    public BatchSummary getBatchSummary() { return batchSummary; }
    public String getCoreFinding() { return coreFinding; }
    public List<SeveritySplitSignal> getSeveritySplitLogic() { return severitySplitLogic; }
    public FallbackLogic getFallbackLogic() { return fallbackLogic; }
    public List<ExampleRule> getRepresentativeExamples() { return representativeExamples; }
    public List<ExampleRule> getExceptions() { return exceptions; }
    public List<String> getPatternTokens() { return patternTokens; }
}
