package com.example.alarm.knowledge;

import java.util.Collections;
import java.util.Map;

public final class BatchSummary {
    private final int support;
    private final Map<String, Integer> severityDistribution;
    private final String dominantSeverity;
    private final double purity;
    private final double entropy;

    public BatchSummary(
            int support,
            Map<String, Integer> severityDistribution,
            String dominantSeverity,
            double purity,
            double entropy
    ) {
        this.support = support;
        this.severityDistribution = Collections.unmodifiableMap(severityDistribution);
        this.dominantSeverity = dominantSeverity;
        this.purity = purity;
        this.entropy = entropy;
    }

    public int getSupport() { return support; }
    public Map<String, Integer> getSeverityDistribution() { return severityDistribution; }
    public String getDominantSeverity() { return dominantSeverity; }
    public double getPurity() { return purity; }
    public double getEntropy() { return entropy; }
}
