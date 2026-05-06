"""
EDA + severity prediction for alarm rules.

Inputs
------
master_rules.csv : columns ['Rule', 'Severity']  (~9,900 rows)
new_rules.csv    : column  ['Rule']              (~75 rows)

Output
------
new_rules_predicted.csv with: predicted severity, confidence, method,
                              matched_prefix, matched_suffix, knn_neighbors

Approach
--------
The rule strings are hyphen-separated tokens with a hierarchy:
    <SYSTEM>-<SUBSYSTEM>-<COMPONENT>-<...>-<EVENT-TYPE>
So we build:
  1. a prefix trie keyed on tokens (left-to-right) - your "tree" idea
  2. a suffix trie keyed on tokens (right-to-left)  - because event-type
     suffixes like -FAIL / -TRIP / -GOOSE-QUALITY-BIT-FROM-... often
     determine severity more than the system prefix
  3. a TF-IDF + cosine-kNN over the bag of tokens, as a position-agnostic
     fallback / sanity check.

For each new rule we run all three and ensemble. We surface confidence
and the supporting evidence so you can audit / promote to master.
"""

from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from math import log2
from typing import Iterable

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Visual helpers (shared across tree EDA sections)
# ---------------------------------------------------------------------------
_FILL = "█▓▒░·+"
_CSEV = {                       # ANSI terminal colors per severity
    "High":       "\033[91m",   # bright red
    "Critical":   "\033[95m",   # magenta
    "Medium":     "\033[93m",   # bright yellow
    "Diagnostic": "\033[96m",   # bright cyan
    "Low":        "\033[92m",   # bright green
    "Warning":    "\033[33m",   # orange
}
_RST = "\033[0m"


def _bar(counter: Counter, width: int = 22) -> str:
    """Colored block-char bar + compact distribution. ANSI-safe width tracking."""
    total = sum(counter.values())
    if not total:
        return "[no data]"
    sevs = sorted(counter, key=lambda s: -counter[s])
    bar, vis = "", 0
    for idx, sev in enumerate(sevs):
        n = min(max(1, round(counter[sev] / total * width)), width - vis)
        if n <= 0:
            break
        bar += f"{_CSEV.get(sev, '')}{_FILL[idx % 6] * n}{_RST}"
        vis += n
    bar += " " * (width - vis)      # pad to correct visual width
    dist = "  ".join(f"{s[:3]}={counter[s]}" for s in sevs)
    return f"[{bar}] {dist}  H={entropy(counter):.2f}"


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------
def tokenize(rule: str) -> list[str]:
    """Split on '-', uppercase, drop empties. Mirrors backend normalization."""
    return [t for t in rule.upper().strip().split("-") if t]


# ---------------------------------------------------------------------------
# Trie
# ---------------------------------------------------------------------------
@dataclass
class Node:
    children: dict[str, "Node"] = field(default_factory=dict)
    sev_counts: Counter = field(default_factory=Counter)
    n_rules: int = 0


def build_trie(token_lists: Iterable[list[str]], severities: Iterable[str]) -> Node:
    root = Node()
    for toks, sev in zip(token_lists, severities):
        node = root
        node.sev_counts[sev] += 1
        node.n_rules += 1
        for tok in toks:
            node = node.children.setdefault(tok, Node())
            node.sev_counts[sev] += 1
            node.n_rules += 1
    return root


def entropy(counter: Counter) -> float:
    n = sum(counter.values())
    if n == 0:
        return 0.0
    return -sum((c / n) * log2(c / n) for c in counter.values() if c > 0)


def info_gain(parent: Counter, children: list[Counter]) -> float:
    n = sum(parent.values())
    if n == 0:
        return 0.0
    parent_h = entropy(parent)
    return parent_h - sum((sum(c.values()) / n) * entropy(c) for c in children)


# ---------------------------------------------------------------------------
# 1. Basic EDA
# ---------------------------------------------------------------------------
def basic_eda(master: pd.DataFrame) -> None:
    print("=" * 70)
    print("BASIC EDA")
    print("=" * 70)

    print("\n[Severity distribution]")
    print(master["Severity"].value_counts(dropna=False))
    print(master["Severity"].value_counts(normalize=True).round(3))

    print("\n[Rule length distribution (#tokens)]")
    print(master["n_tokens"].describe().round(2))

    all_tokens = [t for toks in master["tokens"] for t in toks]
    token_freq = Counter(all_tokens)
    print(f"\n[Vocab] unique tokens = {len(token_freq):,}")
    print("Top 20 tokens (by raw frequency):")
    for tok, c in token_freq.most_common(20):
        print(f"  {c:6d}  {tok}")


