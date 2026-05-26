package com.example.alarm.knowledge;

public final class FallbackLogic {
    private final String severity;
    private final String confidence;
    private final String useWhen;

    public FallbackLogic(String severity, String confidence, String useWhen) {
        this.severity = severity;
        this.confidence = confidence;
        this.useWhen = useWhen;
    }

    public String getSeverity() { return severity; }
    public String getConfidence() { return confidence; }
    public String getUseWhen() { return useWhen; }
}
