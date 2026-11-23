"""The business account and simulated users that appear in webhook payloads."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

_FIRST_NAMES = (
    "Aarav",
    "Ananya",
    "Rohan",
    "Priya",
    "Vikram",
    "Meera",
    "Karthik",
    "Sneha",
    "Arjun",
    "Divya",
)
_LAST_NAMES = (
    "Sharma",
    "Iyer",
    "Patel",
    "Reddy",
    "Gupta",
    "Nair",
    "Mehta",
    "Singh",
)


@dataclass(frozen=True, slots=True)
class BusinessAccount:
    """The WhatsApp Business account the bot runs as (the recipient of inbound webhooks)."""

    waba_id: str = "102290129340398"
    phone_number_id: str = "106540352242922"
    display_phone_number: str = "15550783881"


@dataclass(frozen=True, slots=True)
class SimulatedUser:
    """A simulated WhatsApp end user.

    ``wa_id`` is the id Meta puts in ``contacts[].wa_id`` and ``messages[].from`` (digits only).
    ``phone_number`` is the same number in E.164 form with a leading ``+``.
    """

    wa_id: str
    phone_number: str
    profile_name: str

    @classmethod
    def from_phone_number(cls, phone_number: str, profile_name: str = "Test User") -> SimulatedUser:
        digits = re.sub(r"\D", "", phone_number)
        if not digits:
            raise ValueError(f"phone number has no digits: {phone_number!r}")
        return cls(wa_id=digits, phone_number=f"+{digits}", profile_name=profile_name)


def make_users(
    count: int, *, country_code: str = "91", seed: int | None = None
) -> list[SimulatedUser]:
    """Create ``count`` simulated users, each with a unique wa_id and phone number.

    Numbers are random but valid-looking (for ``91``, ten digits starting 6-9). Pass ``seed``
    for reproducible users.
    """
    if count < 0:
        raise ValueError("count must be >= 0")
    rng = random.Random(seed)
    first_digits = "6789" if country_code == "91" else "23456789"
    seen: set[str] = set()
    users: list[SimulatedUser] = []
    while len(users) < count:
        national = rng.choice(first_digits) + "".join(rng.choice("0123456789") for _ in range(9))
        if national in seen:
            continue
        seen.add(national)
        name = f"{rng.choice(_FIRST_NAMES)} {rng.choice(_LAST_NAMES)}"
        users.append(SimulatedUser.from_phone_number(country_code + national, name))
    return users
