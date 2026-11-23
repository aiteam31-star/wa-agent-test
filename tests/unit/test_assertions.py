"""Checks, parsers, the file truth source and fact checks."""

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from wa_agent_test.assertions import BotMessage, Button, Row, TurnContext, parse_check
from wa_agent_test.assertions.parsers import parse_date, parse_number
from wa_agent_test.truth import FileTruthSource, TruthError

ROOT = Path(__file__).parents[2]
IPOS = ROOT / "demo_bot" / "data" / "ipos.json"
FIELDS = {
    "listing_date": "dates.listing",
    "open_date": "dates.open",
    "close_date": "dates.close",
    "price_band_high": "price_band.high",
    "lot_size": "lot_size",
    "subscription_total": "subscription.total",
}


def truth() -> dict[str, FileTruthSource]:
    source = FileTruthSource(
        IPOS, records="ipos", entity_match=["name", "short_name"], fields=FIELDS
    )
    return {"ipos": source}


def msg(
    text: str = "",
    *,
    type: str = "text",
    buttons: list[tuple[str, str]] | None = None,
    rows: list[tuple[str, str]] | None = None,
    latency_ms: float = 10.0,
) -> BotMessage:
    return BotMessage(
        message_id="wamid.X",
        type=type,
        text=text,
        buttons=[Button(id=i, title=t) for i, t in buttons or []],
        rows=[Row(id=i, title=t) for i, t in rows or []],
        latency_ms=latency_ms,
        raw={},
    )


def run(check: dict[str, Any], *messages: BotMessage) -> tuple[bool, str]:
    result = parse_check(check).evaluate(TurnContext(list(messages), truth()))
    return result.passed, result.message


# --- deterministic checks -----------------------------------------------------------------


def test_contains_is_case_insensitive_and_needs_every_item() -> None:
    assert run({"contains": "nova"}, msg("Nova Textiles"))[0]
    assert run({"contains": ["Nova", "Textiles"]}, msg("Nova Textiles"))[0]
    ok, why = run({"contains": ["Nova", "Marwar"]}, msg("Nova Textiles"))
    assert not ok and "'Marwar'" in why and "Nova Textiles" in why


def test_not_contains() -> None:
    assert run({"not_contains": ["apply", "invest"]}, msg("just facts"))[0]
    ok, why = run({"not_contains": "YOU SHOULD APPLY"}, msg("Hi. You should apply now"))
    assert not ok and "you should apply" in why.lower()


def test_equals_needs_one_message() -> None:
    assert run({"equals": "hello"}, msg("  hello \n"))[0]
    assert not run({"equals": "hello"}, msg("hello!"))[0]
    ok, why = run({"equals": "hello"}, msg("hello"), msg("hello"))
    assert not ok and "exactly one message" in why
    assert run({"equals": "hello", "in": "last"}, msg("x"), msg("hello"))[0]


def test_regex() -> None:
    assert run({"regex": r"\d+ shares"}, msg("lot size 67 shares"))[0]
    assert not run({"regex": r"^\d+$"}, msg("lot size 67 shares"))[0]


def test_message_count_exact_and_range() -> None:
    assert run({"message_count": 2}, msg("a"), msg("b"))[0]
    assert not run({"message_count": 1}, msg("a"), msg("b"))[0]
    assert run({"message_count": {"min": 1, "max": 3}}, msg("a"), msg("b"))[0]
    assert not run({"message_count": {"min": 3}}, msg("a"))[0]
    assert run({"message_count": 0})[0]


def test_message_type() -> None:
    assert run({"message_type": "interactive"}, msg("x", type="interactive"))[0]
    ok, why = run({"message_type": "text"}, msg("x"), msg("y", type="interactive"))
    assert not ok and "interactive" in why
    assert not run({"message_type": "text"})[0]


def test_buttons() -> None:
    three = msg("x", type="interactive", buttons=[("1", "A"), ("2", "B"), ("3", "C")])
    assert run({"button_count": 3}, three)[0]
    assert not run({"button_count": 2}, three)[0]
    assert run({"button_titles": ["A", "B", "C"]}, three)[0]
    ok, why = run({"button_titles": ["A", "C", "B"]}, three)
    assert not ok and "['A', 'B', 'C']" in why
    ok, why = run({"button_count": 3}, msg("no buttons here"))
    assert not ok and "no message with reply buttons" in why


