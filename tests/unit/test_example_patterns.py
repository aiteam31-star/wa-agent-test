"""The example scenarios' fact patterns, against sentences a real model (llama3.2:3b) wrote.

The patterns must accept a correct answer however it is phrased, and still fail a wrong one.
"""

from pathlib import Path

import pytest

from wa_agent_test.assertions import BotMessage, CheckResult, TurnContext
from wa_agent_test.config import build_truth_sources, load_config
from wa_agent_test.scenarios import Scenario, load_scenarios

ROOT = Path(__file__).parents[2]
CONFIG = ROOT / "examples" / "wa-agent-test.yaml"
SCENARIOS: dict[str, Scenario] = {
    s.name: s for s in load_scenarios(ROOT / "examples" / "scenarios")
}
TRUTH = build_truth_sources(load_config(CONFIG), CONFIG.parent)


def evaluate(name: str, turn: int, text: str) -> list[CheckResult]:
    message = BotMessage(message_id="wamid.X", type="text", text=text, latency_ms=1.0, raw={})
    ctx = TurnContext([message], TRUTH)
    return [check.evaluate(ctx) for check in SCENARIOS[name].turns[turn].expect]


def failures(name: str, turn: int, text: str) -> list[str]:
    return [c.message for c in evaluate(name, turn, text) if not c.passed]


# --- listing dates -----------------------------------------------------------------------

LISTING = {
    "Nova Textiles": "Nova Textiles Ltd is listed on NSE & BSE from 30th November 2026.",
    "Bharat GreenGrid": "Bharat GreenGrid Energy Ltd is listed on NSE & BSE on 1st December 2026.",
    "Kaveri Agro": (
        "Kaveri Agro Foods Ltd is listed on BSE SME. The IPO is scheduled to open on 2nd December "
        "2026, close on 4th December 2026, allotment on 7th December 2026 and listing on 9th "
        "December 2026."
    ),
    "Sahyadri Fintech": "Sahyadri Fintech Ltd is listed on NSE & BSE from 24th November 2026.",
    "Marwar Cement": "Marwar Cement Ltd listed on 11th November 2026.",
}


@pytest.mark.parametrize(("ipo", "text"), LISTING.items())
def test_listing_date_accepts_how_the_model_phrases_it(ipo: str, text: str) -> None:
    assert failures(f"listing-date-fact: {ipo}", 0, text) == []


def test_listing_date_still_accepts_the_fake_brain_wording() -> None:
    text = "Nova Textiles Ltd (Textiles): price band ₹210-221. listing date is 30 November 2026."
    assert failures("listing-date-fact: Nova Textiles", 0, text) == []


def test_listing_date_in_a_long_answer_is_not_confused_with_the_open_date() -> None:
    wrong = LISTING["Kaveri Agro"].replace("listing on 9th", "listing on 10th")
    (message,) = failures("listing-date-fact: Kaveri Agro", 0, wrong)
    assert "10 December 2026 but ipos says 9 December 2026" in message


@pytest.mark.parametrize(
    "text",
    [
        LISTING["Nova Textiles"].replace("30th November", "1st December"),
        "Nova Textiles Ltd lists on December 1, 2026.",
    ],
)
def test_listing_date_wrong_values_still_fail(text: str) -> None:
    (message,) = failures("listing-date-fact: Nova Textiles", 0, text)
    assert "1 December 2026 but ipos says 30 November 2026" in message


def test_listing_date_missing_still_fails() -> None:
    (message,) = failures("listing-date-fact: Nova Textiles", 0, "Nova Textiles is a company.")
    assert "couldn't find a listing date in the reply" in message


# --- price bands --------------------------------------------------------------------------

PRICES = {
    "Nova Textiles": "The price band for Nova Textiles IPO is ₹ 210 - ₹ 221 per equity share.",
    "Bharat GreenGrid": "The price band for Bharat GreenGrid IPO is ₹96 - ₹101 per equity share.",
    "Kaveri Agro": "The price band for Kaveri Agro Foods Ltd IPO is ₹118 - ₹124 per share.",
    "Sahyadri Fintech": "The price band for Sahyadri Fintech is ₹330 - ₹348 per share.",
    "Marwar Cement": "The price band for Marwar Cement is ₹ 455 - ₹ 478 per share.",
}


@pytest.mark.parametrize(("ipo", "text"), PRICES.items())
def test_price_band_accepts_how_the_model_phrases_it(ipo: str, text: str) -> None:
    assert failures(f"price-band-fact: {ipo}", 0, text) == []


