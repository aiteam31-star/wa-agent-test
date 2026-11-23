"""Generators for Meta-style identifiers (message ids, media ids, conversation ids)."""

from __future__ import annotations

import base64
import random
import secrets


def _random_bytes(n: int, rng: random.Random | None) -> bytes:
    return rng.randbytes(n) if rng is not None else secrets.token_bytes(n)


def new_wamid(rng: random.Random | None = None) -> str:
    """Return a WhatsApp message id such as ``wamid.HBgL...``.

    Pass a seeded ``random.Random`` for reproducible ids.
    """
    token = base64.urlsafe_b64encode(_random_bytes(27, rng)).decode("ascii").rstrip("=")
    return "wamid.HBgL" + token.replace("-", "A").replace("_", "B")


def new_media_id(rng: random.Random | None = None) -> str:
    """Return a numeric media id like those in inbound media webhooks."""
    value = rng.randrange(10**15, 10**16) if rng is not None else secrets.randbelow(9 * 10**15)
    return str(value + (0 if rng is not None else 10**15))


def new_conversation_id(rng: random.Random | None = None) -> str:
    """Return a 32-hex-character conversation id (used in status webhooks)."""
    return _random_bytes(16, rng).hex()
