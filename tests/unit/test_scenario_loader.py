"""Scenario schema, for_each expansion and error reporting."""

from pathlib import Path

import pytest

from wa_agent_test.scenarios import ScenarioLoadError, load_scenario_file, load_scenarios

EXAMPLES = Path(__file__).parents[2] / "examples" / "scenarios"


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def problems(path: Path) -> list[str]:
    with pytest.raises(ScenarioLoadError) as info:
        load_scenarios(path)
    return [str(p) for p in info.value.problems]


# --- valid scenarios ----------------------------------------------------------------------


def test_minimal_scenario_with_defaults(tmp_path: Path) -> None:
    f = write(tmp_path, "a.yaml", 'name: hi\nturns:\n  - say: "hello"\n')
    (s,) = load_scenario_file(f)
    assert s.name == "hi" and s.tags == [] and s.turns[0].say == "hello"
    assert (s.defaults.timeout_s, s.defaults.settle_ms, s.defaults.allow_rejected) == (
        30.0,
        500,
        False,
    )
    assert s.timeout_for(s.turns[0]) == 30.0 and s.source_file == str(f)


def test_turn_overrides_defaults(tmp_path: Path) -> None:
    f = write(
        tmp_path,
        "a.yaml",
        "name: x\ndefaults: {timeout_s: 5, settle_ms: 100, allow_rejected: true}\n"
        "turns:\n  - {say: a, timeout_s: 60, settle_ms: 0, allow_rejected: false}\n  - {say: b}\n",
    )
    (s,) = load_scenario_file(f)
    first, second = s.turns
    assert (s.timeout_for(first), s.settle_ms_for(first), s.allow_rejected_for(first)) == (
        60,
        0,
        False,
    )
    assert (s.timeout_for(second), s.settle_ms_for(second), s.allow_rejected_for(second)) == (
        5,
        100,
        True,
    )


def test_all_turn_kinds_and_bare_send_image(tmp_path: Path) -> None:
    f = write(
        tmp_path,
        "a.yaml",
        "name: x\nturns:\n  - say: hi\n  - tap_button: Yes\n  - pick_row: Row\n"
        "  - send_image:\n  - send_image: {caption: pic}\n",
    )
    (s,) = load_scenario_file(f)
    assert [t.action_kind for t in s.turns] == [
        "say",
        "tap_button",
        "pick_row",
        "send_image",
        "send_image",
    ]
    assert s.turns[3].label == "send_image" and s.turns[4].label == "send_image: 'pic'"


def test_expect_items_become_checks(tmp_path: Path) -> None:
    f = write(
        tmp_path,
        "a.yaml",
        "name: x\nturns:\n  - say: hi\n    expect_messages: 2\n    expect:\n"
        "      - contains: a\n      - {not_contains: b, in: last}\n      - message_count: 2\n",
    )
    (s,) = load_scenario_file(f)
    turn = s.turns[0]
    assert [c.kind for c in turn.expect] == ["contains", "not_contains", "message_count"]
    assert turn.expect[1].scope == "last" and turn.expect_messages == 2


# --- for_each -----------------------------------------------------------------------------


def test_for_each_expands_and_substitutes(tmp_path: Path) -> None:
    f = write(
        tmp_path,
        "a.yaml",
        'name: "ask {{ ipo }}"\ntags: [t]\nfor_each:\n  ipo: [Nova, Marwar]\n'
        'turns:\n  - say: "About {{ ipo }}?"\n    expect:\n      - contains: "{{ ipo }}"\n',
    )
    scenarios = load_scenario_file(f)
    assert [s.name for s in scenarios] == ["ask Nova", "ask Marwar"]
    assert scenarios[1].turns[0].say == "About Marwar?"
    assert scenarios[1].turns[0].expect[0].value == "Marwar"  # type: ignore[attr-defined]
    assert all(s.tags == ["t"] for s in scenarios)


def test_for_each_with_mappings(tmp_path: Path) -> None:
    f = write(
        tmp_path,
        "a.yaml",
        'name: "{{ c.label }}"\nfor_each:\n  c:\n    - {label: one, text: first}\n'
        '    - {label: two, text: second}\nturns:\n  - say: "{{ c.text }}"\n',
    )
    scenarios = load_scenario_file(f)
    assert [(s.name, s.turns[0].say) for s in scenarios] == [("one", "first"), ("two", "second")]


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ("name: plain\nfor_each: {x: [a]}\nturns:\n  - say: hi\n", "name' must include"),
        ('name: "n {{ x }}"\nfor_each: {x: []}\nturns:\n  - say: hi\n', "non-empty list"),
        (
            'name: "n {{ x }}"\nfor_each: {x: [a], y: [b]}\nturns:\n  - say: hi\n',
            "exactly one variable",
        ),
        ('name: "n {{ x }}"\nfor_each: {x: [a]}\nturns:\n  - say: "{{ y }}"\n', "unknown variable"),
        ('name: "n {{ x.k }}"\nfor_each: {x: [a]}\nturns:\n  - say: hi\n', "no key 'k'"),
    ],
)
def test_for_each_errors(tmp_path: Path, body: str, fragment: str) -> None:
    (msg,) = problems(write(tmp_path, "a.yaml", body))[:1]
    assert fragment in msg and "a.yaml:" in msg


# --- errors point at file and line ----------------------------------------------------------