def test_reply_within_ms_uses_the_first_message() -> None:
    assert run({"reply_within_ms": 500}, msg("a", latency_ms=100), msg("b", latency_ms=900))[0]
    assert not run({"reply_within_ms": 50}, msg("a", latency_ms=100))[0]
    assert not run({"reply_within_ms": 50})[0]


def test_scopes() -> None:
    a, b, c = msg("alpha"), msg("beta"), msg("gamma")
    assert run({"contains": "alpha", "in": "first"}, a, b, c)[0]
    assert not run({"contains": "alpha", "in": "last"}, a, b, c)[0]
    assert run({"contains": "beta", "in": 1}, a, b, c)[0]
    assert run({"contains": "gamma", "in": -1}, a, b, c)[0]
    ok, why = run({"contains": "x", "in": 7}, a, b, c)
    assert not ok and "no message at 7" in why
    ok, why = run({"contains": "x", "in": "first"})
    assert not ok and "no message" in why


# --- parse_check errors -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("item", "fragment"),
    [
        ("contains: x", "mapping"),
        ({"contains": "x", "regex": "y"}, "exactly one check"),
        ({}, "exactly one check"),
        ({"contian": "x"}, "unknown check 'contian'"),
        ({"judge": {"rubric": "x", "oops": 1}}, "judge"),
        ({"regex": "("}, "invalid regular expression"),
        ({"message_count": "lots"}, "message_count"),
        ({"contains": "x", "in": "middle"}, "contains"),
        ({"fact": {"source": "ipos"}}, "fact"),
    ],
)
def test_parse_check_errors(item: Any, fragment: str) -> None:
    with pytest.raises(ValueError, match=fragment):
        parse_check(item)


# --- parsers ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "30 November 2026",
        "30 Nov 2026",
        "November 30, 2026",
        "Nov 30 2026",
        "2026-11-30",
        "30/11/2026",
        "30-11-2026",
        "30th November 2026",
        "  30   November   2026 ",
    ],
)
def test_parse_date_formats(text: str) -> None:
    assert parse_date(text) == date(2026, 11, 30)


@pytest.mark.parametrize("text", ["32 November 2026", "soon", "", "November 2026"])
def test_parse_date_rejects_nonsense(text: str) -> None:
    with pytest.raises(ValueError):
        parse_date(text)


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("221", 221.0),
        ("₹14,807", 14807.0),
        ("Rs. 210", 210.0),
        ("7.1x", 7.1),
        ("1,234.5", 1234.5),
        (67, 67.0),
    ],
)
def test_parse_number(text: Any, value: float) -> None:
    assert parse_number(text) == value


def test_parse_number_rejects_nonsense() -> None:
    with pytest.raises(ValueError):
        parse_number("a lot")
    with pytest.raises(ValueError):
        parse_number(True)


# --- file truth source --------------------------------------------------------------------


def test_truth_lookup_by_name_short_name_and_fragment() -> None:
    src = truth()["ipos"]
    assert src.lookup("Nova Textiles", "listing_date") == "2026-11-30"
    assert src.lookup("nova textiles ltd", "lot_size") == 67
    assert src.lookup("Bharat", "price_band_high") == 101
    assert src.lookup("Kaveri Agro", "subscription_total") is None


def test_truth_errors_are_clear() -> None:
    src = truth()["ipos"]
    with pytest.raises(TruthError, match="was not found"):
        src.lookup("Acme", "lot_size")
    with pytest.raises(TruthError, match="is ambiguous"):
        src.lookup("ltd", "lot_size")
    with pytest.raises(TruthError, match="no field 'colour'"):
        src.lookup("Nova Textiles", "colour")
    with pytest.raises(TruthError, match="empty entity"):
        src.lookup("", "lot_size")


def test_truth_source_rejects_a_wrong_records_path() -> None:
    with pytest.raises(TruthError, match="no 'nope'"):
        FileTruthSource(IPOS, records="nope")