# ---------------------------------------------------------------------------
# 2. Purity vs depth (does severity get determined as we go deeper?)
# ---------------------------------------------------------------------------
def purity_vs_depth(root: Node, max_depth: int = 20) -> pd.DataFrame:
    by_depth: dict[int, list[tuple[int, float]]] = defaultdict(list)

    def walk(node: Node, depth: int) -> None:
        if depth > max_depth:
            return
        by_depth[depth].append((node.n_rules, entropy(node.sev_counts)))
        for child in node.children.values():
            walk(child, depth + 1)

    walk(root, 0)

    rows = []
    for d in sorted(by_depth):
        items = by_depth[d]
        total = sum(r for r, _ in items)
        if total == 0:
            continue
        weighted_h = sum(r * h for r, h in items) / total
        rows.append({"depth": d, "n_nodes": len(items), "n_rules_covered": total,
                     "weighted_entropy": round(weighted_h, 4)})
    df = pd.DataFrame(rows)
    print("\n[Purity vs depth]  (entropy → 0 means severity is determined)")
    print(df.to_string(index=False))
    return df


# ---------------------------------------------------------------------------
# 3. Decision points - where do children diverge in severity?
# ---------------------------------------------------------------------------
def find_decision_points(root: Node, min_rules: int = 30, top_k: int = 15):
    results = []

    def walk(node: Node, path: list[str]) -> None:
        if node.n_rules >= min_rules and node.children:
            ig = info_gain(node.sev_counts, [c.sev_counts for c in node.children.values()])
            if ig > 0:
                results.append((ig, node.n_rules, path, dict(node.sev_counts),
                                [(t, dict(c.sev_counts)) for t, c in node.children.items()]))
        for tok, child in node.children.items():
            walk(child, path + [tok])

    walk(root, [])
    results.sort(key=lambda x: (-x[0], -x[1]))

    print(f"\n[Top {top_k} decision points - branches with biggest severity divergence]")
    for ig, n, path, parent_dist, children in results[:top_k]:
        prefix = "-".join(path) if path else "<ROOT>"
        print(f"\n  prefix='{prefix}'  n={n}  info_gain={ig:.3f}")
        print(f"    parent dist: {parent_dist}")
        # show top 3 children sorted by size
        for tok, dist in sorted(children, key=lambda x: -sum(x[1].values()))[:3]:
            print(f"    +{tok:30s} -> {dist}")
    return results[:top_k]


# ---------------------------------------------------------------------------
# 4. Pure branches - prefixes where severity is essentially determined
# ---------------------------------------------------------------------------
def find_pure_branches(root: Node, min_rules: int = 5, max_entropy: float = 0.2):
    results = []

    def walk(node: Node, path: list[str]) -> None:
        if node.n_rules >= min_rules and entropy(node.sev_counts) <= max_entropy and path:
            sev, _ = node.sev_counts.most_common(1)[0]
            results.append((node.n_rules, "-".join(path), sev, dict(node.sev_counts)))
            return  # stop descending - already pure
        for tok, child in node.children.items():
            walk(child, path + [tok])

    walk(root, [])
    results.sort(key=lambda x: -x[0])
    print(f"\n[Pure prefix branches]  (>= {min_rules} rules, entropy <= {max_entropy})")
    print(f"  found {len(results)} branches; showing top 25 by support:")
    for n, prefix, sev, dist in results[:25]:
        print(f"  {n:5d}  {sev:12s}  {prefix}")
    return results


# ---------------------------------------------------------------------------
# 5. Token mutual information (position-agnostic discriminators)
# ---------------------------------------------------------------------------
def token_mutual_info(master: pd.DataFrame, top_k: int = 25) -> pd.DataFrame:
    """For each token, how informative is its presence about severity?"""
    sev_counts = master["Severity"].value_counts()
    N = len(master)
    p_sev = {s: c / N for s, c in sev_counts.items()}

    # token -> Counter(severity)
    token_sev = defaultdict(Counter)
    token_total = Counter()
    for toks, sev in zip(master["tokens"], master["Severity"]):
        for t in set(toks):
            token_sev[t][sev] += 1
            token_total[t] += 1

    rows = []
    for tok, total in token_total.items():
        if total < 10:  # ignore rare tokens
            continue
        p_t = total / N
        mi = 0.0
        for sev, p_s in p_sev.items():
            joint = token_sev[tok][sev] / N
            if joint > 0:
                mi += joint * log2(joint / (p_t * p_s))
        # dominant severity given token
        dom_sev, dom_n = token_sev[tok].most_common(1)[0]
        rows.append({"token": tok, "n_rules_with_token": total,
                     "mutual_info": round(mi, 4),
                     "dominant_severity": dom_sev,
                     "dominant_share": round(dom_n / total, 3)})

    df = pd.DataFrame(rows).sort_values("mutual_info", ascending=False)
    print(f"\n[Top {top_k} most-discriminative tokens (mutual information w/ severity)]")
    print(df.head(top_k).to_string(index=False))
    return df


