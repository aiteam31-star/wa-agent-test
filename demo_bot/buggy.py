"""BUGGY_MODE: deliberate, realistic defects for the harness to catch.

Three bugs:

* ``listing_date``: the listing date in tool output is off by 1-2 days (a stale/off-by-one
  data bug), so the LLM confidently quotes a wrong date.
* ``buttons``: an IPO reply carries 4 reply buttons (Meta allows 3).
* ``advice``: the reply says "you should apply" (investment advice).

Each fires with probability ``rate`` (seeded for reproducibility), or always for the kinds in
``force``. When ``force`` is non-empty only those kinds fire. With ``enabled=False`` nothing does.
"""

from __future__ import annotations

import logging
import random
from datetime import date, timedelta

logger = logging.getLogger("demo_bot.buggy")

ADVICE_SENTENCE = "You should apply for this IPO, it looks like a great opportunity."
EXTRA_BUTTON_TITLE = "Apply now"


class BuggyMode:
    def __init__(
        self,
        *,
        enabled: bool = False,
        rate: float = 0.3,
        seed: int | None = None,
        force: frozenset[str] = frozenset(),
    ) -> None:
        self.enabled = enabled
        self.rate = rate
        self.force = force
        self._rng = random.Random(seed)
        self.fired: list[str] = []  # for tests and diagnostics; never shown to users

    def fire(self, kind: str) -> bool:
        """Decide whether to inject ``kind`` at this opportunity."""
        if not self.enabled:
            return False
        hit = kind in self.force if self.force else self._rng.random() < self.rate
        if hit:
            self.fired.append(kind)
            logger.warning("BUGGY_MODE injecting %s", kind)
        return hit

    def wrong_listing_date(self, correct: date) -> date:
        """A plausible but wrong listing date."""
        return correct + timedelta(days=self._rng.choice([1, 2]))
