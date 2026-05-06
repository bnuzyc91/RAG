package com.example.alarm;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Set;

public final class RuleTokenizer {
    private static final Set<String> KEEP_S_ENDING = Set.of(
            "BUS",
            "BYPASS",
            "GAS",
            "STATUS"
    );

    private RuleTokenizer() {
    }

    public static List<String> tokenize(String rule) {
        List<String> out = new ArrayList<>();
        if (rule == null) {
            return out;
        }
        for (String raw : rule.toUpperCase(Locale.ROOT).trim().split("-")) {
            String token = raw.trim();
            if (!token.isEmpty()) {
                out.add(canonicalToken(token));
            }
        }
        return out;
    }

    public static String canonicalToken(String token) {
        if (token == null || token.isBlank()) {
            return "";
        }
        String t = token.toUpperCase(Locale.ROOT).trim();

        // Domain-safe singular/plural normalization. Keep known words where
        // trailing S is part of the word, such as BUS.
        if (KEEP_S_ENDING.contains(t)) {
            return t;
        }
        if (t.endsWith("IES") && t.length() > 4) {
            return t.substring(0, t.length() - 3) + "Y";
        }
        if (t.endsWith("ERS") && t.length() > 4) {
            return t.substring(0, t.length() - 1);
        }
        if (t.endsWith("S") && t.length() > 3) {
            return t.substring(0, t.length() - 1);
        }
        return t;
    }

    public static String joinTokens(List<String> tokens) {
        return String.join("-", tokens);
    }
}
