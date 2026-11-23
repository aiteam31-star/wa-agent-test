"""Bot configuration, read from environment variables."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

BUG_KINDS = frozenset({"listing_date", "buttons", "advice"})
DEFAULT_DATA_PATH = Path(__file__).parent / "data" / "ipos.json"
_TRUE = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """All settings. Build from the environment with :meth:`from_env`."""

    # WhatsApp / Graph API
    app_secret: str = "dev-app-secret"  # APP_SECRET: verifies X-Hub-Signature-256
    verify_token: str = "dev-verify-token"  # VERIFY_TOKEN: GET handshake
    access_token: str = "dev-access-token"  # WHATSAPP_ACCESS_TOKEN: bearer for sends
    graph_base_url: str = "https://graph.facebook.com"  # GRAPH_API_BASE_URL (point at the mock)
    graph_version: str = "v21.0"  # GRAPH_API_VERSION

    # LLM
    llm_provider: str = "fake"  # LLM_PROVIDER: anthropic | ollama | fake
    anthropic_api_key: str | None = None  # ANTHROPIC_API_KEY
    anthropic_model: str = "claude-haiku-5-5"  # ANTHROPIC_MODEL
    anthropic_base_url: str = "https://api.anthropic.com"  # ANTHROPIC_BASE_URL
    ollama_base_url: str = "http://localhost:11434"  # OLLAMA_BASE_URL
    ollama_model: str = "llama3.1"  # OLLAMA_MODEL
    request_timeout_s: float = 60.0  # LLM_TIMEOUT_S

    # Data / memory
    data_path: Path = DEFAULT_DATA_PATH  # IPO_DATA_PATH
    history_max_messages: int = 40  # HISTORY_MAX_MESSAGES

    # Bug injection
    buggy_mode: bool = False  # BUGGY_MODE
    buggy_rate: float = 0.3  # BUGGY_RATE: chance each bug fires per opportunity
    buggy_seed: int | None = None  # BUGGY_SEED: makes "sometimes" reproducible
    buggy_force: frozenset[str] = field(default_factory=frozenset)  # BUGGY_FORCE=a,b

    def __post_init__(self) -> None:
        if not 0.0 <= self.buggy_rate <= 1.0:
            raise ValueError("BUGGY_RATE must be between 0 and 1")
        unknown = self.buggy_force - BUG_KINDS
        if unknown:
            raise ValueError(
                f"unknown BUGGY_FORCE kinds {sorted(unknown)}; use {sorted(BUG_KINDS)}"
            )

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        e = os.environ if env is None else env
        defaults = cls()

        def text(key: str, default: str) -> str:
            return e.get(key) or default

        force = frozenset(p.strip() for p in e.get("BUGGY_FORCE", "").split(",") if p.strip())
        seed = e.get("BUGGY_SEED")
        return cls(
            app_secret=text("APP_SECRET", defaults.app_secret),
            verify_token=text("VERIFY_TOKEN", defaults.verify_token),
            access_token=text("WHATSAPP_ACCESS_TOKEN", defaults.access_token),
            graph_base_url=text("GRAPH_API_BASE_URL", defaults.graph_base_url).rstrip("/"),
            graph_version=text("GRAPH_API_VERSION", defaults.graph_version),
            llm_provider=text("LLM_PROVIDER", defaults.llm_provider).lower(),
            anthropic_api_key=e.get("ANTHROPIC_API_KEY") or None,
            anthropic_model=text("ANTHROPIC_MODEL", defaults.anthropic_model),
            anthropic_base_url=text("ANTHROPIC_BASE_URL", defaults.anthropic_base_url).rstrip("/"),
            ollama_base_url=text("OLLAMA_BASE_URL", defaults.ollama_base_url).rstrip("/"),
            ollama_model=text("OLLAMA_MODEL", defaults.ollama_model),
            request_timeout_s=float(text("LLM_TIMEOUT_S", str(defaults.request_timeout_s))),
            data_path=Path(text("IPO_DATA_PATH", str(defaults.data_path))),
            history_max_messages=int(text("HISTORY_MAX_MESSAGES", "40")),
            buggy_mode=e.get("BUGGY_MODE", "").strip().lower() in _TRUE,
            buggy_rate=float(text("BUGGY_RATE", str(defaults.buggy_rate))),
            buggy_seed=int(seed) if seed else None,
            buggy_force=force,
        )