# ---------------------------------------------------------------------------
# 7. Full prefix-trie ASCII tree
# ---------------------------------------------------------------------------
def print_ascii_trie(
    root: Node,
    *,
    max_depth: int = 7,
    min_rules: int = 3,
    max_children: int = 6,
) -> None:
    """
    Render the prefix trie as an indented ASCII tree (like the `tree` command).

    Each level = one token deeper in the hyphen-separated rule string.
    Nodes whose severity is already determined (entropy < 0.05) are printed
    as leaves marked ◄PURE so the tree stays readable.
    """
    print("\n" + "=" * 70)
    print("7. PREFIX-TRIE TREE  (each level = one hyphen-token deeper)")
    print("   Bar: different fill char per severity, sorted high→low count")
    print("   H=entropy  0=pure  1=50-50 split (2 classes)  ◄PURE = leaf")
    print("=" * 70)

    def _walk(node: Node, label: str, depth: int, gprefix: str, last: bool) -> None:
        h = entropy(node.sev_counts)
        conn = "└── " if last else "├── "
        bar = _bar(node.sev_counts)

        if depth == 0:
            print(f"ROOT  n={node.n_rules}  {bar}")
        else:
            pure = ""
            if h < 0.05 and node.n_rules:
                dom = node.sev_counts.most_common(1)[0][0]
                pure = f"  ◄PURE:{_CSEV.get(dom,'')}{dom}{_RST}"
            print(f"{gprefix}{conn}{label}  n={node.n_rules}  {bar}{pure}")

        if h < 0.05:        # already determined — stop descending
            return
        if depth >= max_depth:
            ext = gprefix + ("    " if last else "│   ")
            if node.children:
                print(f"{ext}└── … ({len(node.children)} children, depth limit)")
            return

        child_pfx = gprefix + ("    " if (last or depth == 0) else "│   ")
        eligible = sorted(
            [(t, c) for t, c in node.children.items() if c.n_rules >= min_rules],
            key=lambda x: -x[1].n_rules,
        )
        shown = eligible[:max_children]
        hidden = len(eligible) - len(shown)
        for i, (tok, child) in enumerate(shown):
            _walk(child, tok, depth + 1, child_pfx,
                  last=(i == len(shown) - 1 and hidden == 0))
        if hidden:
            print(f"{child_pfx}└── … {hidden} more branches (≥{min_rules} rules each)")

    _walk(root, "ROOT", 0, "", True)


# ---------------------------------------------------------------------------
# 8. Divergence tree — decision-tree style
# ---------------------------------------------------------------------------
def print_divergence_tree(
    root: Node,
    *,
    min_rules: int = 5,
    pure_entropy: float = 0.15,
    max_depth: int = 12,
) -> None:
    """
    Show only nodes where severity is still uncertain; branches collapse to a
    leaf (→ [Severity]) the moment they become pure enough or drop below
    min_rules.

    Read it like a decision tree: follow any path from ROOT to its →
    terminal to see what severity the algorithm would predict.
    """
    print("\n" + "=" * 70)
    print("8. DIVERGENCE TREE  (decision-tree style)")
    print(f"   Branches fold to leaves when H < {pure_entropy} or n < {min_rules}")
    print("   → [Severity] = prediction at that branch")
    print("=" * 70)

    def _walk(node: Node, label: str, depth: int, gprefix: str, last: bool) -> None:
        h = entropy(node.sev_counts)
        conn = "└── " if last else "├── "

        # Leaf: pure enough or too small
        if depth > 0 and (h < pure_entropy or node.n_rules < min_rules):
            dom, dom_n = node.sev_counts.most_common(1)[0]
            purity = dom_n / max(sum(node.sev_counts.values()), 1)
            col = _CSEV.get(dom, "")
            print(f"{gprefix}{conn}{label}  "
                  f"→  {col}[{dom}]{_RST}  n={node.n_rules}  purity={purity:.0%}")
            return

        bar = _bar(node.sev_counts, width=16)
        if depth == 0:
            print(f"ROOT  n={node.n_rules}  {bar}")
        else:
            print(f"{gprefix}{conn}{label}  n={node.n_rules}  {bar}")

        if depth >= max_depth:
            child_pfx = gprefix + ("    " if last else "│   ")
            print(f"{child_pfx}└── … (depth limit)")
            return

        child_pfx = gprefix + ("    " if (last or depth == 0) else "│   ")
        eligible = sorted(
            [(t, c) for t, c in node.children.items() if c.n_rules >= min_rules],
            key=lambda x: -x[1].n_rules,
        )
        for i, (tok, child) in enumerate(eligible):
            _walk(child, tok, depth + 1, child_pfx, last=(i == len(eligible) - 1))

        # Summarise small branches that were pruned
        small: Counter = Counter()
        for _, c in node.children.items():
            if c.n_rules < min_rules:
                small.update(c.sev_counts)
        if small:
            dom = small.most_common(1)[0][0]
            n_small = sum(small.values())
            print(f"{child_pfx}└── … ({n_small} rules in small branches, "
                  f"dominant={_CSEV.get(dom,'')}{dom}{_RST})")

    _walk(root, "ROOT", 0, "", True)


