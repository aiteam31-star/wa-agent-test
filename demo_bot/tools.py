"""LLM tools: list_open_ipos(), get_ipo_details(name), get_subscription_status(name)."""

from __future__ import annotations

from typing import Any

from demo_bot.buggy import BuggyMode
from demo_bot.data import IPO, IPOStore

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "list_open_ipos",
        "description": "List the IPOs that are currently open for bidding.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_ipo_details",
        "description": (
            "Get details of one IPO: sector, exchange, price band, lot size, and the open, "
            "close, allotment and listing dates."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "IPO / company name"}},
            "required": ["name"],
        },
    },
    {
        "name": "get_subscription_status",
        "description": (
            "Get how many times an IPO is subscribed, by category (QIB, NII, retail, employee) "
            "and overall."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "IPO / company name"}},
            "required": ["name"],
        },
    },
]


def _not_found(store: IPOStore, name: str) -> dict[str, Any]:
    return {
        "found": False,
        "error": f"No unique IPO matches {name!r}.",
        "available": [i.name for i in store.all()],
    }


class ToolRunner:
    """Executes tool calls against the fixture (optionally with injected bugs)."""

    def __init__(self, store: IPOStore, buggy: BuggyMode | None = None) -> None:
        self.store = store
        self.buggy = buggy or BuggyMode()

    def run(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "list_open_ipos":
            return self.list_open_ipos()
        if name == "get_ipo_details":
            return self.get_ipo_details(str(arguments.get("name", "")))
        if name == "get_subscription_status":
            return self.get_subscription_status(str(arguments.get("name", "")))
        return {"error": f"unknown tool {name!r}"}

    def list_open_ipos(self) -> dict[str, Any]:
        return {
            "open_ipos": [
                {
                    "slug": i.slug,
                    "name": i.name,
                    "short_name": i.short_name,
                    "price_band": i.price_band.model_dump(),
                    "closes": i.dates.close.isoformat(),
                }
                for i in self.store.open_ipos()
            ]
        }

    def get_ipo_details(self, name: str) -> dict[str, Any]:
        ipo = self.store.find(name)
        if ipo is None:
            return _not_found(self.store, name)
        dates = ipo.dates.model_dump(mode="json")
        if self.buggy.fire("listing_date"):
            dates["listing"] = self.buggy.wrong_listing_date(ipo.dates.listing).isoformat()
        return {
            "found": True,
            "slug": ipo.slug,
            "ipo": {
                "name": ipo.name,
                "short_name": ipo.short_name,
                "sector": ipo.sector,
                "exchange": ipo.exchange,
                "issue_size_cr": ipo.issue_size_cr,
                "price_band": ipo.price_band.model_dump(),
                "lot_size": ipo.lot_size,
                "min_investment": ipo.min_investment,
                "registrar": ipo.registrar,
                "status": ipo.status,
                "dates": dates,
            },
        }

    def get_subscription_status(self, name: str) -> dict[str, Any]:
        ipo: IPO | None = self.store.find(name)
        if ipo is None:
            return _not_found(self.store, name)
        result: dict[str, Any] = {
            "found": True,
            "slug": ipo.slug,
            "name": ipo.name,
            "status": ipo.status,
            "opens": ipo.dates.open.isoformat(),
        }
        if ipo.subscription is None:
            result["subscription"] = None
            result["note"] = "Bidding has not opened yet, so there is no subscription data."
        else:
            result["subscription"] = ipo.subscription.model_dump(mode="json")
        return result
