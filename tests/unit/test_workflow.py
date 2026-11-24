"""The GitHub Actions workflows: structure checks, since they can't be run here.

These don't prove GitHub will accept the file, but they catch the mistakes that matter: the wrong
trigger, a missing "always upload the report", a missing failure, or an API key sneaking in.
"""

from pathlib import Path
from typing import Any

import pytest

from wa_agent_test import yamlio

ROOT = Path(__file__).parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
SCENARIOS = WORKFLOWS / "scenarios.yml"


def load(path: Path) -> dict[str, Any]:
    data = yamlio.load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def steps() -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = load(SCENARIOS)["jobs"]["scenarios"]["steps"]
    return found


def step(name_part: str) -> dict[str, Any]:
    (found,) = [s for s in steps() if name_part.lower() in str(s.get("name", "")).lower()]
    return found


@pytest.mark.parametrize("path", sorted(WORKFLOWS.glob("*.yml")), ids=lambda p: p.name)
def test_every_workflow_is_valid_yaml_with_a_name_a_trigger_and_jobs(path: Path) -> None:
    data = load(path)
    assert data["name"] and data["on"] and data["jobs"]
    for job in data["jobs"].values():
        assert job["runs-on"] and job["steps"]


def test_it_runs_on_every_push_and_pull_request() -> None:
    triggers = load(SCENARIOS)["on"]
    assert set(triggers) == {"push", "pull_request"}
    assert not triggers["push"] and not triggers["pull_request"]  # no branch or path filters


def test_it_can_comment_on_pull_requests_but_cannot_write_code() -> None:
    permissions = load(SCENARIOS)["permissions"]
    assert permissions == {"contents": "read", "pull-requests": "write"}


def test_the_run_step_is_the_ci_script_and_is_not_allowed_to_fail_silently() -> None:
    run = step("Run all scenarios")
    assert run["run"].strip() == "python scripts/ci_run.py"
    assert "continue-on-error" not in run  # a non-zero exit (newly broken) fails the job
    assert "if" not in run  # it runs on pushes and pull requests alike


def test_the_report_is_uploaded_even_when_the_run_fails() -> None:
    upload = step("Upload the HTML report")
    assert upload["if"] == "always()"
    assert upload["uses"].startswith("actions/upload-artifact@")
    assert upload["with"]["name"] == "scenario-report" and upload["with"]["path"] == "reports/ci/"


def test_the_summary_is_shown_on_the_run_page_even_when_the_run_fails() -> None:
    show = step("summary on the run page")
    assert show["if"] == "always()" and "GITHUB_STEP_SUMMARY" in show["run"]


def test_the_pull_request_comment_is_pull_request_only_and_never_fails_the_job() -> None:
    comment = step("Post the summary on the pull request")
    assert "pull_request" in comment["if"] and "always()" in comment["if"]
    assert comment["continue-on-error"] is True  # forks get a read-only token
    script = comment["with"]["script"]
    assert (
        "<!-- wa-agent-test-summary -->" in script
    )  # updates its own comment, not a new one each time
    assert "updateComment" in script and "createComment" in script


def test_the_comment_marker_matches_the_one_the_summary_writes() -> None:
    from wa_agent_test.report import MARKER

    assert MARKER in step("Post the summary on the pull request")["with"]["script"]


def test_no_secrets_no_api_keys_and_no_model_are_needed_in_ci() -> None:
    text = SCENARIOS.read_text(encoding="utf-8")
    for forbidden in ("secrets.", "ANTHROPIC", "OPENAI", "OLLAMA", "ollama", "api_key"):
        assert forbidden not in text, forbidden
    script = (ROOT / "scripts" / "ci_run.py").read_text(encoding="utf-8")
    assert '"LLM_PROVIDER": "fake"' in script and '"--fake-judge"' in script


def test_actions_are_pinned_to_a_major_version() -> None:
    for s in steps():
        if "uses" in s:
            assert "@v" in s["uses"], s["uses"]


def test_the_committed_baseline_the_workflow_compares_with_exists_and_is_clean() -> None:
    import json

    baseline = json.loads((ROOT / "baselines" / "demo-bot.json").read_text(encoding="utf-8"))
    assert baseline["version"] == 1 and len(baseline["scenarios"]) >= 30
    assert all(entry["passed"] for entry in baseline["scenarios"].values())
