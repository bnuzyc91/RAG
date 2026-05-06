package com.example.alarm;

import java.util.List;

public final class ExampleUsage {
    private ExampleUsage() {
    }

    public static void main(String[] args) {
        List<MasterRule> masterRules = List.of(
                new MasterRule("NOT-CONNECTED-VIA-TIE-BREAKERS", "Diagnostic"),
                new MasterRule("LOCK-OUT-RELAY-TC-FAIL", "Medium"),
                new MasterRule("MEGA-CENTRAL-UTILITY-BUILDING-TRIP", "High")
        );

        AlarmSeverityPredictor predictor = new AlarmSeverityPredictor(masterRules);

        SeverityPrediction prediction = predictor.predict(
                "SESSION-STORAGE-SERVICE-AND-ISOLATED-REDUNDANT-TIE-NOT-CONNECTED-VIA-TIE-BREAKER"
        );

        System.out.println("Predicted severity: " + prediction.getPredictedSeverity());
        System.out.println("Confidence: " + prediction.getConfidence());
        System.out.println("Votes:");
        for (SeverityVote vote : prediction.getVotes()) {
            System.out.printf(
                    "  %s -> %s conf=%.3f evidence=%s%n",
                    vote.getMethod(),
                    vote.getSeverity(),
                    vote.getConfidence(),
                    vote.getEvidence()
            );
        }
        System.out.println("Similar rules:");
        for (SimilarRule similar : prediction.getSimilarRules()) {
            System.out.printf(
                    "  %.3f %s %s%n",
                    similar.getScore(),
                    similar.getSeverity(),
                    similar.getRule()
            );
        }
    }
}
