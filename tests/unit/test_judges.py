"""The judge protocol, rubrics, Ollama / Anthropic / fake judges, the cache and build_judge."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from wa_agent_test.config import ConfigError, JudgeConfig, ProjectConfig, build_judge
from wa_agent_test.judges import (
    RUBRICS,
    AnthropicJudge,
    CachedJudge,
    FakeJudge,
    JudgeCache,
    JudgeError,
    JudgeRequest,
    OllamaJudge,
    Verdict,
    parse_verdict,
    resolve_rubric,
)
from wa_agent_test.judges.base import SYSTEM_PROMPT, VERDICT_SCHEMA, build_user_prompt


def request(**overrides: Any) -> JudgeRequest:
    fields: dict[str, Any] = {
        "rubric_id": "no_investment_advice",
        "rubric": RUBRICS["no_investment_advice"],
        "reply": "Price band is ₹210-221.",
        "question": "Should I apply?",
        "data": '{"name": "Nova Textiles Ltd"}',
    }
    return JudgeRequest(**{**fields, **overrides})


# --- verdict parsing ----------------------------------------------------------------------


def test_parse_verdict_plain_and_wrapped_json() -> None:
    v = parse_verdict('{"reason": "only facts", "passed": true}', "m")
    assert (v.passed, v.reason, v.model, v.cached) == (True, "only facts", "m", False)
    wrapped = 'Sure! Here you go:\n```json\n{"reason": "it says apply", "passed": false}\n```'
    assert parse_verdict(wrapped).passed is False


def test_parse_verdict_accepts_string_booleans_and_tidies_the_reason() -> None:
    v = parse_verdict('{"reason": "  two\\n  lines ", "passed": "TRUE"}')
    assert v.passed is True and v.reason == "two lines"


def test_parse_verdict_missing_reason_gets_a_placeholder() -> None:
    assert parse_verdict('{"passed": false}').reason == "(no reason given)"


@pytest.mark.parametrize(
    "text",
    ["", "I think it passes.", '{"reason": "x"}', '{"passed": "maybe", "reason": "x"}', "[1, 2]"],
)
def test_parse_verdict_rejects_unusable_answers(text: str) -> None:
    with pytest.raises(JudgeError, match="usable verdict"):
        parse_verdict(text)


# --- prompt and rubrics -------------------------------------------------------------------


def test_prompt_contains_every_part_and_omits_missing_data() -> None:
    prompt = build_user_prompt(request())
    for part in (
        "RUBRIC:",
        "USER MESSAGE:\nShould I apply?",
        "BOT REPLY:\nPrice band",
        "TRUE DATA (JSON):",
    ):
        assert part in prompt
    assert "TRUE DATA (JSON):" not in build_user_prompt(request(data=None))
    assert "(not given)" in build_user_prompt(request(question=""))


def test_built_in_rubrics_and_custom_text() -> None:
    assert set(RUBRICS) == {"no_investment_advice", "factually_consistent"}
    assert resolve_rubric("no_investment_advice") == (
        "no_investment_advice",
        RUBRICS["no_investment_advice"],
    )
    assert resolve_rubric(" factually_consistent ")[0] == "factually_consistent"
    assert resolve_rubric("Fail if the bot swears.") == ("custom", "Fail if the bot swears.")


def test_rubrics_cover_what_they_promise() -> None:
    advice = RUBRICS["no_investment_advice"].lower()
    for word in ("apply", "hinglish", "listing gains", "opinion", "your money"):
        assert word in advice or word.replace("your", "user's") in advice
    facts = RUBRICS["factually_consistent"].lower()
    for word in (
        "times subscribed",
        "percentage",
        "closing date",
        "not in the data",
        "listing gains",
    ):
        assert word in facts


# --- Ollama -------------------------------------------------------------------------------


@respx.mock
async def test_ollama_judge_request_and_verdict() -> None:
    route = respx.post("http://localhost:11434/api/chat").respond(
        json={"message": {"content": '{"reason": "only facts", "passed": true}'}}
    )
    async with httpx.AsyncClient() as client:
        verdict = await OllamaJudge(model="llama3.2:3b", client=client).judge(request())
    assert (verdict.passed, verdict.reason, verdict.model) == (True, "only facts", "llama3.2:3b")
    body = json.loads(route.calls.last.request.content)
    assert body["model"] == "llama3.2:3b" and body["stream"] is False
    assert body["options"] == {"temperature": 0}
    assert body["format"] == VERDICT_SCHEMA  # forces valid JSON with "reason" before "passed"
    assert list(VERDICT_SCHEMA["properties"]) == ["reason", "passed"]
    system, user = body["messages"]
    assert system == {"role": "system", "content": SYSTEM_PROMPT}
    assert "BOT REPLY:\nPrice band is ₹210-221." in user["content"]


@respx.mock
async def test_ollama_judge_errors_become_judge_errors() -> None:
    respx.post("http://localhost:11434/api/chat").respond(500)
    async with httpx.AsyncClient() as client:
        judge = OllamaJudge(model="m", client=client)
        with pytest.raises(JudgeError, match="couldn't reach Ollama"):
            await judge.judge(request())
    respx.post("http://localhost:11434/api/chat").respond(
        json={"message": {"content": "I cannot decide."}}
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(JudgeError, match="usable verdict"):
            await OllamaJudge(model="m", client=client).judge(request())


@respx.mock
async def test_ollama_judge_unreachable_server() -> None:
    respx.post("http://localhost:11434/api/chat").mock(side_effect=httpx.ConnectError("refused"))
    async with httpx.AsyncClient() as client:
        with pytest.raises(JudgeError, match="ConnectError"):
            await OllamaJudge(model="m", client=client).judge(request())


# --- Anthropic ----------------------------------------------------------------------------


@respx.mock
async def test_anthropic_judge_request_and_verdict() -> None:
    route = respx.post("https://api.anthropic.com/v1/messages").respond(
        json={"content": [{"type": "text", "text": '{"reason": "it says apply", "passed": false}'}]}
    )
    async with httpx.AsyncClient() as client:
        judge = AnthropicJudge(api_key="sk-test", model="claude-haiku-5-5", client=client)
        verdict = await judge.judge(request())
    assert (verdict.passed, verdict.reason) == (False, "it says apply")
    sent = route.calls.last.request
    assert (
        sent.headers["x-api-key"] == "sk-test" and sent.headers["anthropic-version"] == "2023-06-01"
    )
    body = json.loads(sent.content)
    assert body["model"] == "claude-haiku-5-5" and body["temperature"] == 0
    assert body["system"] == SYSTEM_PROMPT
    assert body["messages"][0]["role"] == "user" and "BOT REPLY" in body["messages"][0]["content"]


@respx.mock
async def test_anthropic_judge_http_error() -> None:
    respx.post("https://api.anthropic.com/v1/messages").respond(401)
    async with httpx.AsyncClient() as client:
        with pytest.raises(JudgeError, match="couldn't reach Anthropic"):
            await AnthropicJudge(api_key="bad", model="m", client=client).judge(request())


# --- fake judge ---------------------------------------------------------------------------


async def test_fake_judge_passes_by_default_and_records_requests() -> None:
    judge = FakeJudge()
    verdict = await judge.judge(request())
    assert verdict.passed and judge.requests == [request()]
    scripted = FakeJudge(lambda r: Verdict(passed="apply" not in r.reply, reason="scripted"))
    assert (await scripted.judge(request(reply="you should apply"))).passed is False


# --- cache --------------------------------------------------------------------------------


class CountingJudge:
    provider = "counting"
    model = "m1"

    def __init__(self, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    async def judge(self, req: JudgeRequest) -> Verdict:
        self.calls += 1
        if self.fail:
            raise JudgeError("down")
        return Verdict(
            passed="apply" not in req.reply, reason=f"call {self.calls}", model=self.model
        )

    async def aclose(self) -> None:
        return None


async def test_a_repeated_request_is_answered_from_disk(tmp_path: Path) -> None:
    inner = CountingJudge()
    judge = CachedJudge(inner, JudgeCache(tmp_path))
    first = await judge.judge(request())
    second = await judge.judge(request())
    assert inner.calls == 1 and (judge.misses, judge.hits) == (1, 1)
    assert first.cached is False and second.cached is True
    assert (second.passed, second.reason) == (first.passed, first.reason)  # reruns are stable


async def test_the_cache_survives_a_new_process(tmp_path: Path) -> None:
    await CachedJudge(CountingJudge(), JudgeCache(tmp_path)).judge(request())
    fresh_inner = CountingJudge()
    verdict = await CachedJudge(fresh_inner, JudgeCache(tmp_path)).judge(request())
    assert verdict.cached and fresh_inner.calls == 0


@pytest.mark.parametrize(
    "change",
    [
        {"reply": "something else"},
        {"question": "another question"},
        {"data": None},
        {"rubric": "a different rubric text"},
    ],
)
async def test_anything_that_changes_the_verdict_changes_the_key(
    tmp_path: Path, change: dict[str, Any]
) -> None:
    inner = CountingJudge()
    judge = CachedJudge(inner, JudgeCache(tmp_path))
    await judge.judge(request())
    await judge.judge(request(**change))
    assert inner.calls == 2


async def test_a_different_model_or_provider_does_not_reuse_verdicts(tmp_path: Path) -> None:
    cache = JudgeCache(tmp_path)
    a, b = CountingJudge(), CountingJudge()
    b.model = "m2"
    await CachedJudge(a, cache).judge(request())
    await CachedJudge(b, cache).judge(request())
    assert (a.calls, b.calls) == (1, 1)
    assert cache.key("p", "m", request()) != cache.key("q", "m", request())


async def test_errors_are_never_cached(tmp_path: Path) -> None:
    cache = JudgeCache(tmp_path)
    broken = CountingJudge(fail=True)
    with pytest.raises(JudgeError):
        await CachedJudge(broken, cache).judge(request())
    healthy = CountingJudge()
    verdict = await CachedJudge(healthy, cache).judge(request())
    assert healthy.calls == 1 and verdict.cached is False


async def test_a_damaged_cache_file_just_asks_the_judge_again(tmp_path: Path) -> None:
    cache = JudgeCache(tmp_path)
    inner = CountingJudge()
    judge = CachedJudge(inner, cache)
    await judge.judge(request())
    (file,) = tmp_path.rglob("*.json")  # noqa: ASYNC240
    file.write_text("{not json", encoding="utf-8")
    await judge.judge(request())
    assert inner.calls == 2


def test_cache_key_is_stable_and_hex() -> None:
    key = JudgeCache.key("ollama", "m", request())
    assert key == JudgeCache.key("ollama", "m", request()) and len(key) == 64


# --- build_judge --------------------------------------------------------------------------


def project(judge: dict[str, Any] | None = None) -> ProjectConfig:
    data: dict[str, Any] = {"bot": {"webhook_url": "http://x/webhook", "app_secret": "s"}}
    if judge is not None:
        data["judge"] = judge
    return ProjectConfig.model_validate(data)


async def test_build_judge_defaults_to_cached_ollama(tmp_path: Path) -> None:
    judge = build_judge(project(), tmp_path)
    try:
        assert isinstance(judge, CachedJudge)
        assert (judge.provider, judge.model) == ("ollama", "llama3.2:3b")
    finally:
        await judge.aclose()


async def test_build_judge_without_cache_and_with_cache_disabled(tmp_path: Path) -> None:
    for judge in (
        build_judge(project(), tmp_path, use_cache=False),
        build_judge(project({"cache_dir": None}), tmp_path),
    ):
        try:
            assert isinstance(judge, OllamaJudge)
        finally:
            await judge.aclose()


async def test_build_judge_anthropic_needs_a_key(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="api_key"):
        build_judge(project({"provider": "anthropic"}), tmp_path)
    judge = build_judge(
        project({"provider": "anthropic", "api_key": "k", "cache_dir": None}), tmp_path
    )
    try:
        assert isinstance(judge, AnthropicJudge) and judge.model == "claude-haiku-5-5"
    finally:
        await judge.aclose()


def test_build_judge_fake_is_never_cached(tmp_path: Path) -> None:
    assert isinstance(build_judge(project({"provider": "fake"}), tmp_path), FakeJudge)


def test_judge_config_validation() -> None:
    assert JudgeConfig().provider == "ollama" and JudgeConfig().cache_dir
    with pytest.raises(ValueError):
        JudgeConfig(provider="gpt")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        JudgeConfig(timeout_s=0)
