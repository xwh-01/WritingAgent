from __future__ import annotations

from pathlib import Path

from evals.run_eval import CASES_DIR, run_all


def test_longform_evals_pass(tmp_path: Path) -> None:
    report_path = tmp_path / "report.md"
    results = run_all(CASES_DIR, report_path)

    assert results
    assert all(result.passed for result in results)
    assert "Hit Rate" in report_path.read_text(encoding="utf-8")
