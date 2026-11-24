"""scripts/ci_run.py: exactly what the GitHub workflow runs, as a real subprocess."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).parents[2]


def ci_run(out_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/ci_run.py", "--out-dir", str(out_dir), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )


def test_a_clean_bot_matches_the_committed_baseline_and_exits_0(tmp_path: Path) -> None:
    result = ci_run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 newly broken, 0 fixed, 30 unchanged" in result.stdout
    assert "Judge: fake" in result.stdout  # no model was used
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "**No new breakage.**" in summary and "baselines/demo-bot.json" in summary
    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "<h1>0 newly broken, 0 fixed, 30 unchanged</h1>" in html
    assert (tmp_path / "results.json").is_file() and (tmp_path / "bot.log").is_file()


def test_a_misbehaving_bot_fails_the_run_and_names_what_broke(tmp_path: Path) -> None:
    result = ci_run(tmp_path, "--force", "listing_date")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "6 newly broken, 0 fixed, 24 unchanged" in result.stdout
    assert "Result: REGRESSION" in result.stdout
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "**Regression:** 6 scenario(s) broke. This check fails." in summary
    assert "`listing-date-fact: Nova Textiles`" in summary
    data = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert data["comparison"]["has_regression"] is True


def test_the_bot_does_not_inherit_a_bug_from_the_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BUGGY_MODE", "1")
    monkeypatch.setenv("BUGGY_FORCE", "listing_date")
    result = ci_run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