# --- fact checks --------------------------------------------------------------------------


def fact(**extract: Any) -> dict[str, Any]:
    return {
        "fact": {
            "source": "ipos",
            "entity": "Nova Textiles",
            "field": "listing_date",
            "extract": {
                "regex": r"listing date is (\d{1,2} \w+ \d{4})",
                "parser": "date",
                **extract,
            },
        }
    }


def test_fact_passes_when_the_claim_matches() -> None:
    ok, why = run(fact(), msg("Nova Textiles: listing date is 30 November 2026."))
    assert ok and "30 November 2026 matches ipos" in why


def test_fact_accepts_other_date_spellings_of_the_right_date() -> None:
    check = fact(regex=r"lists on (.+?)\.")
    assert run(check, msg("It lists on Nov 30, 2026."))[0]
    assert run(check, msg("It lists on 2026-11-30."))[0]


def test_fact_fails_on_a_wrong_value_and_names_both_values() -> None:
    ok, why = run(fact(), msg("listing date is 1 December 2026"))
    assert not ok
    assert "reply says listing date 1 December 2026 but ipos says 30 November 2026" in why


def test_fact_fails_when_the_claim_is_not_in_the_reply() -> None:
    """The required behaviour: no match means FAIL with a clear message, never a silent pass."""
    ok, why = run(fact(), msg("Nova Textiles is a textile company. Ask me anything!"))
    assert not ok
    assert "couldn't find a listing date in the reply" in why


def test_fact_fails_when_the_bot_sent_no_message_at_all() -> None:
    ok, why = run(fact())
    assert not ok and "couldn't find a listing date in the reply" in why


def test_fact_does_not_pass_on_a_correct_value_the_pattern_does_not_capture() -> None:
    # The right date is present, but not where the pattern looks: still a failure.
    ok, why = run(fact(), msg("It will start trading on 30 November 2026."))
    assert not ok and "couldn't find a listing date" in why


def test_fact_fails_when_the_extracted_text_is_not_a_date() -> None:
    ok, why = run(fact(regex=r"listing date is (\w+)"), msg("listing date is soon"))
    assert not ok and "found 'soon' for listing date but couldn't read it as a date" in why


def test_fact_fails_if_any_claim_in_the_reply_is_wrong() -> None:
    ok, why = run(
        fact(),
        msg("listing date is 30 November 2026"),
        msg("(correction) listing date is 2 December 2026"),
    )
    assert not ok and "2 December 2026" in why


def test_fact_numbers_and_currency() -> None:
    check = {
        "fact": {
            "source": "ipos",
            "entity": "Nova Textiles",
            "field": "price_band_high",
            "extract": {"regex": r"price band ₹\d+-(\d+)", "parser": "number"},
        }
    }
    assert run(check, msg("price band ₹210-221"))[0]
    ok, why = run(check, msg("price band ₹210-225"))
    assert not ok and "225" in why and "221" in why


def test_fact_number_tolerance() -> None:
    def sub(tolerance: float) -> dict[str, Any]:
        return {
            "fact": {
                "source": "ipos",
                "entity": "Nova Textiles",
                "field": "subscription_total",
                "tolerance": tolerance,
                "extract": {"regex": r"overall (\d+(?:\.\d+)?)x", "parser": "number"},
            }
        }

    assert not run(sub(0), msg("overall 7.2x"))[0]
    assert run(sub(0.2), msg("overall 7.2x"))[0]


def test_fact_without_a_capture_group_uses_the_whole_match() -> None:
    check = fact(regex=r"\d{1,2} November 2026")
    assert run(check, msg("on 30 November 2026"))[0]


def test_fact_scope_selects_the_message() -> None:
    check = {**fact(), "in": "last"}
    assert not run(check, msg("listing date is 30 November 2026"), msg("see you soon"))[0]
    assert run(check, msg("hi"), msg("listing date is 30 November 2026"))[0]


def test_fact_text_parser_is_case_and_space_insensitive() -> None:
    check = {
        "fact": {
            "source": "ipos",
            "entity": "Nova Textiles",
            "field": "name",
            "extract": {"regex": r"company: (.+)$", "parser": "text"},
        }
    }
    assert run(check, msg("company: NOVA   textiles ltd"))[0]


