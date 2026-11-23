"""Fixture, tools, BUGGY_MODE and settings."""

from datetime import date

import pytest

from demo_bot.buggy import BuggyMode
from demo_bot.config import DEFAULT_DATA_PATH, Settings
from demo_bot.data import IPOStore
from demo_bot.tools import TOOL_SPECS, ToolRunner


@pytest.fixture(scope="module")
def store() -> IPOStore:
    return IPOStore.load(DEFAULT_DATA_PATH)


# --- fixture ------------------------------------------------------------------------------


def test_fixture_has_five_ipos_with_consistent_dates(store: IPOStore) -> None:
    ipos = store.all()
    assert len(ipos) == 5
    assert len({i.slug for i in ipos}) == 5
    for i in ipos:
        d = i.dates
        assert d.open < d.close < d.allotment < d.listing, i.slug
        assert i.price_band.low < i.price_band.high and i.lot_size > 0


def test_fixture_status_mix_and_subscription_data(store: IPOStore) -> None:
    assert sorted(i.status for i in store.all()) == ["closed", "listed", "open", "open", "upcoming"]
    for i in store.all():
        assert (i.subscription is None) == (i.status == "upcoming"), i.slug
    assert [i.slug for i in store.open_ipos()] == ["nova-textiles", "bharat-greengrid"]


def test_min_investment_is_one_lot_at_upper_band(store: IPOStore) -> None:
    nova = store.by_slug("nova-textiles")
    assert nova is not None and nova.min_investment == 221 * 67


# --- lookups ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query", ["Nova Textiles", "nova textiles ltd", "NOVA-TEXTILES", "nova textiles!", "Nova"]
)
def test_find_is_forgiving(store: IPOStore, query: str) -> None:
    found = store.find(query)
    assert found is not None and found.slug == "nova-textiles"


def test_find_rejects_unknown_empty_and_ambiguous(store: IPOStore) -> None:
    assert store.find("Acme Corp") is None
    assert store.find("") is None
    assert store.find("ltd") is None  # matches every company


def test_find_in_text(store: IPOStore) -> None:
    ipo = store.find_in_text("when does kaveri agro open?")
    assert ipo is not None and ipo.slug == "kaveri-agro"
    assert store.find_in_text("which ipos are open?") is None


# --- tools --------------------------------------------------------------------------------


def test_tool_specs_cover_the_three_tools() -> None:
    assert [t["name"] for t in TOOL_SPECS] == [
        "list_open_ipos",
        "get_ipo_details",
        "get_subscription_status",
    ]


def test_list_open_ipos(store: IPOStore) -> None:
    result = ToolRunner(store).run("list_open_ipos", {})
    assert [i["slug"] for i in result["open_ipos"]] == ["nova-textiles", "bharat-greengrid"]


def test_get_ipo_details(store: IPOStore) -> None:
    result = ToolRunner(store).run("get_ipo_details", {"name": "nova"})
    assert result["found"] and result["slug"] == "nova-textiles"
    ipo = result["ipo"]
    assert ipo["price_band"] == {"low": 210, "high": 221}
    assert ipo["lot_size"] == 67
    assert ipo["dates"] == {
        "open": "2026-11-20",
        "close": "2026-11-25",
        "allotment": "2026-11-26",
        "listing": "2026-11-30",
    }


def test_get_subscription_status(store: IPOStore) -> None:
    runner = ToolRunner(store)
    sub = runner.run("get_subscription_status", {"name": "Nova Textiles"})["subscription"]
    assert (sub["qib"], sub["nii"], sub["retail"], sub["total"]) == (12.4, 8.7, 3.2, 7.1)
    upcoming = runner.run("get_subscription_status", {"name": "Kaveri Agro"})
    assert upcoming["subscription"] is None and "not opened" in upcoming["note"]


def test_unknown_ipo_and_unknown_tool(store: IPOStore) -> None:
    runner = ToolRunner(store)
    missing = runner.run("get_ipo_details", {"name": "Acme"})
    assert missing["found"] is False and len(missing["available"]) == 5
    assert "error" in runner.run("drop_tables", {})


# --- BUGGY_MODE ---------------------------------------------------------------------------


def test_buggy_mode_off_never_fires_even_when_forced() -> None:
    buggy = BuggyMode(enabled=False, rate=1.0, force=frozenset({"advice"}))
    assert not any(buggy.fire(k) for k in ("listing_date", "buttons", "advice") for _ in range(20))
    assert buggy.fired == []


def test_force_fires_only_the_forced_kinds_every_time() -> None:
    buggy = BuggyMode(enabled=True, force=frozenset({"buttons"}))
    assert all(buggy.fire("buttons") for _ in range(10))
    assert not any(buggy.fire("advice") or buggy.fire("listing_date") for _ in range(10))


def test_rate_extremes_and_seed_reproducibility() -> None:
    assert not any(BuggyMode(enabled=True, rate=0.0).fire("advice") for _ in range(50))
    assert all(BuggyMode(enabled=True, rate=1.0).fire("advice") for _ in range(50))
    a = BuggyMode(enabled=True, rate=0.5, seed=7)
    b = BuggyMode(enabled=True, rate=0.5, seed=7)
    seq_a = [a.fire("advice") for _ in range(40)]
    assert seq_a == [b.fire("advice") for _ in range(40)]
    assert 5 < sum(seq_a) < 35  # "sometimes", not always or never


def test_wrong_listing_date_in_tool_output(store: IPOStore) -> None:
    runner = ToolRunner(store, BuggyMode(enabled=True, force=frozenset({"listing_date"}), seed=1))
    listing = runner.run("get_ipo_details", {"name": "nova"})["ipo"]["dates"]["listing"]
    delta = (date.fromisoformat(listing) - date(2026, 11, 30)).days
    assert delta in (1, 2)


def test_clean_tool_output_without_buggy_mode(store: IPOStore) -> None:
    listing = ToolRunner(store).run("get_ipo_details", {"name": "nova"})["ipo"]["dates"]["listing"]
    assert listing == "2026-11-30"


# --- settings -----------------------------------------------------------------------------


def test_settings_defaults() -> None:
    s = Settings.from_env({})
    assert s.llm_provider == "fake" and not s.buggy_mode and s.buggy_force == frozenset()
    assert s.graph_base_url == "https://graph.facebook.com"


def test_settings_from_env() -> None:
    s = Settings.from_env(
        {
            "GRAPH_API_BASE_URL": "http://127.0.0.1:9000/",
            "LLM_PROVIDER": "Ollama",
            "BUGGY_MODE": "1",
            "BUGGY_RATE": "0.5",
            "BUGGY_SEED": "7",
            "BUGGY_FORCE": "buttons, advice",
            "ANTHROPIC_API_KEY": "k",
        }
    )
    assert s.graph_base_url == "http://127.0.0.1:9000"
    assert s.llm_provider == "ollama"
    assert s.buggy_mode and s.buggy_rate == 0.5 and s.buggy_seed == 7
    assert s.buggy_force == {"buttons", "advice"}
    assert s.anthropic_api_key == "k"


@pytest.mark.parametrize(
    "env", [{"BUGGY_FORCE": "nonsense"}, {"BUGGY_RATE": "1.5"}, {"BUGGY_RATE": "-0.1"}]
)
def test_settings_validation(env: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        Settings.from_env(env)
