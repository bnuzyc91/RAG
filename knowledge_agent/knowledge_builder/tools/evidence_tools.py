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
        depth=1,
        max_depth=max_depth,
        min_support=min_support,
        pure_threshold=pure_threshold,
        max_examples=max_examples,
    )


def _split_suffix_group(
    rules: list[AlarmRule],
    *,
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
            batches.append(_make_batch("suffix", pattern, grouped, max_examples=max_examples))
            continue

        child_batches = _split_suffix_group(
            grouped,
            depth=depth + 1,
            max_depth=max_depth,
            min_support=min_support,
            pure_threshold=pure_threshold,
            max_examples=max_examples,
        )
        if child_batches:
            batches.extend(child_batches)
        else:
            batches.append(_make_batch("suffix", pattern, grouped, max_examples=max_examples))

    return batches


def _make_batch(
    pattern_type: str,
    pattern: str,
    rules: list[AlarmRule],
    *,
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
    )


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