# ---------------------------------------------------------------------------
# 9. Token-position entropy profile
# ---------------------------------------------------------------------------
def token_position_entropy(master: pd.DataFrame, max_pos: int = 20) -> None:
    """
    For each position index in the tokenized rule, compute the entropy of
    severity among all rules that have a token there.

    Low entropy at position P  →  knowing token[P] is usually enough to
    determine severity — this is where the algorithm should split first.
    """
    pos_sev: dict[int, Counter] = defaultdict(Counter)
    pos_tok: dict[int, Counter] = defaultdict(Counter)
    for toks, sev in zip(master["tokens"], master["Severity"]):
        for i, tok in enumerate(toks):
            pos_sev[i][sev] += 1
            pos_tok[i][tok] += 1

    print("\n" + "=" * 70)
    print("9. TOKEN POSITION ENTROPY PROFILE")
    print("   Which index in RULE-TOK0-TOK1-TOK2-... best predicts severity?")
    print("   Low H at position P → token[P] alone ≈ determines severity")
    print("=" * 70)
    print(f"  {'Pos':>3}  {'n':>6}  {'H (bar out of 10)':18}  "
          f"{'Dom severity':>14}  {'Purity':>7}  Top-3 tokens")
    print("  " + "-" * 90)

    for pos in range(min(max_pos, max(pos_sev) + 1)):
        if pos not in pos_sev:
            continue
        c = pos_sev[pos]
        n = sum(c.values())
        h = entropy(c)
        dom, dom_n = c.most_common(1)[0]
        top3 = ", ".join(f"{t}({cnt})" for t, cnt in pos_tok[pos].most_common(3))
        h_bar = "▓" * int(round(h * 10))
        col = _CSEV.get(dom, "")
        print(f"  {pos:>3}  {n:>6}  {h_bar:<18}  "
              f"{col}{dom:>14}{_RST}  {dom_n/n:>7.1%}  {top3}")


# ---------------------------------------------------------------------------
# 10. Severity profiles by top-N-token prefix
# ---------------------------------------------------------------------------
def prefix_severity_profiles(master: pd.DataFrame, depth: int = 2) -> None:
    """
    Group rules by their first `depth` tokens and show the severity
    distribution for each group.

    Reveals which system/subsystem combos are 'owned' by one severity
    (safe to hard-code) vs genuinely mixed (need deeper token analysis).
    """
    df = master.copy()
    df["pfx"] = df["tokens"].apply(
        lambda t: "-".join(t[:depth]) if len(t) >= depth else "-".join(t)
    )
    grouped = (
        df.groupby("pfx")["Severity"]
        .value_counts()
        .unstack(fill_value=0)
    )

    rows = []
    for pfx, row in grouped.iterrows():
        total = int(row.sum())
        c = Counter(row.to_dict())
        h = entropy(c)
        dom = row.idxmax()
        rows.append((total, pfx, dom, h, c))
    rows.sort(key=lambda x: -x[0])

    print("\n" + "=" * 70)
    print(f"10. SEVERITY PROFILES — FIRST-{depth}-TOKEN PREFIX")
    print("    Each row = distinct system+subsystem combo")
    print("    ◄PURE = every rule in this prefix shares one severity")
    print("=" * 70)
    for total, pfx, dom, h, c in rows:
        bar = _bar(c, width=20)
        pure_tag = ""
        if h < 0.05:
            col = _CSEV.get(dom, "")
            pure_tag = f"  ◄PURE:{col}{dom}{_RST}"
        print(f"  n={total:4d}  {pfx:<55}  {bar}{pure_tag}")


# ---------------------------------------------------------------------------
# 11. Subtree explorer — drill into any node by token path
# ---------------------------------------------------------------------------
def explore_subtree(
    root: Node,
    path: "str | list[str]",
    *,
    max_depth: int = 6,
    min_rules: int = 3,
    max_children: int = 8,
    show_ascii: bool = True,
    show_divergence: bool = True,
    pure_entropy: float = 0.15,
) -> "Node | None":
    """
    Navigate to a subtree by token path and display it.

    path can be:
      - a hyphen-string  "POWER-PANEL"
      - a list           ["POWER", "PANEL"]

    Returns the subtree Node so you can pass it to plot_trie_tree().

    Examples
    --------
        node = explore_subtree(pref_root, "POWER")
        node = explore_subtree(pref_root, "MEDIUM-VOLTAGE-DISTRIBUTION")
        explore_subtree(suf_root, "GENERATOR")   # suffix trie view
    """
    if isinstance(path, str):
        path_tokens = [t for t in path.upper().strip().split("-") if t]
    else:
        path_tokens = [t.upper() for t in path]

    node = root
    resolved: list[str] = []

    for tok in path_tokens:
        if tok not in node.children:
            avail = sorted(node.children.items(), key=lambda x: -x[1].n_rules)
            pfx = "-".join(resolved) or "ROOT"
            print(f"\n[!] Token '{tok}' not found under '{pfx}'.")
            print(f"    Children of '{pfx}' (top 10 by rule count):")
            for t, c in avail[:10]:
                print(f"      {t:30s}  n={c.n_rules}  {_bar(c.sev_counts, width=14)}")
            return None
        node = node.children[tok]
        resolved.append(tok)

    path_str = "-".join(resolved)
    h = entropy(node.sev_counts)
    print(f"\n{'='*70}")
    print(f"SUBTREE EXPLORER: '{path_str}'")
    print(f"  n={node.n_rules}  H={h:.3f}  {_bar(node.sev_counts, width=20)}")
    print(f"{'='*70}")

    if show_ascii:
        print_ascii_trie(node, max_depth=max_depth, min_rules=min_rules,
                         max_children=max_children)
    if show_divergence:
        print_divergence_tree(node, min_rules=min_rules, pure_entropy=pure_entropy,
                              max_depth=max_depth)

    # Show available children as hints for the next drill
    avail = sorted(node.children.items(), key=lambda x: -x[1].n_rules)
    if avail:
        print(f"\n[Drill deeper — children of '{path_str}']")
        for tok, child in avail[:12]:
            print(f"  explore_subtree(root, '{path_str}-{tok}')  "
                  f"n={child.n_rules}  {_bar(child.sev_counts, width=12)}")

    return node