def test_fact_problems_with_the_truth_source_fail_clearly() -> None:
    ok, why = run({"fact": {**fact()["fact"], "source": "nope"}}, msg("x"))
    assert not ok and "'nope' isn't defined" in why and "ipos" in why
    ok, why = run({"fact": {**fact()["fact"], "entity": "Acme"}}, msg("listing date is 1 May 2026"))
    assert not ok and "'Acme' was not found" in why
    ok, why = run(
        {"fact": {**fact()["fact"], "entity": "Kaveri Agro", "field": "subscription_total"}},
        msg("overall 3x"),
    )
    assert not ok and "has no subscription total" in why


def test_fact_definition_errors_are_caught_at_load_time() -> None:
    with pytest.raises(ValueError, match="invalid regular expression"):
        parse_check(fact(regex="("))
    with pytest.raises(ValueError, match="group 2 doesn't exist"):
        parse_check(fact(group=2))
    with pytest.raises(ValueError, match="parser"):
        parse_check(fact(parser="magic"))


def test_why_text_explains_a_failure_and_keeps_the_detail() -> None:
    check = parse_check({"not_contains": "%", "why": "subscription must be in times"})
    ctx = TurnContext([msg("Total: 7.1%")], truth())
    result = check.evaluate(ctx)
    assert not result.passed
    assert result.message.startswith("subscription must be in times (reply must not contain ['%']")
    assert (
        check.evaluate(TurnContext([msg("Total: 7.1x")], truth())).message == "reply avoids ['%']"
    )


def test_why_is_accepted_alongside_in() -> None:
    check = parse_check({"contains": "x", "in": "last", "why": "because"})
    assert check.scope == "last" and check.why == "because"


# --- known_dates --------------------------------------------------------------------------------


def known(**extra: Any) -> dict[str, Any]:
    spec = {"source": "ipos", "fields": ["listing_date", "close_date"]}
    return {"known_dates": {**spec, **extra}}


def test_find_dates_reads_every_spelling_in_order() -> None:
    from wa_agent_test.assertions.parsers import find_dates

    text = (
        "Opens 20th November 2026, closes Nov 25, 2026; allotment 2026-11-26; "
        "listing on 30/11/2026 or 1 Dec. 2026 or 2 December, 2026."
    )
    assert [d.isoformat() for _, d in find_dates(text)] == [
        "2026-11-20",
        "2026-11-25",
        "2026-11-26",
        "2026-11-30",
        "2026-12-01",
        "2026-12-02",
    ]
    assert find_dates("31 February 2026 and 99/99/2026 and 'May 2026'") == []
    assert find_dates("no dates here") == []


def test_known_dates_passes_when_every_date_is_in_the_data() -> None:
    ok, why = run(known(), msg("Nova lists on 30 November 2026; closes 25 November 2026."))
    assert ok and why == "all 2 date(s) in the reply appear in the data (ipos)"


def test_known_dates_with_no_dates_passes_and_says_so() -> None:
    ok, why = run(known(), msg("I can't give advice."))
    assert ok and "no dates" in why


def test_known_dates_fails_on_an_invented_date() -> None:
    ok, why = run(known(), msg("Nova lists on 30 November 2026, opened 29 Sep 2022."))
    assert not ok
    assert "29 Sep 2022" in why and "1 of 2 date(s) were real" in why


def test_known_dates_only_allows_the_listed_fields() -> None:
    # 20 November is Nova's opening date, but only listing and closing dates are allowed here
    ok, why = run(known(), msg("It opens 20 November 2026."))
    assert not ok and "20 November 2026" in why


def test_known_dates_problems_with_the_source_fail_loudly() -> None:
    ok, why = run(known(source="nope"), msg("x"))
    assert not ok and "'nope' isn't defined" in why
    ok, why = run(known(fields=["colour"]), msg("x"))
    assert not ok and "has no dates for colour" in why
    with pytest.raises(ValueError, match="known_dates"):
        parse_check({"known_dates": {"source": "ipos"}})
