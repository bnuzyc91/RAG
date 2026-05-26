package com.example.alarm.knowledge;

import com.example.alarm.RuleTokenizer;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Loads alarm_rule_knowledge.json into an immutable KnowledgeBase.
 *
 * Uses a minimal recursive-descent JSON parser so there are no external dependencies.
 * All patterns and signal features are pre-tokenized at load time.
 */
public final class AlarmKnowledgeLoader {
    private AlarmKnowledgeLoader() {}

    public static KnowledgeBase load(Path jsonPath) throws IOException {
        String text = Files.readString(jsonPath, StandardCharsets.UTF_8);
        Object root = new JsonParser(text).parse();
        Map<String, Object> rootMap = castMap(root);
        List<Object> aiRulesRaw = castList(rootMap.get("ai_rules"));

        List<AiRule> rules = new ArrayList<>(aiRulesRaw.size());
        for (Object item : aiRulesRaw) {
            AiRule rule = parseAiRule(castMap(item));
            if (rule != null) {
                rules.add(rule);
            }
        }
        return new KnowledgeBase(rules);
    }

    private static AiRule parseAiRule(Map<String, Object> m) {
        String pattern = str(m, "pattern");
        if (pattern == null || pattern.isBlank()) {
            return null;
        }
        List<String> patternTokens = RuleTokenizer.tokenize(pattern);

        BatchSummary summary = parseBatchSummary(castMapOrEmpty(m.get("batch_summary")));
        List<SeveritySplitSignal> splitLogic = parseSplitLogic(castListOrEmpty(m.get("severity_split_logic")));
        FallbackLogic fallback = parseFallback(castMapOrEmpty(m.get("fallback_logic")));
        List<ExampleRule> repExamples = parseExamples(castListOrEmpty(m.get("representative_examples")));
        List<ExampleRule> exceptions = parseExamples(castListOrEmpty(m.get("exceptions")));

        return new AiRule(
                str(m, "ai_rule_id"),
                str(m, "batch_id"),
                str(m, "pattern_type"),
                pattern,
                str(m, "classification_mode"),
                bool(m, "do_not_use_suffix_alone"),
                str(m, "default_severity"),
                str(m, "confidence"),
                summary,
                str(m, "core_finding"),
                splitLogic,
                fallback,
                repExamples,
                exceptions,
                patternTokens
        );
    }

    private static BatchSummary parseBatchSummary(Map<String, Object> m) {
        return new BatchSummary(
                intVal(m, "support"),
                parseSeverityDist(castMapOrEmpty(m.get("severity_distribution"))),
                str(m, "dominant_severity"),
                dbl(m, "purity"),
                dbl(m, "entropy")
        );
    }

    private static List<SeveritySplitSignal> parseSplitLogic(List<Object> raw) {
        List<SeveritySplitSignal> out = new ArrayList<>(raw.size());
        for (Object item : raw) {
            Map<String, Object> m = castMap(item);
            String feature = str(m, "feature");
            if (feature == null || feature.isBlank()) continue;
            List<String> featureTokens = RuleTokenizer.tokenize(feature);
            out.add(new SeveritySplitSignal(
                    str(m, "condition"),
                    feature,
                    str(m, "feature_type"),
                    str(m, "predicts_severity"),
                    intVal(m, "support"),
                    dbl(m, "purity"),
                    dbl(m, "lift"),
                    parseSeverityDist(castMapOrEmpty(m.get("severity_distribution"))),
                    strList(castListOrEmpty(m.get("example_rule_ids"))),
                    strList(castListOrEmpty(m.get("counterexample_rule_ids"))),
                    featureTokens
            ));
        }
        return out;
    }

    private static FallbackLogic parseFallback(Map<String, Object> m) {
        return new FallbackLogic(
                str(m, "severity"),
                str(m, "confidence"),
                str(m, "use_when")
        );
    }

    private static List<ExampleRule> parseExamples(List<Object> raw) {
        List<ExampleRule> out = new ArrayList<>(raw.size());
        for (Object item : raw) {
            Map<String, Object> m = castMap(item);
            out.add(new ExampleRule(
                    str(m, "source_rule_id"),
                    str(m, "rule"),
                    str(m, "severity")
            ));
        }
        return out;
    }

    private static Map<String, Integer> parseSeverityDist(Map<String, Object> m) {
        Map<String, Integer> out = new HashMap<>();
        for (Map.Entry<String, Object> e : m.entrySet()) {
            if (e.getValue() instanceof Number) {
                out.put(e.getKey(), ((Number) e.getValue()).intValue());
            }
        }
        return out;
    }

    // ---- type helpers ----

    @SuppressWarnings("unchecked")
    private static Map<String, Object> castMap(Object o) {
        if (o instanceof Map) return (Map<String, Object>) o;
        return Collections.emptyMap();
    }

    @SuppressWarnings("unchecked")
    private static List<Object> castList(Object o) {
        if (o instanceof List) return (List<Object>) o;
        return Collections.emptyList();
    }

    private static Map<String, Object> castMapOrEmpty(Object o) { return castMap(o); }
    private static List<Object> castListOrEmpty(Object o) { return castList(o); }

    private static String str(Map<String, Object> m, String key) {
        Object v = m.get(key);
        return v instanceof String ? (String) v : null;
    }

