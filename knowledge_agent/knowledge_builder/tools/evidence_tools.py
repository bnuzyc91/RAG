from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class AlarmRule:
    rule: str
    severity: str
    tokens: list[str]


@dataclass(frozen=True)
class EvidenceBatch:
    batch_id: str
    pattern_type: str
    pattern: str
    support: int
    severity_distribution: dict[str, int]
    dominant_severity: str | None
    purity: float
    entropy: float
    examples: list[dict[str, str]]
    counterexamples: list[dict[str, str]]
    structural_context: dict


def tokenize_rule(rule: str) -> list[str]:
    return [part for part in rule.upper().strip().split("-") if part]


def load_rules_csv(csv_path: str | Path) -> list[AlarmRule]:
    path = Path(csv_path)
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = {"Rule", "Severity"} - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path} is missing required columns: {sorted(missing)}")
        rules = []
        for row in reader:
            rule = (row.get("Rule") or "").strip()
            severity = (row.get("Severity") or "").strip()
            if not rule or not severity:
                continue
            rules.append(AlarmRule(rule=rule, severity=severity, tokens=tokenize_rule(rule)))
    return rules


def entropy(counts: dict[str, int] | Counter[str]) -> float:
    total = sum(counts.values())
    if total == 0:
        return 0.0
    return -sum((count / total) * math.log2(count / total) for count in counts.values() if count)


def purity(counts: dict[str, int] | Counter[str]) -> float:
    total = sum(counts.values())
    if total == 0:
        return 0.0
    return max(counts.values()) / total


def dominant_severity(counts: dict[str, int] | Counter[str]) -> str | None:
    if not counts:
        return None
    return max(counts.items(), key=lambda item: item[1])[0]


def suffix_pattern(tokens: list[str], depth: int) -> str:
    if depth <= 0:
        raise ValueError("depth must be positive")
    return "-".join(tokens[-depth:]) if len(tokens) >= depth else "-".join(tokens)


def build_suffix_batches(
    rules: Iterable[AlarmRule],
    *,
    max_depth: int = 3,
    min_support: int = 3,
    pure_threshold: float = 0.9,
    max_examples: int = 8,
) -> list[EvidenceBatch]:
    """Create suffix-first batches.

    A group is emitted when it is pure enough, reaches max_depth, or cannot be
    split further with meaningful support.
    """
    usable = [rule for rule in rules if rule.tokens]
    return _split_suffix_group(
        usable,
        all_rules=usable,
        depth=1,
        max_depth=max_depth,
        min_support=min_support,
        pure_threshold=pure_threshold,
        max_examples=max_examples,
    )


def _split_suffix_group(
    rules: list[AlarmRule],
    *,
    all_rules: list[AlarmRule],
    depth: int,
    max_depth: int,
    min_support: int,
    pure_threshold: float,
    max_examples: int,
) -> list[EvidenceBatch]:
    groups: dict[str, list[AlarmRule]] = defaultdict(list)
    for rule in rules:
        groups[suffix_pattern(rule.tokens, depth)].append(rule)

    batches: list[EvidenceBatch] = []
    for pattern, grouped in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0])):
        if len(grouped) < min_support:
            continue

        counts = Counter(rule.severity for rule in grouped)
        group_purity = purity(counts)
        can_split = depth < max_depth and any(len(rule.tokens) > depth for rule in grouped)

        if group_purity >= pure_threshold or not can_split:
            batches.append(
                _make_batch("suffix", pattern, grouped, all_rules=all_rules, max_examples=max_examples)
            )
            continue

        child_batches = _split_suffix_group(
            grouped,
            all_rules=all_rules,
            depth=depth + 1,
            max_depth=max_depth,
            min_support=min_support,
            pure_threshold=pure_threshold,
            max_examples=max_examples,
        )
        if child_batches:
            batches.extend(child_batches)
        else:
            batches.append(
                _make_batch("suffix", pattern, grouped, all_rules=all_rules, max_examples=max_examples)
            )

    return batches


def _make_batch(
    pattern_type: str,
    pattern: str,
    rules: list[AlarmRule],
    *,
    all_rules: list[AlarmRule],
    max_examples: int,
) -> EvidenceBatch:
    counts = Counter(rule.severity for rule in rules)
    dom = dominant_severity(counts)
    examples = [
        {"rule": rule.rule, "severity": rule.severity}
        for rule in rules
        if rule.severity == dom
    ][:max_examples]
    counterexamples = [
        {"rule": rule.rule, "severity": rule.severity}
        for rule in rules
        if rule.severity != dom
    ][:max_examples]
    safe_pattern = pattern.replace("/", "_").replace(" ", "_")
    return EvidenceBatch(
        batch_id=f"{pattern_type}__{safe_pattern}",
        pattern_type=pattern_type,
        pattern=pattern,
        support=len(rules),
        severity_distribution=dict(sorted(counts.items())),
        dominant_severity=dom,
        purity=round(purity(counts), 4),
        entropy=round(entropy(counts), 4),
        examples=examples,
        counterexamples=counterexamples,
        structural_context=build_structural_context(rules, all_rules=all_rules),
    )


