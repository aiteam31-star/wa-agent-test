"""Project config loading and the CLI's error handling."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from wa_agent_test.cli import app
from wa_agent_test.config import (
    ConfigError,
    build_truth_sources,
    find_config,
    load_config,
)

ROOT = Path(__file__).parents[2]
EXAMPLES = ROOT / "examples"
cli = CliRunner()

MINIMAL = "bot:\n  webhook_url: http://127.0.0.1:9/webhook\n  app_secret: s\n"
SCENARIO = "name: hello\nturns:\n  - say: hi\n"


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --- config -------------------------------------------------------------------------------


def test_env_interpolation_with_and_without_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WA_SECRET", "from-env")
    monkeypatch.delenv("WA_TOKEN", raising=False)
    cfg = load_config(
        write(
            tmp_path / "c.yaml",
            "bot:\n  webhook_url: http://x/webhook\n  app_secret: ${WA_SECRET}\n"
            "  verify_token: ${WA_TOKEN:-fallback}\n",
        )
    )
    assert cfg.bot.app_secret == "from-env" and cfg.bot.verify_token == "fallback"
    assert cfg.mock.port == 9000 and cfg.run.concurrency == 4  # defaults


def test_missing_env_var_is_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NOPE_SECRET", raising=False)
    path = write(
        tmp_path / "c.yaml", "bot:\n  webhook_url: http://x\n  app_secret: ${NOPE_SECRET}\n"
    )
    with pytest.raises(ConfigError, match="NOPE_SECRET is not set"):
        load_config(path)


def test_config_errors_name_the_field(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"bot.app_secret: Field required"):
        load_config(write(tmp_path / "a.yaml", "bot:\n  webhook_url: http://x\n"))
    with pytest.raises(ConfigError, match=r"mock.prot: Extra inputs"):
        load_config(write(tmp_path / "b.yaml", MINIMAL + "mock:\n  prot: 1\n"))
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_config(write(tmp_path / "c.yaml", "bot: [oops\n"))
    with pytest.raises(ConfigError, match="must be a YAML mapping"):
        load_config(write(tmp_path / "d.yaml", "- a\n"))


def test_find_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    scenarios = tmp_path / "proj" / "scenarios"
    scenarios.mkdir(parents=True)
    with pytest.raises(ConfigError, match=r"no wa-agent-test\.yaml found"):
        find_config(None, scenarios)
    config = write(tmp_path / "proj" / "wa-agent-test.yaml", MINIMAL)
    assert find_config(None, scenarios) == config  # next to the scenarios folder
    explicit = write(tmp_path / "other.yaml", MINIMAL)
    assert find_config(explicit, scenarios) == explicit
    with pytest.raises(ConfigError, match="config file not found"):
        find_config(tmp_path / "missing.yaml", scenarios)


def test_example_config_and_truth_sources_load() -> None:
    path = EXAMPLES / "wa-agent-test.yaml"
    cfg = load_config(path)
    sources = build_truth_sources(cfg, path.parent)
    assert sources["ipos"].lookup("Nova Textiles", "listing_date") == "2026-11-30"


def test_truth_source_file_must_exist(tmp_path: Path) -> None:
    path = write(
        tmp_path / "c.yaml",
        MINIMAL + "truth_sources:\n  t:\n    type: file\n    path: missing.json\n",
    )
    with pytest.raises(ConfigError, match="file not found"):
        build_truth_sources(load_config(path), tmp_path)


# --- CLI ----------------------------------------------------------------------------------


def test_validate_the_examples() -> None:
    result = cli.invoke(app, ["validate", str(EXAMPLES / "scenarios")])
    assert result.exit_code == 0
    assert "OK: 25 scenario(s) from 15 file(s)" in result.output


def test_validate_reports_file_and_line_and_exits_2(tmp_path: Path) -> None:
    bad = write(tmp_path / "bad.yaml", "name: x\nturns:\n  - say: hi\n    expct: []\n")
    result = cli.invoke(app, ["validate", str(bad)])
    assert result.exit_code == 2
    assert f"{bad}:4:" in result.output and "expct" in result.output


def test_run_without_a_config_exits_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    scenarios = write(tmp_path / "s" / "a.yaml", SCENARIO).parent
    result = cli.invoke(app, ["run", str(scenarios)])
    assert result.exit_code == 2 and "no wa-agent-test.yaml found" in result.output


def test_run_with_an_invalid_scenario_exits_2(tmp_path: Path) -> None:
    config = write(tmp_path / "wa-agent-test.yaml", MINIMAL)
    bad = write(tmp_path / "s" / "bad.yaml", "name: x\nturns: []\n")
    result = cli.invoke(app, ["run", str(bad.parent), "--config", str(config)])
    assert result.exit_code == 2 and "bad.yaml" in result.output


def test_run_with_no_matching_scenarios_exits_2(tmp_path: Path) -> None:
    config = write(tmp_path / "wa-agent-test.yaml", MINIMAL)
    scenarios = write(tmp_path / "s" / "a.yaml", SCENARIO).parent
    for extra in (["--name", "zzz"], ["--tag", "nothing"]):
        result = cli.invoke(app, ["run", str(scenarios), "--config", str(config), *extra])
        assert result.exit_code == 2 and "no scenarios matched" in result.output


def test_run_with_an_unreachable_bot_exits_3(tmp_path: Path) -> None:
    config = write(
        tmp_path / "wa-agent-test.yaml",
        MINIMAL.replace("s\n", "s\n  verify_token: t\n") + "mock:\n  port: 0\n",
    )
    scenarios = write(tmp_path / "s" / "a.yaml", SCENARIO).parent
    result = cli.invoke(app, ["run", str(scenarios), "--config", str(config)])
    assert result.exit_code == 3 and "can't reach the bot" in result.output


def test_no_arguments_shows_help() -> None:
    result = cli.invoke(app, [])
    assert "run" in result.output and "validate" in result.output
