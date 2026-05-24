from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from knowledge_builder.tools.evidence_tools import (  # noqa: E402
    build_suffix_batches,
    load_rules_csv,
    read_evidence_batch,
    write_evidence_batches,
)
from knowledge_builder.tools.fragment_tools import render_template_fragment  # noqa: E402
from knowledge_builder.tools.graph_context_tools import (  # noqa: E402
    attach_graph_context,
    write_sibling_conflict_report,
)
from knowledge_builder.tools.validation_tools import parse_frontmatter  # noqa: E402


class GraphContextToolsTest(unittest.TestCase):
    def test_graph_context_and_sibling_conflict_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            master_path = root / "master.csv"
            master_path.write_text(
                "\n".join(
                    [
                        "Rule,Severity",
                        "A-ALARM,Diagnostic",
                        "B-ALARM,Diagnostic",
                        "A-POWER-FAIL-ALARM,High",
                        "B-POWER-FAIL-ALARM,High",
                        "C-COMMUNICATION-FAIL-ALARM,Diagnostic",
                        "D-COMMUNICATION-FAIL-ALARM,Medium",
                        "E-COMMUNICATION-FAIL-ALARM,Medium",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            rules = load_rules_csv(master_path)
            batches = build_suffix_batches(
                rules,
                max_depth=3,
                min_support=1,
                pure_threshold=0.95,
                max_batch_support=0,
                min_split_support=0,
                min_information_gain=0.0,
                min_child_coverage=0.0,
            )
            evidence_dir = root / "evidence_batches"
            batch_paths = write_evidence_batches(batches, evidence_dir)
            attach_graph_context(batch_paths)

            comm = read_evidence_batch(evidence_dir / "suffix__COMMUNICATION-FAIL-ALARM.json")
            self.assertEqual(comm["graph_context"]["parent_key"], "FAIL-ALARM")
            self.assertIn("suffix__POWER-FAIL-ALARM", comm["graph_context"]["sibling_batch_ids"])

            ancestor_patterns = [
                item["pattern"]
                for item in comm["hierarchical_context"]["ancestor_summaries"]
            ]
            self.assertEqual(ancestor_patterns, ["ALARM", "FAIL-ALARM"])

            fragments = []
            for index, batch_id in enumerate(
                ["suffix__COMMUNICATION-FAIL-ALARM", "suffix__POWER-FAIL-ALARM"],
                start=1,
            ):
                evidence = read_evidence_batch(evidence_dir / f"{batch_id}.json")
                markdown = render_template_fragment(evidence)
                metadata = parse_frontmatter(markdown)
                metadata["ai_rule_id"] = f"AIRULE-{index:06d}"
                fragments.append(
                    {
                        "path": str(root / f"{batch_id}.md"),
                        "metadata": metadata,
                        "markdown": markdown,
                    }
                )

            report_path = write_sibling_conflict_report(
                fragments,
                evidence_dir,
                root / "sibling_conflict_report.md",
            )
            report = report_path.read_text(encoding="utf-8")
            self.assertIn("Sibling Default Conflict: FAIL-ALARM", report)
            self.assertIn("COMMUNICATION-FAIL-ALARM", report)
            self.assertIn("POWER-FAIL-ALARM", report)


if __name__ == "__main__":
    unittest.main()