    private static boolean bool(Map<String, Object> m, String key) {
        Object v = m.get(key);
        return Boolean.TRUE.equals(v);
    }

    private static int intVal(Map<String, Object> m, String key) {
        Object v = m.get(key);
        return v instanceof Number ? ((Number) v).intValue() : 0;
    }

    private static double dbl(Map<String, Object> m, String key) {
        Object v = m.get(key);
        return v instanceof Number ? ((Number) v).doubleValue() : 0.0;
    }

    private static List<String> strList(List<Object> raw) {
        List<String> out = new ArrayList<>(raw.size());
        for (Object o : raw) {
            if (o instanceof String) out.add((String) o);
        }
        return out;
    }

    // -----------------------------------------------------------------------
    // Minimal recursive-descent JSON parser
    // Returns: Map<String,Object> | List<Object> | String | Double | Boolean | null
    // -----------------------------------------------------------------------

    static final class JsonParser {
        private final char[] src;
        private int pos;

        JsonParser(String text) {
            this.src = text.toCharArray();
            this.pos = 0;
        }

        Object parse() {
            skipWhitespace();
            return parseValue();
        }

        private Object parseValue() {
            if (pos >= src.length) return null;
            char c = src[pos];
            if (c == '{') return parseObject();
            if (c == '[') return parseArray();
            if (c == '"') return parseString();
            if (c == 't') return parseLiteral("true", Boolean.TRUE);
            if (c == 'f') return parseLiteral("false", Boolean.FALSE);
            if (c == 'n') return parseLiteral("null", null);
            if (c == '-' || Character.isDigit(c)) return parseNumber();
            throw new IllegalStateException("Unexpected character '" + c + "' at position " + pos);
        }

        private Map<String, Object> parseObject() {
            expect('{');
            Map<String, Object> map = new HashMap<>();
            skipWhitespace();
            if (peek() == '}') { pos++; return map; }
            while (true) {
                skipWhitespace();
                String key = parseString();
                skipWhitespace();
                expect(':');
                skipWhitespace();
                Object value = parseValue();
                map.put(key, value);
                skipWhitespace();
                char next = src[pos];
                if (next == '}') { pos++; break; }
                if (next == ',') { pos++; continue; }
                throw new IllegalStateException("Expected ',' or '}' at position " + pos);
            }
            return map;
        }

        private List<Object> parseArray() {
            expect('[');
            List<Object> list = new ArrayList<>();
            skipWhitespace();
            if (peek() == ']') { pos++; return list; }
            while (true) {
                skipWhitespace();
                list.add(parseValue());
                skipWhitespace();
                char next = src[pos];
                if (next == ']') { pos++; break; }
                if (next == ',') { pos++; continue; }
                throw new IllegalStateException("Expected ',' or ']' at position " + pos);
            }
            return list;
        }

        private String parseString() {
            expect('"');
            StringBuilder sb = new StringBuilder();
            while (pos < src.length) {
                char c = src[pos++];
                if (c == '"') return sb.toString();
                if (c == '\\') {
                    char esc = src[pos++];
                    switch (esc) {
                        case '"': sb.append('"'); break;
                        case '\\': sb.append('\\'); break;
                        case '/': sb.append('/'); break;
                        case 'n': sb.append('\n'); break;
                        case 'r': sb.append('\r'); break;
                        case 't': sb.append('\t'); break;
                        case 'b': sb.append('\b'); break;
                        case 'f': sb.append('\f'); break;
                        case 'u':
                            int code = Integer.parseInt(new String(src, pos, 4), 16);
                            sb.append((char) code);
                            pos += 4;
                            break;
                        default: sb.append(esc);
                    }
                } else {
                    sb.append(c);
                }
            }
            throw new IllegalStateException("Unterminated string");
        }

        private Number parseNumber() {
            int start = pos;
            if (pos < src.length && src[pos] == '-') pos++;
            while (pos < src.length && Character.isDigit(src[pos])) pos++;
            boolean isFloat = false;
            if (pos < src.length && src[pos] == '.') {
                isFloat = true;
                pos++;
                while (pos < src.length && Character.isDigit(src[pos])) pos++;
            }
            if (pos < src.length && (src[pos] == 'e' || src[pos] == 'E')) {
                isFloat = true;
                pos++;
                if (pos < src.length && (src[pos] == '+' || src[pos] == '-')) pos++;
                while (pos < src.length && Character.isDigit(src[pos])) pos++;
            }
            String numStr = new String(src, start, pos - start);
            if (isFloat) return Double.parseDouble(numStr);
            long lv = Long.parseLong(numStr);
            return (lv >= Integer.MIN_VALUE && lv <= Integer.MAX_VALUE) ? (int) lv : lv;
        }

        private Object parseLiteral(String expected, Object value) {
            for (char c : expected.toCharArray()) {
                if (pos >= src.length || src[pos] != c) {
                    throw new IllegalStateException("Expected '" + expected + "' at position " + pos);
                }
                pos++;
            }
            return value;
        }

        private void skipWhitespace() {
            while (pos < src.length && Character.isWhitespace(src[pos])) pos++;
        }

        private void expect(char c) {
            if (pos >= src.length || src[pos] != c) {
                throw new IllegalStateException("Expected '" + c + "' at position " + pos);
            }
            pos++;
        }

        private char peek() {
            return pos < src.length ? src[pos] : '\0';
        }
    }
}