def build_structural_context(
    rules: list[AlarmRule],
    *,
    all_rules: list[AlarmRule],
    max_items: int = 10,
) -> dict:
    """Summarize full-rule structure inside a batch.

    This gives the distiller more than suffix statistics: repeated prefixes,
    contiguous phrases, and severity-specific token/phrase contrast.
    """
    return {
        "common_prefixes": _top_phrases(
            (
                "-".join(rule.tokens[:depth])
                for rule in rules
                for depth in range(1, min(4, len(rule.tokens)) + 1)
            ),
            max_items=max_items,
        ),
        "common_suffixes": _top_phrases(
            (
                "-".join(rule.tokens[-depth:])
                for rule in rules
                for depth in range(1, min(5, len(rule.tokens)) + 1)
            ),
            max_items=max_items,
        ),
        "common_contiguous_phrases": _top_phrases(
            (
                "-".join(rule.tokens[start : start + size])
                for rule in rules
                for size in range(2, min(5, len(rule.tokens)) + 1)
                for start in range(0, len(rule.tokens) - size + 1)
            ),
            max_items=max_items,
        ),
        "common_tokens": _top_phrases(
            (token for rule in rules for token in rule.tokens),
            max_items=max_items,
        ),
        "severity_contrast": _severity_contrast(rules, max_items=6),
        "structural_neighbors": _structural_neighbors(rules, all_rules, max_items=max_items),
    }


def _top_phrases(values: Iterable[str], *, max_items: int) -> list[dict[str, int | str]]:
    counts = Counter(value for value in values if value)
    return [
        {"phrase": phrase, "count": count}
        for phrase, count in counts.most_common(max_items)
        if count > 1
    ]


def _severity_contrast(rules: list[AlarmRule], *, max_items: int) -> list[dict]:
    by_severity: dict[str, list[AlarmRule]] = defaultdict(list)
    for rule in rules:
        by_severity[rule.severity].append(rule)

    out = []
    for severity, severity_rules in sorted(by_severity.items()):
        other_rules = [rule for rule in rules if rule.severity != severity]
        other_tokens = Counter(token for rule in other_rules for token in set(rule.tokens))
        sev_tokens = Counter(token for rule in severity_rules for token in set(rule.tokens))
        distinctive_tokens = [
            {"token": token, "count": count}
            for token, count in sev_tokens.most_common()
            if count > other_tokens.get(token, 0)
        ][:max_items]

        phrase_counts = Counter(
            "-".join(rule.tokens[start : start + size])
            for rule in severity_rules
            for size in range(2, min(4, len(rule.tokens)) + 1)
            for start in range(0, len(rule.tokens) - size + 1)
        )
        distinctive_phrases = [
            {"phrase": phrase, "count": count}
            for phrase, count in phrase_counts.most_common(max_items)
            if count > 1
        ]

        out.append(
            {
                "severity": severity,
                "support": len(severity_rules),
                "distinctive_tokens": distinctive_tokens,
                "distinctive_phrases": distinctive_phrases,
                "examples": [
                    {"rule": rule.rule, "severity": rule.severity}
                    for rule in severity_rules[:3]
                ],
            }
        )
    return out


def _structural_neighbors(
    batch_rules: list[AlarmRule],
    all_rules: list[AlarmRule],
    *,
    max_items: int,
) -> list[dict]:
    batch_rule_names = {rule.rule for rule in batch_rules}
    candidates = []
    seen_candidates: set[tuple[str, str]] = set()
    for candidate in all_rules:
        if candidate.rule in batch_rule_names:
            continue
        candidate_key = (candidate.rule, candidate.severity)
        if candidate_key in seen_candidates:
            continue
        seen_candidates.add(candidate_key)
        best = max(
            (_structural_similarity(seed.tokens, candidate.tokens) for seed in batch_rules),
            key=lambda item: item["score"],
            default={"score": 0.0},
        )
        if best["score"] >= 0.30:
            candidates.append(
                {
                    "rule": candidate.rule,
                    "severity": candidate.severity,
                    "score": round(best["score"], 4),
                    "shared_phrase": best["shared_phrase"],
                    "prefix_match": best["prefix_match"],
                    "suffix_match": best["suffix_match"],
                }
            )
    return sorted(candidates, key=lambda item: (-item["score"], item["rule"]))[:max_items]


def _structural_similarity(left: list[str], right: list[str]) -> dict:
    shared_phrase_tokens = _longest_common_contiguous(left, right)
    prefix = _common_prefix_len(left, right)
    suffix = _common_suffix_len(left, right)
    token_overlap = len(set(left) & set(right)) / max(len(set(left) | set(right)), 1)
    denom = max(len(left), len(right), 1)
    score = (
        0.45 * (len(shared_phrase_tokens) / denom)
        + 0.30 * (suffix / max(len(left), 1))
        + 0.15 * (prefix / max(len(left), 1))
        + 0.10 * token_overlap
    )
    return {
        "score": score,
        "shared_phrase": "-".join(shared_phrase_tokens),
        "prefix_match": prefix,
        "suffix_match": suffix,
    }


def _longest_common_contiguous(left: list[str], right: list[str]) -> list[str]:
    if not left or not right:
        return []
    previous = [0] * (len(right) + 1)
    best_length = 0
    best_end = 0
    for i, token in enumerate(left, start=1):
        current = [0] * (len(right) + 1)
        for j, other in enumerate(right, start=1):
            if token == other:
                current[j] = previous[j - 1] + 1
                if current[j] > best_length:
                    best_length = current[j]
                    best_end = i
        previous = current
    return left[best_end - best_length : best_end]


def _common_prefix_len(left: list[str], right: list[str]) -> int:
    count = 0
    for a, b in zip(left, right):
        if a != b:
            break
        count += 1
    return count


def _common_suffix_len(left: list[str], right: list[str]) -> int:
    count = 0
    for a, b in zip(reversed(left), reversed(right)):
        if a != b:
            break
        count += 1
    return count


def write_evidence_batches(batches: Iterable[EvidenceBatch], output_dir: str | Path) -> list[Path]:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for batch in batches:
        path = out_dir / f"{batch.batch_id}.json"
        path.write_text(json.dumps(asdict(batch), indent=2), encoding="utf-8")
        paths.append(path)
    return paths


def read_evidence_batch(batch_path: str | Path) -> dict:
    return json.loads(Path(batch_path).read_text(encoding="utf-8"))
