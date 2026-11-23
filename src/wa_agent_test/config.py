"""Project config (``wa-agent-test.yaml``): the bot, the mock Graph API, truth sources."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from wa_agent_test import yamlio
from wa_agent_test.payloads import BusinessAccount
from wa_agent_test.truth import FileTruthSource, TruthSource

CONFIG_NAME = "wa-agent-test.yaml"
_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


class ConfigError(Exception):
    pass


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BotConfig(_Strict):
    webhook_url: str
    app_secret: str
    verify_token: str | None = None
    timeout_s: float = Field(10.0, gt=0)


class MockConfig(_Strict):
    host: str = "127.0.0.1"
    port: int = Field(9000, ge=0, le=65535)
    access_token: str | None = None


class RunConfig(_Strict):
    concurrency: int = Field(4, ge=1)
    seed: int | None = 1
    scenario_timeout_s: float = Field(300.0, gt=0)


class BusinessConfig(_Strict):
    waba_id: str = BusinessAccount().waba_id
    phone_number_id: str = BusinessAccount().phone_number_id
    display_phone_number: str = BusinessAccount().display_phone_number


class TruthSourceConfig(_Strict):
    type: Literal["file"]
    path: str
    records: str | None = None
    entity_match: list[str] = ["name"]
    fields: dict[str, str] = {}


class ProjectConfig(_Strict):
    bot: BotConfig
    mock: MockConfig = MockConfig()
    run: RunConfig = RunConfig()
    business: BusinessConfig = BusinessConfig()
    truth_sources: dict[str, TruthSourceConfig] = {}

    def business_account(self) -> BusinessAccount:
        return BusinessAccount(**self.business.model_dump())


def _interpolate(value: Any) -> Any:
    """Replace ``${VAR}`` / ``${VAR:-default}`` in every string."""
    if isinstance(value, str):

        def sub(m: re.Match[str]) -> str:
            name, default = m.group(1), m.group(2)
            found = os.environ.get(name)
            if found is not None:
                return found
            if default is not None:
                return default
            raise ConfigError(f"environment variable {name} is not set (used as ${{{name}}})")

        return _ENV.sub(sub, value)
    if isinstance(value, list):
        return [_interpolate(v) for v in value]
    if isinstance(value, dict):
        return {k: _interpolate(v) for k, v in value.items()}
    return value


def find_config(explicit: Path | None, scenarios_path: Path) -> Path:
    """The ``--config`` path, or the nearest ``wa-agent-test.yaml``.

    Looked for in the current folder, the scenarios folder, then its parent.
    """
    if explicit is not None:
        if not explicit.is_file():
            raise ConfigError(f"config file not found: {explicit}")
        return explicit
    base = scenarios_path if scenarios_path.is_dir() else scenarios_path.parent
    for folder in (Path.cwd(), base, base.parent):
        candidate = folder / CONFIG_NAME
        if candidate.is_file():
            return candidate
    raise ConfigError(f"no {CONFIG_NAME} found; create one or pass --config")


def load_config(path: Path) -> ProjectConfig:
    try:
        raw = yamlio.load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: must be a YAML mapping")
    try:
        return ProjectConfig.model_validate(_interpolate(raw))
    except ValidationError as exc:
        lines = [f"{path}: {'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
        raise ConfigError("\n".join(lines)) from exc


def build_truth_sources(config: ProjectConfig, base_dir: Path) -> dict[str, TruthSource]:
    """Create the truth sources; relative file paths are relative to the config file."""
    sources: dict[str, TruthSource] = {}
    for name, cfg in config.truth_sources.items():
        file = Path(cfg.path)
        if not file.is_absolute():
            file = base_dir / file
        if not file.is_file():
            raise ConfigError(f"truth source {name!r}: file not found: {file}")
        sources[name] = FileTruthSource(
            file, records=cfg.records, entity_match=cfg.entity_match, fields=cfg.fields
        )
    return sources
