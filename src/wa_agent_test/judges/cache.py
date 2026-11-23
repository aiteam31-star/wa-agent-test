"""On-disk cache of judge verdicts, so re-running a suite doesn't call the judge again."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from wa_agent_test.judges.base import SYSTEM_PROMPT, Judge, JudgeRequest, Verdict

CACHE_VERSION = 1


class JudgeCache:
    """One small JSON file per verdict, named by a hash of everything that affects the verdict."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    @staticmethod
    def key(provider: str, model: str, request: JudgeRequest) -> str:
        material = {
            "v": CACHE_VERSION,
            "provider": provider,
            "model": model,
            "system": SYSTEM_PROMPT,  # editing the judge's instructions changes the key
            "rubric": request.rubric,  # editing a rubric's wording changes the key
            "question": request.question,
            "reply": request.reply,
            "data": request.data,
        }
        blob = json.dumps(material, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    def _path(self, key: str) -> Path:
        return self.directory / key[:2] / f"{key}.json"

    def get(self, key: str) -> Verdict | None:
        try:
            data = json.loads(self._path(key).read_text(encoding="utf-8"))
            return Verdict(
                passed=bool(data["passed"]),
                reason=str(data["reason"]),
                model=str(data.get("model", "")),
                cached=True,
            )
        except (OSError, ValueError, KeyError):
            return None  # missing or damaged: just ask the judge again

    def put(self, key: str, verdict: Verdict) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"passed": verdict.passed, "reason": verdict.reason, "model": verdict.model}
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)  # atomic, so a crash never leaves half a file


class CachedJudge:
    """Wraps a judge: a repeated request is answered from disk. Errors are never cached."""

    def __init__(self, inner: Judge, cache: JudgeCache) -> None:
        self._inner = inner
        self._cache = cache
        self.provider = inner.provider
        self.model = inner.model
        self.hits = 0
        self.misses = 0

    async def judge(self, request: JudgeRequest) -> Verdict:
        key = self._cache.key(self.provider, self.model, request)
        found = self._cache.get(key)
        if found is not None:
            self.hits += 1
            return found
        self.misses += 1
        verdict = await self._inner.judge(request)
        self._cache.put(key, verdict)
        return verdict

    async def aclose(self) -> None:
        await self._inner.aclose()
