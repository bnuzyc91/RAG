package com.example.alarm;

import java.util.List;

final class RuleSimilarity {
    private RuleSimilarity() {
    }

    static SimilarRule score(List<String> newTokens, MasterRule master) {
        List<String> masterTokens = master.getTokens();
        int denom = Math.max(Math.max(newTokens.size(), masterTokens.size()), 1);
        int lcs = longestCommonContiguousBlock(newTokens, masterTokens);
        int prefix = commonPrefixLength(newTokens, masterTokens);
        int suffix = commonSuffixLength(newTokens, masterTokens);
        double orderedRatio = sequenceRatio(newTokens, masterTokens);

        double score =
                0.45 * (lcs / (double) denom)
                        + 0.30 * (suffix / (double) Math.max(newTokens.size(), 1))
                        + 0.15 * (prefix / (double) Math.max(newTokens.size(), 1))
                        + 0.10 * orderedRatio;

        return new SimilarRule(
                master.getRule(),
                master.getSeverity(),
                score,
                lcs,
                prefix,
                suffix,
                "STRUCTURAL"
        );
    }

    static int commonPrefixLength(List<String> a, List<String> b) {
        int n = Math.min(a.size(), b.size());
        int count = 0;
        for (int i = 0; i < n; i++) {
            if (!a.get(i).equals(b.get(i))) {
                break;
            }
            count++;
        }
        return count;
    }

    static int commonSuffixLength(List<String> a, List<String> b) {
        int count = 0;
        int ai = a.size() - 1;
        int bi = b.size() - 1;
        while (ai >= 0 && bi >= 0 && a.get(ai).equals(b.get(bi))) {
            count++;
            ai--;
            bi--;
        }
        return count;
    }

    static int longestCommonContiguousBlock(List<String> a, List<String> b) {
        int[][] dp = new int[a.size() + 1][b.size() + 1];
        int best = 0;
        for (int i = 1; i <= a.size(); i++) {
            for (int j = 1; j <= b.size(); j++) {
                if (a.get(i - 1).equals(b.get(j - 1))) {
                    dp[i][j] = dp[i - 1][j - 1] + 1;
                    best = Math.max(best, dp[i][j]);
                }
            }
        }
        return best;
    }

    static double sequenceRatio(List<String> a, List<String> b) {
        int lcs = longestCommonSubsequenceLength(a, b);
        int total = a.size() + b.size();
        return total == 0 ? 0.0 : (2.0 * lcs) / total;
    }

    static double phraseSimilarity(List<String> a, List<String> b) {
        if (a.isEmpty() || b.isEmpty()) {
            return 0.0;
        }
        int maxLen = Math.max(a.size(), b.size());
        int commonBlock = longestCommonContiguousBlock(a, b);
        double ordered = sequenceRatio(a, b);
        double lenPenalty = Math.min(a.size(), b.size()) / (double) maxLen;
        return 0.65 * (commonBlock / (double) maxLen) + 0.25 * ordered + 0.10 * lenPenalty;
    }

    private static int longestCommonSubsequenceLength(List<String> a, List<String> b) {
        int[][] dp = new int[a.size() + 1][b.size() + 1];
        for (int i = 1; i <= a.size(); i++) {
            for (int j = 1; j <= b.size(); j++) {
                if (a.get(i - 1).equals(b.get(j - 1))) {
                    dp[i][j] = dp[i - 1][j - 1] + 1;
                } else {
                    dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
                }
            }
        }
        return dp[a.size()][b.size()];
    }
}
