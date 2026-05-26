package com.example.alarm;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

public final class AlarmSeverityPredictor {
    private final List<MasterRule> masterRules;
    private final TrieNode prefixTrie = new TrieNode();
    private final TrieNode suffixTrie = new TrieNode();
    private final Map<List<String>, List<MasterRule>> suffixIndex = new HashMap<>();

    public AlarmSeverityPredictor(List<MasterRule> masterRules) {
        this.masterRules = List.copyOf(masterRules);
        for (MasterRule master : masterRules) {
            List<String> tokens = master.getTokens();
            prefixTrie.add(tokens, master.getSeverity());
            List<String> reversed = new ArrayList<>(tokens);
            Collections.reverse(reversed);
            suffixTrie.add(reversed, master.getSeverity());
            addSuffixes(master);
        }
    }

    public SeverityPrediction predict(String rule) {
        return predict(rule, 5);
    }

    public SeverityPrediction predict(String rule, int topK) {
        List<String> tokens = RuleTokenizer.tokenize(rule);
        List<SeverityVote> votes = new ArrayList<>();

        TrieMatch prefix = prefixTrie.matchLongest(tokens);
        if (prefix.hasMatch()) {
            votes.add(new SeverityVote(
                    prefix.severity,
                    prefix.confidence,
                    0.8,
                    "PREFIX_TRIE",
                    "matched first " + prefix.matchLength + " tokens; support=" + prefix.support
            ));
        }

        List<String> reversed = new ArrayList<>(tokens);
        Collections.reverse(reversed);
        TrieMatch suffix = suffixTrie.matchLongest(reversed);
        if (suffix.hasMatch()) {
            votes.add(new SeverityVote(
                    suffix.severity,
                    suffix.confidence,
                    1.0,
                    "SUFFIX_TRIE",
                    "matched last " + suffix.matchLength + " tokens; support=" + suffix.support
            ));
        }

        SuffixPhraseMatch exactSuffix = exactSuffixChain(tokens);
        if (exactSuffix.hasMatch()) {
            votes.add(new SeverityVote(
                    exactSuffix.severity,
                    exactSuffix.confidence,
                    1.4,
                    exactSuffix.method,
                    exactSuffix.matchedPhrase
            ));
        }

        SuffixPhraseMatch phrase = bestEmbeddedOrFuzzyPhrase(tokens);
        if (phrase.hasMatch()) {
            votes.add(new SeverityVote(
                    phrase.severity,
                    phrase.confidence,
                    1.3,
                    phrase.method,
                    phrase.matchedPhrase
            ));
        }

        List<SimilarRule> similarRules = topSimilarRules(tokens, topK);
        if (!similarRules.isEmpty() && similarRules.get(0).getScore() > 0.0) {
            Map<String, Double> bySeverity = new HashMap<>();
            for (SimilarRule similar : similarRules) {
                bySeverity.merge(similar.getSeverity(), similar.getScore(), Double::sum);
            }
            Map.Entry<String, Double> top = topDouble(bySeverity);
            double total = bySeverity.values().stream().mapToDouble(Double::doubleValue).sum();
            votes.add(new SeverityVote(
                    top.getKey(),
                    total == 0.0 ? 0.0 : top.getValue() / total,
                    0.8,
                    "STRUCTURAL_NEIGHBORS",
                    "top neighbor=" + similarRules.get(0).getRule()
            ));
        }

        PredictionDecision decision = decide(votes);
        return new SeverityPrediction(
                rule,
                decision.severity,
                decision.confidence,
                votes,
                similarRules
        );
    }

    public List<SeverityPrediction> predictAll(List<String> rules, int topK) {
        List<SeverityPrediction> out = new ArrayList<>();
        for (String rule : rules) {
            out.add(predict(rule, topK));
        }
        return out;
    }