# ---------------------------------------------------------------------------
# 12. Top-to-bottom graphical tree (requires matplotlib)
# ---------------------------------------------------------------------------
_PLOT_COLORS = {
    "High":       "#ff6b6b",
    "Critical":   "#cc44cc",
    "Medium":     "#ffd93d",
    "Diagnostic": "#74c7d4",
    "Low":        "#74d490",
}
_PLOT_DEFAULT = "#bbbbbb"


def _layout_tree(
    node: Node,
    max_depth: int,
    min_rules: int,
    depth: int = 0,
    x_offset: float = 0.0,
) -> "tuple[dict[int, tuple[float, float]], float]":
    """
    Reingold-Tilford-style layout.
    Returns ({node_id: (x_center, y)}, total_width).
    y = -depth so root sits at the top when plotted.
    """
    eligible = sorted(
        [(t, c) for t, c in node.children.items() if c.n_rules >= min_rules],
        key=lambda x: -x[1].n_rules,
    )

    if not eligible or depth >= max_depth:
        return {id(node): (x_offset + 0.5, float(-depth))}, 1.0

    positions: dict[int, tuple[float, float]] = {}
    x_cursor = x_offset
    child_centers: list[float] = []

    for _, child in eligible:
        child_pos, child_w = _layout_tree(child, max_depth, min_rules, depth + 1, x_cursor)
        positions.update(child_pos)
        child_centers.append(positions[id(child)][0])
        x_cursor += child_w

    node_x = (child_centers[0] + child_centers[-1]) / 2
    positions[id(node)] = (node_x, float(-depth))
    return positions, x_cursor - x_offset


