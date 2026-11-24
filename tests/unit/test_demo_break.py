"""scripts/demo_break.py: the one-word bug switch used in the GitHub demo."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "demo_break.py"
AGENT = ROOT / "demo_bot" / "agent.py"


def run(action: str, target: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), action, "--file", str(target)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_on_and_off_flip_exactly_one_word_and_nothing_else(tmp_path: Path) -> None:
    copy = tmp_path / "agent.py"
    original = AGENT.read_bytes()
    copy.write_bytes(original)

    assert run("status", copy).stdout.startswith("the bug is OFF")
    assert run("on", copy).returncode == 0
    broken = copy.read_bytes()
    assert b'("dates", "Date")' in broken and b'("dates", "Dates")' not in broken
    assert len(broken) == len(original) - 1  # one letter fewer, everything else untouched
    assert run("status", copy).stdout.startswith("the bug is ON")

    assert run("off", copy).returncode == 0
    assert copy.read_bytes() == original  # byte for byte, including line endings and the rupee sign


def test_repeating_an_action_changes_nothing(tmp_path: Path) -> None:
    copy = tmp_path / "agent.py"
    copy.write_bytes(AGENT.read_bytes())
    run("on", copy)
    once = copy.read_bytes()
    result = run("on", copy)
    assert "already ON" in result.stdout and copy.read_bytes() == once


def test_the_real_file_is_left_with_the_bug_off() -> None:
    """Guard: the committed bot must never have the demo bug switched on."""
    assert b'("dates", "Dates")' in AGENT.read_bytes()
    assert run("status", AGENT).stdout.startswith("the bug is OFF")


def test_a_file_without_the_pattern_is_reported(tmp_path: Path) -> None:
    other = tmp_path / "other.py"
    other.write_text("nothing to see\n", encoding="utf-8")
    result = run("off", other)
    assert result.returncode == 0 and "already OFF" in result.stdout
    assert run("on", other).returncode == 1
