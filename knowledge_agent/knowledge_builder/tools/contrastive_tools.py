from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations


def build_contrastive_context(
    rules,
    *,
    min_support: int = 2,
    min_purity: float = 0.70,
    max_items: int = 12,
    max_ngram: int = 4,
) -> dict:
    """Find token/phrase signals that distinguish severities inside a batch."""
    severity_totals = Counter(rule.severity for rule in rules)
    total_rules = sum(severity_totals.values())
    if total_rules == 0:
        return empty_contrastive_context()

    feature_counts: dict[str, Counter[str]] = defaultdict(Counter)
    feature_types: dict[str, str] = {}
    for rule in rules:
        for feature, feature_type in features_for_rule(rule.tokens, max_ngram=max_ngram):
            feature_counts[feature][rule.severity] += 1
            feature_types[feature] = feature_type

    signals = []
    for feature, counts in feature_counts.items():
        support = sum(counts.values())
        if support < min_support:
            continue
        dominant, dominant_count = counts.most_common(1)[0]
        feature_purity = dominant_count / support
        if feature_purity < min_purity:
            continue
        overall_rate = severity_totals[dominant] / total_rules
        feature_rate = dominant_count / support
        lift = feature_rate / overall_rate if overall_rate else 0.0
        signals.append(
            {
                "feature": feature,
                "feature_type": feature_types.get(feature, "phrase"),
                "predicts_severity": dominant,
                "support": support,
                "purity": round(feature_purity, 4),
                "lift": round(lift, 4),
                "severity_distribution": dict(sorted(counts.items())),
            }
        )

    signals = sorted(
        signals,
        key=lambda item: (
            item["predicts_severity"],
            -item["purity"],
            -item["lift"],
            -item["support"],
            item["feature"],
        ),
    )

    signals_by_severity = {}
    for severity in sorted(severity_totals):
        severity_signals = [item for item in signals if item["predicts_severity"] == severity]
        signals_by_severity[severity] = severity_signals[:max_items]

    return {
        "severity_totals": dict(sorted(severity_totals.items())),
        "top_signals": _top_global_signals(signals, max_items=max_items * 2),
        "signals_by_severity": signals_by_severity,
        "pairwise_contrasts": pairwise_contrasts(signals, max_items=max_items),
    }


def features_for_rule(tokens: list[str], *, max_ngram: int) -> set[tuple[str, str]]:
    features: set[tuple[str, str]] = set()
    for token in tokens:
        features.add((token, "token"))
    for size in range(2, min(max_ngram, len(tokens)) + 1):
        for start in range(0, len(tokens) - size + 1):
            features.add(("-".join(tokens[start : start + size]), "phrase"))
    return features


def pairwise_contrasts(signals: list[dict], *, max_items: int) -> list[dict]:
    by_severity: dict[str, list[dict]] = defaultdict(list)
    for signal in signals:
        by_severity[signal["predicts_severity"]].append(signal)

    contrasts = []
    for left, right in combinations(sorted(by_severity), 2):
        contrasts.append(
            {
                "severity_pair": [left, right],
                "left_signals": by_severity[left][:max_items],
                "right_signals": by_severity[right][:max_items],
            }
        )
    return contrasts


def empty_contrastive_context() -> dict:
    return {
        "severity_totals": {},
        "top_signals": [],
        "signals_by_severity": {},
        "pairwise_contrasts": [],
    }


def _top_global_signals(signals: list[dict], *, max_items: int) -> list[dict]:
    return sorted(
        signals,
        key=lambda item: (-item["purity"], -item["lift"], -item["support"], item["feature"]),
    )[:max_items]

