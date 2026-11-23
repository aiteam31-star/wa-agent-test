"""The limits config: one file, every entry annotated with how well it is confirmed."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from wa_agent_test.mock_graph import Limits, load_limits
from wa_agent_test.mock_graph.limits import DEFAULT_LIMITS_PATH


def test_default_file_loads_with_expected_values(limits: Limits) -> None:
    assert limits.text_body_max.value == 4096
    assert limits.reply_buttons_max.value == 3
    assert limits.reply_button_title_max.value == 20
    assert limits.list_rows_max.value == 10
    assert limits.list_row_title_max.value == 24
    assert limits.list_row_description_max.value == 72


def test_every_limit_has_a_status_and_source(limits: Limits) -> None:
    for name, spec in limits:
        assert spec.value > 0, name
        assert spec.source, f"{name} has no source"


def test_unconfirmed_limits_are_listed(limits: Limits) -> None:
    assert set(limits.not_confirmed()) == {"interactive_header_text_max"}


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    data = yaml.safe_load(DEFAULT_LIMITS_PATH.read_text(encoding="utf-8"))
    data["typo_limit"] = {"value": 1, "status": "confirmed"}
    path = tmp_path / "limits.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_limits(path)


def test_custom_file_overrides_a_limit(tmp_path: Path) -> None:
    data = yaml.safe_load(DEFAULT_LIMITS_PATH.read_text(encoding="utf-8"))
    data["text_body_max"]["value"] = 10
    path = tmp_path / "limits.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert load_limits(path).text_body_max.value == 10
