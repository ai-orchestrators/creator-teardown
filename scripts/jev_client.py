#!/usr/bin/env python3
"""A small client for Jev, TypeSafe's System One decision model. Standard library only.

Jev answers typed questions about a state you send it: yes/no (noul), pick one (choice) or
a place on an ordered rubric (score). It never writes text.

Provider: TypeSafe direct (TYPESAFE_API_KEY). OpenRouter (OPENROUTER_API_KEY) is the
fallback on 429 or 529 only, never on a network failure or a missing key. 401 and 422
raise at once. Keys come from the environment or config/.env and never appear in an
error message, a log line or a file this module writes.

Kill switch: create config/jev.off to stop every call, or config/jev-<decision_id>.off to
stop one decision. Checked before any network request.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from common import config_dir, load_env

MODEL_PIN = "jev-1.13.0"
OPENROUTER_MODEL = "typesafe/jev-1.13"
TYPESAFE_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/systemone"
PRICE_PER_INPUT_TOKEN_USD = 0.042 / 1_000_000
MAX_ESTIMATED_TOKENS = 30_000
RETRY_DELAYS = (0, 1, 2, 4)


class JevError(Exception):
    """Base for every error this module raises."""


class JevAPIError(JevError):
    """An HTTP error from TypeSafe or OpenRouter, carrying the response body's message."""

    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(f"Jev API error {status}: {message}")


class JevUnavailable(JevError):
    """No usable key, or the provider could not be reached."""


class JevDisabled(JevError):
    """A kill switch file is on: config/jev.off or config/jev-<decision_id>.off."""


class JevTooLarge(JevError):
    """The estimated token count is over the pre-call limit."""


class JevInvalidResponse(JevError):
    """A 200 whose body was not valid JSON or did not match the questions."""


@dataclass
class Response:
    answers: dict[str, dict[str, Any]]
    usage: dict[str, Any]
    latency_ms: float
    provider: str
    request_id: str | None
    model: str | None = None


def _key(name: str) -> str | None:
    load_env()
    return os.environ.get(name) or None


def has_key() -> bool:
    """True when the TypeSafe key is set. Classify checks this before a real run."""
    return bool(_key("TYPESAFE_API_KEY"))


def _redact(text: str) -> str:
    """Belt and braces: never let a key echoed back by a provider reach an exception."""
    for name in ("TYPESAFE_API_KEY", "OPENROUTER_API_KEY"):
        value = os.environ.get(name)
        if value and value in text:
            text = text.replace(value, "[redacted]")
    return text


def kill_switch(decision_id: str | None = None) -> str | None:
    folder = config_dir()
    if (folder / "jev.off").exists():
        return "jev.off"
    if decision_id and (folder / f"jev-{decision_id}.off").exists():
        return f"jev-{decision_id}.off"
    return None


def validate_questions(questions: dict) -> dict:
    if not isinstance(questions, dict) or not questions:
        raise ValueError("questions must be a non-empty object")
    for name, q in questions.items():
        if not isinstance(q, dict) or q.get("type") not in ("noul", "choice", "score"):
            raise ValueError(f"{name}: type must be noul, choice or score")
        if not str(q.get("instructions", "")).strip():
            raise ValueError(f"{name}: write explicit instructions")
        criteria = q.get("criteria")
        if q["type"] == "choice" and (not isinstance(criteria, dict) or not 2 <= len(criteria) <= 255):
            raise ValueError(f"{name}: choice needs 2-255 named options")
        if q["type"] == "score" and (not isinstance(criteria, list) or not 2 <= len(criteria) <= 10):
            raise ValueError(f"{name}: score needs 2-10 ordered levels")
    return questions


def _number(value, low, high) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def validate_answers(questions: dict, answers: Any) -> dict:
    if not isinstance(answers, dict):
        raise ValueError("no answers object returned")
    for name, q in questions.items():
        a = answers.get(name)
        if not isinstance(a, dict) or a.get("type") != q["type"]:
            raise ValueError(f"{name}: missing or wrong answer type")
        if q["type"] == "noul":
            if not _number(a.get("noul"), 0, 1):
                raise ValueError(f"{name}: invalid probability")
            continue
        if q["type"] == "choice" and a.get("choice") not in q["criteria"]:
            raise ValueError(f"{name}: unexpected choice")
        if q["type"] == "score" and not _number(a.get("score"), 0, len(q["criteria"]) - 1):
            raise ValueError(f"{name}: score outside the rubric")
        if a.get("confidence") is not None and not _number(a["confidence"], 0, 1):
            raise ValueError(f"{name}: invalid confidence")
    return answers