def plot_trie_tree(
    root: Node,
    path: "str | list[str] | None" = None,
    *,
    max_depth: int = 5,
    min_rules: int = 5,
    figsize: "tuple[int, int] | None" = None,
    save_to: "str | None" = None,
    title: "str | None" = None,
) -> None:
    """
    Draw the trie as a top-to-bottom graphical tree (requires matplotlib).

    Visual encoding
    ---------------
    Box COLOR   = dominant severity of that branch
    Box OPACITY = purity  (fully solid = one severity, faded = mixed)
    Mini bar    = stacked severity split inside each box

    Parameters
    ----------
    root      : pref_root or suf_root
    path      : optional subtree start, e.g. "POWER" or "MEDIUM-VOLTAGE"
    max_depth : levels to draw (5 is usually readable; more → wider)
    min_rules : prune branches with fewer rules (raise to simplify)
    save_to   : save PNG instead of plt.show(), e.g. "trie.png"

    Examples
    --------
        plot_trie_tree(pref_root)                            # full tree
        plot_trie_tree(pref_root, "POWER", max_depth=5)     # POWER subtree
        plot_trie_tree(pref_root, save_to="trie_full.png")  # save to file
        plot_trie_tree(suf_root, max_depth=4)               # suffix tree
    """
    try:
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        from matplotlib.patches import FancyBboxPatch
    except ImportError:
        print("matplotlib not installed.  Run:  pip install matplotlib")
        return

    # Navigate to subtree
    node = root
    path_label = "ROOT"
    if path:
        tokens = [t.upper() for t in (path if isinstance(path, list)
                                       else path.upper().split("-")) if t]
        for tok in tokens:
            if tok not in node.children:
                avail = sorted(node.children, key=lambda t: -node.children[t].n_rules)[:8]
                print(f"Token '{tok}' not found. Available: {avail}")
                return
            node = node.children[tok]
        path_label = "-".join(tokens)

    # Compute layout
    positions, _ = _layout_tree(node, max_depth, min_rules)

    # Collect node metadata (label + parent linkage)
    info: dict[int, tuple[str, Node, int, "int | None"]] = {}

    def _collect(n: Node, label: str, depth: int, parent_nid: "int | None") -> None:
        nid = id(n)
        if nid not in positions:
            return
        info[nid] = (label, n, depth, parent_nid)
        if depth < max_depth:
            for tok, child in sorted(
                n.children.items(), key=lambda x: -x[1].n_rules
            ):
                if child.n_rules >= min_rules:
                    _collect(child, tok, depth + 1, nid)

    _collect(node, path_label, 0, None)

    if not info:
        print("No nodes to plot. Try lowering min_rules or raising max_depth.")
        return

    # Auto-size figure
    node_w, node_h = 1.2, 0.55
    xs = [positions[nid][0] for nid in info]
    ys = [positions[nid][1] for nid in info]
    if figsize is None:
        fw = max(10, min((max(xs) - min(xs) + 2) * node_w * 0.85, 36))
        fh = max(6, (abs(min(ys)) + 1.5) * 1.9)
        figsize = (int(fw), int(fh))

    fig, ax = plt.subplots(figsize=figsize)
    ax.axis("off")

    # ---- Edges ----
    for nid, (_, _, _, parent_nid) in info.items():
        if parent_nid is not None:
            px, py = positions[parent_nid]
            cx, cy = positions[nid]
            ax.plot([px, cx], [py - node_h / 2 - 0.02, cy + node_h / 2 + 0.02],
                    color="#888888", lw=0.7, alpha=0.5, zorder=1)

    # ---- Nodes ----
    for nid, (label, n, _, _) in info.items():
        x, y = positions[nid]
        total = sum(n.sev_counts.values())
        if not total:
            continue

        dom_sev, dom_n = n.sev_counts.most_common(1)[0]
        h = entropy(n.sev_counts)
        purity = dom_n / total
        color = _PLOT_COLORS.get(dom_sev, _PLOT_DEFAULT)

        # Faded = mixed severity;  solid = pure
        rect = FancyBboxPatch(
            (x - node_w / 2, y - node_h / 2), node_w, node_h,
            boxstyle="round,pad=0.04",
            facecolor=color, alpha=0.25 + 0.75 * purity,
            edgecolor="#444444", linewidth=0.7, zorder=2,
        )
        ax.add_patch(rect)

        # Stacked severity mini-bar at the bottom of the box
        bw, bx = node_w - 0.14, x - (node_w - 0.14) / 2
        bar_y = y - node_h / 2 + 0.04
        for sev, cnt in n.sev_counts.most_common():
            seg = (cnt / total) * bw
            ax.barh(bar_y, seg, height=0.07, left=bx,
                    color=_PLOT_COLORS.get(sev, _PLOT_DEFAULT), alpha=0.95, zorder=3)
            bx += seg

        # Token label + stats
        short = (label[:13] + "…") if len(label) > 14 else label
        ax.text(x, y + 0.10, short,
                ha="center", va="center", fontsize=6.0, fontweight="bold", zorder=4)
        ax.text(x, y - 0.10, f"n={n.n_rules}  H={h:.2f}",
                ha="center", va="center", fontsize=4.8, color="#333333", zorder=4)

    # ---- Legend ----
    present = {info[nid][1].sev_counts.most_common(1)[0][0]
               for nid in info if info[nid][1].sev_counts}
    handles = [mpatches.Patch(color=_PLOT_COLORS.get(s, _PLOT_DEFAULT), label=s)
               for s in _PLOT_COLORS if s in present]
    handles.append(mpatches.Patch(facecolor="white", edgecolor="black",
                                   alpha=0.35, label="faded=mixed  solid=pure"))
    ax.legend(handles=handles, loc="upper right", fontsize=7,
              title="Severity  (opacity = purity)", title_fontsize=7)

    ax.set_xlim(min(xs) - node_w, max(xs) + node_w)
    ax.set_ylim(min(ys) - node_h, max(ys) + node_h + 0.4)
    fig.suptitle(
        title or f"Prefix Trie  —  root: '{path_label}'  "
                 f"(max_depth={max_depth}, min_rules={min_rules})",
        fontsize=9,
    )
    plt.tight_layout()

    if save_to:
        plt.savefig(save_to, dpi=150, bbox_inches="tight")
        print(f"Saved → {save_to}")
    else:
        plt.show()


# ---------------------------------------------------------------------------
# 13. Suffix-trie convenience helpers
# ---------------------------------------------------------------------------
def explore_suffix(
    suf_root: Node,
    end_pattern: "str | list[str]",
    **kwargs,
) -> "Node | None":
    """
    Explore the SUFFIX trie starting from a natural-order end pattern.

    The suffix trie stores tokens RIGHT-TO-LEFT, so "COOLING-MODE" (the last
    two words of a rule) becomes the path MODE → COOLING inside suf_root.
    This wrapper reverses the pattern for you, so you can type the tokens
    as they appear in the rule (left-to-right).

    Parameters
    ----------
    suf_root    : the suffix trie (built with reversed tokens)
    end_pattern : last N tokens of a rule in NATURAL order,
                  e.g. "COOLING-MODE"  or  "FREE-COOLING-MODE"

    Examples
    --------
        explore_suffix(suf_root, "COOLING-MODE")
        explore_suffix(suf_root, "FREE-COOLING-MODE-FREE-COOLING-MODE")
        explore_suffix(suf_root, "GENERATOR")

    The children shown at the bottom tell you what comes BEFORE this suffix
    in the rule — keep drilling to trace the rule back toward its start.
    """
    if isinstance(end_pattern, str):
        tokens = [t for t in end_pattern.upper().strip().split("-") if t]
    else:
        tokens = [t.upper() for t in end_pattern]

    reversed_path = list(reversed(tokens))
    print(f"\n[suffix lookup]  natural order: '{'-'.join(tokens)}'")
    print(f"                 reversed path into suf_root: '{'-'.join(reversed_path)}'")
    return explore_subtree(suf_root, reversed_path, **kwargs)