    private void addSuffixes(MasterRule master) {
        List<String> tokens = master.getTokens();
        for (int start = 0; start < tokens.size(); start++) {
            List<String> suffix = List.copyOf(tokens.subList(start, tokens.size()));
            suffixIndex.computeIfAbsent(suffix, ignored -> new ArrayList<>()).add(master);
        }
    }

    private SuffixPhraseMatch exactSuffixChain(List<String> tokens) {
        SuffixPhraseMatch best = SuffixPhraseMatch.noMatch();
        for (int start = 0; start < tokens.size(); start++) {
            List<String> suffix = List.copyOf(tokens.subList(start, tokens.size()));
            List<MasterRule> found = suffixIndex.get(suffix);
            if (found == null || found.isEmpty()) {
                continue;
            }
            Map<String, Integer> counts = severityCounts(found);
            Map.Entry<String, Integer> top = topInt(counts);
            double confidence = top.getValue() / (double) found.size();
            if (suffix.size() > best.matchLength) {
                best = new SuffixPhraseMatch(
                        found.get(0),
                        top.getKey(),
                        confidence,
                        suffix.size(),
                        suffix.size(),
                        RuleTokenizer.joinTokens(suffix),
                        "EXACT_SUFFIX_CHAIN"
                );
            }
        }
        return best;
    }

    private SuffixPhraseMatch bestEmbeddedOrFuzzyPhrase(List<String> newTokens) {
        SuffixPhraseMatch best = SuffixPhraseMatch.noMatch();

        for (MasterRule master : masterRules) {
            List<String> masterTokens = master.getTokens();
            if (masterTokens.isEmpty()) {
                continue;
            }

            double embeddedScore = bestEmbeddedPhraseScore(newTokens, masterTokens);
            double suffixScore = bestFuzzySuffixScore(newTokens, masterTokens);
            double score = Math.max(embeddedScore, suffixScore);

            // High threshold because this method gets a strong vote. The
            // canonical tokenizer already handles BREAKERS -> BREAKER, so
            // NOT-CONNECTED-VIA-TIE-BREAKERS should be a near-perfect phrase.
            if (score >= 0.72 && score > best.score) {
                best = new SuffixPhraseMatch(
                        master,
                        master.getSeverity(),
                        score,
                        score,
                        masterTokens.size(),
                        master.getRule(),
                        embeddedScore >= suffixScore ? "EMBEDDED_PHRASE" : "FUZZY_SUFFIX_PHRASE"
                );
            }
        }
        return best;
    }

    private double bestEmbeddedPhraseScore(List<String> newTokens, List<String> masterTokens) {
        if (newTokens.size() < masterTokens.size()) {
            return RuleSimilarity.phraseSimilarity(newTokens, masterTokens);
        }

        double best = 0.0;
        for (int start = 0; start <= newTokens.size() - masterTokens.size(); start++) {
            List<String> window = newTokens.subList(start, start + masterTokens.size());
            best = Math.max(best, RuleSimilarity.phraseSimilarity(window, masterTokens));
        }
        return best;
    }

    private double bestFuzzySuffixScore(List<String> newTokens, List<String> masterTokens) {
        double best = 0.0;
        int maxLen = Math.min(newTokens.size(), masterTokens.size());
        for (int len = 1; len <= maxLen; len++) {
            List<String> newSuffix = newTokens.subList(newTokens.size() - len, newTokens.size());
            List<String> masterSuffix = masterTokens.subList(masterTokens.size() - len, masterTokens.size());
            best = Math.max(best, RuleSimilarity.phraseSimilarity(newSuffix, masterSuffix));
        }
        return best;
    }

    private List<SimilarRule> topSimilarRules(List<String> tokens, int topK) {
        return masterRules.stream()
                .map(master -> RuleSimilarity.score(tokens, master))
                .sorted(Comparator.comparingDouble(SimilarRule::getScore).reversed())
                .limit(topK)
                .collect(Collectors.toList());
    }