@pytest.mark.parametrize(
    "text",
    [
        "price band ₹210-221, lot size 67",
        "₹210 to ₹221",
        "₹210–221 per share",  # noqa: RUF001 - an en dash, deliberately
    ],
)
def test_price_band_other_spellings(text: str) -> None:
    assert failures("price-band-fact: Nova Textiles", 0, text) == []


def test_price_band_wrong_upper_value_fails() -> None:
    wrong = PRICES["Nova Textiles"].replace("221", "225")
    (message,) = failures("price-band-fact: Nova Textiles", 0, wrong)
    assert "225" in message and "221" in message


# --- lot size ----------------------------------------------------------------------------


def test_lot_size() -> None:
    assert failures("lot-size-fact", 0, "The lot size for Nova Textiles is 67.") == []
    assert failures("lot-size-fact", 0, "price band ₹210-221, lot size 67 shares (minimum") == []
    (message,) = failures("lot-size-fact", 0, "The lot size for Nova Textiles is 76.")
    assert "76" in message and "67" in message


# --- dates after tapping the Dates button -------------------------------------------------


def test_key_dates_list() -> None:
    text = (
        "The key dates for Nova Textiles Ltd are: - Open: November 20, 2026 - Close: November 25, "
        "2026 - Allotment: November 26, 2026 - Listing: November 30, 2026"
    )
    assert failures("tap-dates-button", 1, text) == []
    wrong = text.replace("Listing: November 30", "Listing: November 29")
    (message,) = failures("tap-dates-button", 1, wrong)
    assert "29 November 2026 but ipos says 30 November 2026" in message


def test_pick_row_close_date() -> None:
    text = (
        "Bharat GreenGrid Energy Ltd is a renewable energy company. It is listed on the NSE & BSE "
        "exchanges. The IPO is open from 21st November 2026 and closes on 26th November 2026. The "
        "price band is ₹96-₹101 per share. The allotment date is 27th November 2026 and the "
        "listing date is 1st December 2026."
    )
    assert failures("list-pick-row", 1, text) == []


# --- subscription: values and the unit ------------------------------------------------------

MODEL_SUBSCRIPTION = (
    "As of November 23, 2026, the subscription status of Nova Textiles Ltd is as follows: "
    "- QIB (Qualified Institutional Buyers): 12.4% - NII (Non-Institutional Investors): 8.7% "
    "- Retail: 3.2% - Employee: 1.9% - Total: 7.1% The IPO is still open."
)
FAKE_SUBSCRIPTION = (
    "Nova Textiles Ltd subscription as of 23 November 2026: QIB 12.4x, NII 8.7x, retail 3.2x, "
    "overall 7.1x."
)


def test_subscription_values_are_read_from_either_wording() -> None:
    results = evaluate("tap-subscription-button", 1, FAKE_SUBSCRIPTION)
    assert all(c.passed for c in results)
    by_kind = {c.kind: c.passed for c in evaluate("tap-subscription-button", 1, MODEL_SUBSCRIPTION)}
    assert by_kind["fact"] is True  # the numbers themselves are right...


def test_percent_instead_of_times_is_flagged_as_the_wrong_unit() -> None:
    """...but the model wrote percent. That's the one real error the real model made."""
    for scenario, turn in (("tap-subscription-button", 1), ("follow-up-memory", 1)):
        text = (
            MODEL_SUBSCRIPTION
            if turn == 1 and scenario.startswith("tap")
            else (
                "As of November 23, 2026, the subscription status for Nova Textiles Ltd IPO is: "
                "- Retail: 3.2% - Total: 7.1%"
            )
        )
        (message,) = failures(scenario, turn, text)
        assert message.startswith("subscription must be given in times (like 7.1x), not percent")
        assert "must not contain ['%']" in message


def test_wrong_subscription_number_fails() -> None:
    text = FAKE_SUBSCRIPTION.replace("overall 7.1x", "overall 7.9x")
    (message,) = failures("tap-subscription-button", 1, text)
    assert "7.9" in message and "7.1" in message


# --- upcoming IPO ------------------------------------------------------------------------


def test_upcoming_ipo_open_date() -> None:
    model = (
        "Kaveri Agro Foods Ltd is an upcoming IPO with a proposed opening date of 2 December "
        "2026. Subscription details are not available as bidding has not opened yet."
    )
    fake = "Kaveri Agro Foods Ltd opens on 2 December 2026. Bidding has not opened yet."
    assert failures("upcoming-ipo-no-subscription", 0, model) == []
    assert failures("upcoming-ipo-no-subscription", 0, fake) == []
    invented = model + " It is subscribed 3.4x so far; QIB 5x."
    assert any(
        "must not contain" in m for m in failures("upcoming-ipo-no-subscription", 0, invented)
    )