def plot_suffix_tree(
    suf_root: Node,
    end_pattern: "str | list[str] | None" = None,
    **kwargs,
) -> None:
    """
    Plot the SUFFIX trie as a top-to-bottom graphical tree.

    end_pattern is in natural reading order (right portion of the rule).
    The function reverses it before navigating into suf_root.

    Examples
    --------
        plot_suffix_tree(suf_root)                          # full suffix tree
        plot_suffix_tree(suf_root, "COOLING-MODE")          # suffix subtree
        plot_suffix_tree(suf_root, "FREE-COOLING-MODE",
                         max_depth=6, save_to="suf.png")
    """
    if end_pattern is not None:
        if isinstance(end_pattern, str):
            tokens = [t for t in end_pattern.upper().strip().split("-") if t]
        else:
            tokens = [t.upper() for t in end_pattern]
        reversed_path = list(reversed(tokens))
        print(f"[suffix lookup]  natural: '{'-'.join(tokens)}'  "
              f"→  reversed path: '{'-'.join(reversed_path)}'")
        plot_trie_tree(suf_root, reversed_path, **kwargs)
    else:
        plot_trie_tree(suf_root, **kwargs)


# ---------------------------------------------------------------------------
# 6. Prediction
# ---------------------------------------------------------------------------
def predict_with_trie(tokens: list[str], root: Node, min_support: int = 5):
    """Walk as deep as possible while node has >= min_support rules.
    Return (severity, confidence, matched_path_str, support_dist)."""
    node = root
    path: list[str] = []
    last_good = (root, [])
    for tok in tokens:
        if tok not in node.children:
            break
        node = node.children[tok]
        path.append(tok)
        if node.n_rules >= min_support:
            last_good = (node, list(path))
    final, final_path = last_good
    total = sum(final.sev_counts.values())
    if total == 0:
        return None, 0.0, "", {}
    sev, c = final.sev_counts.most_common(1)[0]
    return sev, c / total, "-".join(final_path), dict(final.sev_counts)


