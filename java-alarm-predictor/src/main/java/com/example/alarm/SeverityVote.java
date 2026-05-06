package com.example.alarm;

public final class SeverityVote {
    private final String severity;
    private final double confidence;
    private final double weight;
    private final String method;
    private final String evidence;

    public SeverityVote(String severity, double confidence, double weight, String method, String evidence) {
        this.severity = severity;
        this.confidence = confidence;
        this.weight = weight;
        this.method = method;
        this.evidence = evidence;
    }

    public String getSeverity() {
        return severity;
    }

    public double getConfidence() {
        return confidence;
    }

    public double getWeight() {
        return weight;
    }

    public String getMethod() {
        return method;
    }

    public String getEvidence() {
        return evidence;
    }

    public double weightedScore() {
        return confidence * weight;
    }
}