def estimate_tokens(state: Any, questions: dict) -> int:
    """Characters divided by 4. A cheap pre-call estimate, not a tokeniser."""
    state_chars = len(state) if isinstance(state, str) else len(json.dumps(state, default=str))
    return (state_chars + len(json.dumps(questions, default=str))) // 4


def _post(url: str, key: str, body: dict, timeout: int) -> tuple[dict, dict]:
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            headers = dict(response.headers.items()) if response.headers else {}
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        message = text
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            message = parsed.get("message") or parsed.get("error") or text
        raise JevAPIError(exc.code, _redact(str(message))[:500]) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise JevUnavailable(_redact(f"could not reach {url}: {exc}")) from None
    try:
        data = json.loads(raw)
    except ValueError:
        raise JevInvalidResponse("the provider sent a 200 that was not valid JSON") from None
    if not isinstance(data, dict):
        raise JevInvalidResponse("the provider sent a 200 that was not a JSON object")
    return data, headers


def _call_typesafe(body: dict, timeout: int) -> tuple[dict, dict]:
    key = _key("TYPESAFE_API_KEY")
    if not key:
        raise JevUnavailable("TYPESAFE_API_KEY is not set. Export it, or add it to config/.env (see SETUP.md).")
    last: JevAPIError | None = None
    for delay in RETRY_DELAYS:
        if delay:
            time.sleep(delay)
        try:
            return _post(TYPESAFE_ENDPOINT, key, body, timeout)
        except JevAPIError as exc:
            if exc.status not in (429, 529):
                raise
            last = exc
    raise last  # type: ignore[misc]


def _call_openrouter(body: dict, timeout: int) -> tuple[dict, dict]:
    key = _key("OPENROUTER_API_KEY")
    if not key:
        raise JevUnavailable("TypeSafe is rate limited and OPENROUTER_API_KEY is not set for the fallback.")
    return _post(OPENROUTER_ENDPOINT, key, dict(body, model=OPENROUTER_MODEL), timeout)


def decide(state: Any, questions: dict, *, decision_id: str | None = None, model: str = MODEL_PIN,
           timeout: int = 30) -> Response:
    """Ask every question about one state in one request."""
    switch = kill_switch(decision_id)
    if switch:
        raise JevDisabled(f"Jev calls are switched off by config/{switch}")
    questions = validate_questions(questions)
    estimate = estimate_tokens(state, questions)
    if estimate > MAX_ESTIMATED_TOKENS:
        raise JevTooLarge(f"estimated {estimate} tokens is over the {MAX_ESTIMATED_TOKENS:,} limit")
    body = {"state": state, "model": model, "questions": questions}
    started = time.monotonic()
    provider = "typesafe"
    try:
        data, headers = _call_typesafe(body, timeout)
    except JevAPIError as exc:
        if exc.status not in (429, 529):
            raise
        provider = "openrouter"
        data, headers = _call_openrouter(body, timeout)
    try:
        answers = validate_answers(questions, data.get("answers"))
    except ValueError as exc:
        raise JevInvalidResponse(str(exc)) from None
    request_id = headers.get("x-request-id") or data.get("id") or data.get("request_id")
    return Response(answers=answers, usage=data.get("usage") or {}, latency_ms=(time.monotonic() - started) * 1000,
                    provider=provider, request_id=request_id, model=data.get("model", model))


def decide_many(rows: list, questions: dict, *, workers: int = 8, **kw) -> list:
    """decide() over every row in a thread pool. Order is kept. A row's error comes back in its
    slot as the exception, never retried silently."""
    results: list[Any] = [None] * len(rows)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(decide, row, questions, **kw): i for i, row in enumerate(rows)}
        for future in concurrent.futures.as_completed(futures):
            try:
                results[futures[future]] = future.result()
            except JevError as exc:
                results[futures[future]] = exc
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the Jev setup without making a call.")
    parser.parse_args()
    switch = kill_switch()
    print(f"TYPESAFE_API_KEY: {'set' if has_key() else 'missing'}")
    print(f"OPENROUTER_API_KEY (fallback): {'set' if _key('OPENROUTER_API_KEY') else 'missing'}")
    print(f"kill switch: {'config/' + switch if switch else 'off'}")
    print(f"model: {MODEL_PIN}, US${PRICE_PER_INPUT_TOKEN_USD * 1_000_000:.3f} per million input tokens")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
