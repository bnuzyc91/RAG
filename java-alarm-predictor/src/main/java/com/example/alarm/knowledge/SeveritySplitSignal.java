package com.example.alarm.knowledge;

import java.util.Collections;
import java.util.List;
import java.util.Map;

public final class SeveritySplitSignal {
    private final String condition;
    private final String feature;
    private final String featureType;
    private final String predictsSeverity;
    private final int support;
    private final double purity;
    private final double lift;
    private final Map<String, Integer> severityDistribution;
    private final List<String> exampleRuleIds;
    private final List<String> counterexampleRuleIds;
    /** Pre-tokenized feature tokens for fast containment checks. */
    private final List<String> featureTokens;

    public SeveritySplitSignal(
            String condition,
            String feature,
            String featureType,
            String predictsSeverity,
            int support,
            double purity,
            double lift,
            Map<String, Integer> severityDistribution,
            List<String> exampleRuleIds,
            List<String> counterexampleRuleIds,
            List<String> featureTokens
    ) {
        this.condition = condition;
        this.feature = feature;
        this.featureType = featureType;
        this.predictsSeverity = predictsSeverity;
        this.support = support;
        this.purity = purity;
        this.lift = lift;
        this.severityDistribution = Collections.unmodifiableMap(severityDistribution);
        this.exampleRuleIds = Collections.unmodifiableList(exampleRuleIds);
        this.counterexampleRuleIds = Collections.unmodifiableList(counterexampleRuleIds);
        this.featureTokens = Collections.unmodifiableList(featureTokens);
    }

    public String getCondition() { return condition; }
    public String getFeature() { return feature; }
    public String getFeatureType() { return featureType; }
    public String getPredictsSeverity() { return predictsSeverity; }
    public int getSupport() { return support; }
    public double getPurity() { return purity; }
    public double getLift() { return lift; }
    public Map<String, Integer> getSeverityDistribution() { return severityDistribution; }
    public List<String> getExampleRuleIds() { return exampleRuleIds; }
    public List<String> getCounterexampleRuleIds() { return counterexampleRuleIds; }
    public List<String> getFeatureTokens() { return featureTokens; }
}
