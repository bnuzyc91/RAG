package com.example.alarm;

import java.util.List;

public final class SeverityPrediction {
    private final String rule;
    private final String predictedSeverity;
    private final double confidence;
    private final List<SeverityVote> votes;
    private final List<SimilarRule> similarRules;

    public SeverityPrediction(
            String rule,
            String predictedSeverity,
            double confidence,
            List<SeverityVote> votes,
            List<SimilarRule> similarRules
    ) {
        this.rule = rule;
        this.predictedSeverity = predictedSeverity;
        this.confidence = confidence;
        this.votes = List.copyOf(votes);
        this.similarRules = List.copyOf(similarRules);
    }

    public String getRule() {
        return rule;
    }

    public String getPredictedSeverity() {
        return predictedSeverity;
    }

    public double getConfidence() {
        return confidence;
    }

    public List<SeverityVote> getVotes() {
        return votes;
    }

    public List<SimilarRule> getSimilarRules() {
        return similarRules;
    }
}