    /**
     * Aggregates severity votes into a single decision.
     *
     * <p>Votes are first grouped into <em>family seats</em>. Within each family
     * only the highest-weighted vote is retained, preventing multiple signals
     * from the same evidence source from inflating the final score. Critically,
     * knowledge-base votes ({@code KB_*}) occupy their own family seat so they
     * contribute <em>alongside</em> structural suffix votes rather than competing
     * with them for the same seat.
     *
     * <p>Package-private so that composite callers in {@code com.example.alarm}
     * can pass a merged structural + KB vote list directly.
     */
    PredictionDecision decide(List<SeverityVote> votes) {
        if (votes.isEmpty()) {
            return new PredictionDecision(null, 0.0);
        }

        // ---- Family-seat grouping -------------------------------------------
        // Within each named family keep only the highest-weighted vote so that
        // multiple signals from the same evidence source cannot inflate the score.
        // KB_ prefixed methods form their own family so knowledge-based evidence
        // supports (rather than displaces) structural suffix evidence.
        // --------------------------------------------------------------------
        Map<String, SeverityVote> familyBest = new LinkedHashMap<>();
        for (SeverityVote vote : votes) {
            String family = familyOf(vote.getMethod());
            SeverityVote existing = familyBest.get(family);
            if (existing == null || vote.weightedScore() > existing.weightedScore()) {
                familyBest.put(family, vote);
            }
        }

        Map<String, Double> scores = new LinkedHashMap<>();
        for (SeverityVote vote : familyBest.values()) {
            if (vote.getSeverity() != null && !vote.getSeverity().isBlank()) {
                scores.merge(vote.getSeverity(), vote.weightedScore(), Double::sum);
            }
        }
        if (scores.isEmpty()) {
            return new PredictionDecision(null, 0.0);
        }
        Map.Entry<String, Double> top = topDouble(scores);
        double total = scores.values().stream().mapToDouble(Double::doubleValue).sum();
        return new PredictionDecision(top.getKey(), total == 0.0 ? 0.0 : top.getValue() / total);
    }

    /**
     * Maps a vote method name to a family seat.
     *
     * <p>Rules:
     * <ul>
     *   <li>{@code KB_*}          → {@code KB_FAMILY} (knowledge-base, separate seat)
     *   <li>{@code PREFIX_*}      → {@code PREFIX_FAMILY}
     *   <li>suffix-related names  → {@code SUFFIX_FAMILY}
     *   <li>{@code STRUCTURAL_*}  → {@code NEIGHBORS_FAMILY}
     *   <li>anything else         → its own individual seat (method name as key)
     * </ul>
     */
    private static String familyOf(String method) {
        if (method == null) return "UNKNOWN";
        if (method.startsWith("KB_"))          return "KB_FAMILY";
        if (method.startsWith("PREFIX_"))      return "PREFIX_FAMILY";
        if (method.startsWith("SUFFIX_")
                || method.equals("EXACT_SUFFIX_CHAIN")
                || method.equals("EMBEDDED_PHRASE")
                || method.equals("FUZZY_SUFFIX_PHRASE")) return "SUFFIX_FAMILY";
        if (method.startsWith("STRUCTURAL_"))  return "NEIGHBORS_FAMILY";
        return method; // unknown methods each get their own seat
    }

    private static Map<String, Integer> severityCounts(List<MasterRule> rules) {
        Map<String, Integer> counts = new HashMap<>();
        for (MasterRule rule : rules) {
            counts.merge(rule.getSeverity(), 1, Integer::sum);
        }
        return counts;
    }

    private static Map.Entry<String, Integer> topInt(Map<String, Integer> counts) {
        return counts.entrySet().stream()
                .max(Map.Entry.comparingByValue())
                .orElseThrow();
    }

    private static Map.Entry<String, Double> topDouble(Map<String, Double> counts) {
        return counts.entrySet().stream()
                .max(Map.Entry.comparingByValue())
                .orElseThrow();
    }

    static final class PredictionDecision {
        final String severity;
        final double confidence;

        PredictionDecision(String severity, double confidence) {
            this.severity = severity;
            this.confidence = confidence;
        }
    }
}