def knn_predict(master: pd.DataFrame, new_rules: pd.DataFrame, k: int = 5):
    """TF-IDF over tokens + cosine kNN. Returns list of (sev, conf, neighbors)."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.neighbors import NearestNeighbors

    vec = TfidfVectorizer(analyzer="word", token_pattern=r"[^ ]+", lowercase=False)
    X_master = vec.fit_transform(master["tokens"].apply(" ".join))
    X_new = vec.transform(new_rules["tokens"].apply(" ".join))

    nn = NearestNeighbors(n_neighbors=min(k, len(master)), metric="cosine").fit(X_master)
    dists, idxs = nn.kneighbors(X_new)

    out = []
    master_sevs = master["Severity"].to_numpy()
    master_rules = master["Rule"].to_numpy()
    for i in range(len(new_rules)):
        neigh_sevs = master_sevs[idxs[i]]
        sev, count = Counter(neigh_sevs).most_common(1)[0]
        # weight by similarity (1 - cosine distance)
        sims = 1 - dists[i]
        weights_by_sev = defaultdict(float)
        for s, w in zip(neigh_sevs, sims):
            weights_by_sev[s] += w
        weighted_sev = max(weights_by_sev, key=weights_by_sev.get)
        weighted_conf = weights_by_sev[weighted_sev] / sum(weights_by_sev.values())
        neighbors = [(master_rules[idxs[i][j]], master_sevs[idxs[i][j]],
                      round(float(sims[j]), 3)) for j in range(len(idxs[i]))]
        out.append({"sev": weighted_sev, "conf": round(weighted_conf, 3),
                    "neighbors": neighbors})
    return out


def predict_all(master: pd.DataFrame, new_rules: pd.DataFrame) -> pd.DataFrame:
    pref_root = build_trie(master["tokens"], master["Severity"])
    suf_root = build_trie(master["tokens"].apply(lambda t: list(reversed(t))),
                          master["Severity"])

    knn = knn_predict(master, new_rules, k=5)

    rows = []
    for i, rule in enumerate(new_rules["Rule"]):
        toks = new_rules["tokens"].iloc[i]
        p_sev, p_conf, p_path, p_dist = predict_with_trie(toks, pref_root)
        s_sev, s_conf, s_path, s_dist = predict_with_trie(list(reversed(toks)), suf_root)
        k_sev, k_conf = knn[i]["sev"], knn[i]["conf"]

        # Ensemble: weighted vote between three predictors
        votes = Counter()
        for sev, conf in [(p_sev, p_conf), (s_sev, s_conf), (k_sev, k_conf)]:
            if sev is not None:
                votes[sev] += conf
        if votes:
            final_sev, final_score = votes.most_common(1)[0]
            final_conf = final_score / sum(votes.values())
        else:
            final_sev, final_conf = None, 0.0

        agree = len({p_sev, s_sev, k_sev} - {None})
        method = "all3_agree" if agree == 1 else f"split_{agree}way"

        rows.append({
            "Rule": rule,
            "predicted_severity": final_sev,
            "confidence": round(final_conf, 3),
            "method": method,
            "prefix_pred": p_sev, "prefix_conf": round(p_conf, 3), "prefix_match": p_path,
            "suffix_pred": s_sev, "suffix_conf": round(s_conf, 3),
            "suffix_match": "-".join(reversed(s_path.split("-"))) if s_path else "",
            "knn_pred": k_sev, "knn_conf": round(k_conf, 3),
            "knn_top_neighbor": knn[i]["neighbors"][0][0] if knn[i]["neighbors"] else "",
            "knn_top_sim": knn[i]["neighbors"][0][2] if knn[i]["neighbors"] else 0.0,
        })

    return pd.DataFrame(rows).sort_values(["confidence", "method"], ascending=[False, True])


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", default="master_rules.csv",
                    help="CSV with columns Rule, Severity")
    ap.add_argument("--new", default="new_rules.csv",
                    help="CSV with column Rule")
    ap.add_argument("--out", default="new_rules_predicted.csv")
    args = ap.parse_args()

    master = pd.read_csv(args.master)
    master = master.dropna(subset=["Rule", "Severity"]).copy()
    master["tokens"] = master["Rule"].apply(tokenize)
    master["n_tokens"] = master["tokens"].apply(len)

    new_rules = pd.read_csv(args.new)
    new_rules = new_rules.dropna(subset=["Rule"]).copy()
    new_rules["tokens"] = new_rules["Rule"].apply(tokenize)

    # ---- EDA ----
    basic_eda(master)
    pref_root = build_trie(master["tokens"], master["Severity"])
    purity_vs_depth(pref_root)
    find_decision_points(pref_root, min_rules=30, top_k=15)
    find_pure_branches(pref_root, min_rules=5, max_entropy=0.2)

    # Suffix view
    print("\n" + "=" * 70)
    print("SUFFIX-TRIE VIEW (tokens reversed)")
    print("=" * 70)
    suf_root = build_trie(master["tokens"].apply(lambda t: list(reversed(t))),
                          master["Severity"])
    purity_vs_depth(suf_root)
    find_pure_branches(suf_root, min_rules=5, max_entropy=0.2)

    token_mutual_info(master, top_k=25)

    # ---- Tree-view EDA (sections 7-10) ----
    print_ascii_trie(pref_root, max_depth=7, min_rules=3, max_children=6)
    print_divergence_tree(pref_root, min_rules=5, pure_entropy=0.15)
    token_position_entropy(master, max_pos=20)
    prefix_severity_profiles(master, depth=2)
    prefix_severity_profiles(master, depth=3)

    print("\n" + "=" * 70)
    print("SUFFIX DIVERGENCE TREE  (reversed tokens — event-type suffix view)")
    print("=" * 70)
    print_divergence_tree(suf_root, min_rules=3, pure_entropy=0.15)

    # ---- Subtree explorer (uncomment to drill into a specific branch) ----
    # explore_subtree(pref_root, "POWER")
    # explore_subtree(pref_root, "MEDIUM-VOLTAGE-DISTRIBUTION")
    # explore_subtree(pref_root, "POWER-PANEL-MEDIUM-VOLTAGE-DISTRIBUTION")
    # explore_subtree(suf_root, "GENERATOR")   # suffix trie: rules ending w/ GENERATOR

    # ---- Graphical top-to-bottom tree (requires: pip install matplotlib) ----
    # plot_trie_tree(pref_root)                               # full prefix tree
    # plot_trie_tree(pref_root, "POWER", max_depth=5)        # POWER subtree only
    # plot_trie_tree(pref_root, save_to="trie_prefix.png")   # save instead of show
    # plot_trie_tree(suf_root,  save_to="trie_suffix.png")   # suffix tree

    # ---- Predict ----
    print("\n" + "=" * 70)
    print("PREDICTIONS FOR NEW RULES")
    print("=" * 70)
    pred = predict_all(master, new_rules)
    pred.to_csv(args.out, index=False)

    print(pred[["Rule", "predicted_severity", "confidence", "method"]]
          .to_string(index=False))
    print(f"\nWrote {len(pred)} predictions -> {args.out}")
    low = pred[pred["confidence"] < 0.7]
    print(f"\n{len(low)} rules below 0.7 confidence -- manual review recommended:")
    print(low[["Rule", "predicted_severity", "confidence",
               "prefix_pred", "suffix_pred", "knn_pred"]].to_string(index=False))


if __name__ == "__main__":
    main()