def test_error_line_numbers(tmp_path: Path) -> None:
    f = write(
        tmp_path,
        "bad.yaml",
        "name: x\n"  # 1
        "turns:\n"  # 2
        "  - say: fine\n"  # 3
        "  - say: oops\n"  # 4
        "    expect:\n"  # 5
        "      - contains: ok\n"  # 6
        "      - containz: typo\n",  # 7
    )
    (msg,) = problems(f)
    assert msg.startswith(f"{f}:5:") or msg.startswith(f"{f}:7:")
    assert "turns[1].expect" in msg and "unknown check 'containz'" in msg
    assert "expect[1]" in msg


def test_unknown_key_is_an_error_with_its_line(tmp_path: Path) -> None:
    f = write(
        tmp_path, "bad.yaml", "name: x\nturns:\n  - say: hi\n    expct:\n      - contains: a\n"
    )
    (msg,) = problems(f)
    assert f"{f}:4:" in msg and "turns[0].expct" in msg and "Extra inputs" in msg


def test_turn_needs_exactly_one_action(tmp_path: Path) -> None:
    f = write(
        tmp_path, "bad.yaml", "name: x\nturns:\n  - say: hi\n    tap_button: Yes\n  - expect: []\n"
    )
    msgs = problems(f)
    assert len(msgs) == 2 and all("exactly one of say" in m for m in msgs)
    assert f"{f}:3:" in msgs[0] and f"{f}:5:" in msgs[1]


def test_missing_required_fields(tmp_path: Path) -> None:
    (msg,) = problems(write(tmp_path, "bad.yaml", "turns:\n  - say: hi\n"))
    assert "name" in msg and "Field required" in msg
    (msg,) = problems(write(tmp_path, "bad2.yaml", "name: x\nturns: []\n"))
    assert "turns" in msg


def test_wrong_types_and_ranges(tmp_path: Path) -> None:
    f = write(
        tmp_path,
        "bad.yaml",
        "name: x\nturns:\n  - say: hi\n    timeout_s: -1\n    expect_messages: lots\n",
    )
    msgs = problems(f)
    assert any("timeout_s" in m for m in msgs) and any("expect_messages" in m for m in msgs)


def test_invalid_yaml_and_non_mapping(tmp_path: Path) -> None:
    (msg,) = problems(write(tmp_path, "bad.yaml", "name: [unclosed\n"))
    assert "not valid YAML" in msg
    (msg,) = problems(write(tmp_path, "list.yaml", "- a\n- b\n"))
    assert "must be a YAML mapping" in msg
    (msg,) = problems(write(tmp_path, "empty.yaml", ""))
    assert "must be a YAML mapping" in msg


def test_fact_errors_surface_with_a_location(tmp_path: Path) -> None:
    f = write(
        tmp_path,
        "bad.yaml",
        "name: x\nturns:\n  - say: hi\n    expect:\n      - fact:\n          source: s\n"
        '          entity: e\n          field: f\n          extract: {regex: "(", parser: date}\n',
    )
    (msg,) = problems(f)
    assert "invalid regular expression" in msg and "turns[0].expect" in msg


# --- folders ------------------------------------------------------------------------------


def test_folder_loading_is_recursive_sorted_and_ignores_other_files(tmp_path: Path) -> None:
    write(tmp_path, "b.yaml", "name: b\nturns:\n  - say: hi\n")
    write(tmp_path, "a.yml", "name: a\nturns:\n  - say: hi\n")
    (tmp_path / "sub").mkdir()
    write(tmp_path / "sub", "c.yaml", "name: c\nturns:\n  - say: hi\n")
    write(tmp_path, "notes.txt", "not a scenario")
    assert [s.name for s in load_scenarios(tmp_path)] == ["a", "b", "c"]


def test_all_problems_across_files_are_reported_together(tmp_path: Path) -> None:
    write(tmp_path, "one.yaml", "name: one\nturns: []\n")
    write(tmp_path, "two.yaml", "turns:\n  - say: hi\n")
    assert len(problems(tmp_path)) == 2


def test_duplicate_names_are_rejected(tmp_path: Path) -> None:
    write(tmp_path, "a.yaml", "name: same\nturns:\n  - say: hi\n")
    write(tmp_path, "b.yaml", "name: same\nturns:\n  - say: hi\n")
    (msg,) = problems(tmp_path)
    assert "duplicate scenario name 'same'" in msg


def test_missing_path(tmp_path: Path) -> None:
    (msg,) = problems(tmp_path / "nope")
    assert "no such file or folder" in msg


# --- the shipped examples -----------------------------------------------------------------


def test_the_20_example_files_are_valid() -> None:
    files = sorted(EXAMPLES.glob("*.yaml"))
    assert len(files) == 20
    scenarios = load_scenarios(EXAMPLES)
    assert {s.source_file for s in scenarios} == {str(f) for f in files}
    assert len({s.name for s in scenarios}) == len(scenarios) == 30  # for_each expands 3 files
    assert all(s.description for s in scenarios)


def test_yes_no_on_off_stay_text_not_booleans(tmp_path: Path) -> None:
    """Plain YAML turns `Yes`/`No`/`on`/`off` into booleans; button titles must stay text."""
    f = write(
        tmp_path,
        "a.yaml",
        "name: x\nturns:\n  - tap_button: Yes\n  - tap_button: No\n  - tap_button: on\n"
        "  - tap_button: off\ndefaults:\n  allow_rejected: true\n",
    )
    (s,) = load_scenario_file(f)
    assert [t.tap_button for t in s.turns] == ["Yes", "No", "on", "off"]
    assert s.defaults.allow_rejected is True  # real booleans still work
