"""jev_client against a mocked HTTP layer. Offline: nothing here reaches the network."""
from __future__ import annotations

import atexit
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
_CONFIG = tempfile.mkdtemp(prefix="ct-config-")
atexit.register(shutil.rmtree, _CONFIG, True)
os.environ["CREATOR_TEARDOWN_CONFIG"] = _CONFIG

import jev_client  # noqa: E402

QUESTIONS = {
    "kind": {"type": "choice", "instructions": "Which kind is the text?",
             "criteria": {"tip": "A tip.", "story": "A story."}},
    "useful": {"type": "noul", "instructions": "Is the text useful?",
               "criteria": {"true": "Useful.", "false": "Not useful."}},
    "detail": {"type": "score", "instructions": "How detailed is the text?",
               "criteria": ["Vague.", "Some detail.", "Concrete."]},
}
GOOD = {"answers": {"kind": {"type": "choice", "choice": "tip", "probabilities": {"tip": 0.9, "story": 0.1},
                             "confidence": 0.8},
                    "useful": {"type": "noul", "noul": 0.7},
                    "detail": {"type": "score", "score": 1.4, "probabilities": {"0": 0.1, "1": 0.4, "2": 0.5},
                               "confidence": 0.6}},
        "usage": {"input_tokens": 120, "cost": 0.000005}, "model": "jev-1.13.0"}
FAKE_TS_KEY = "ts-test-key-not-real-0001"
FAKE_OR_KEY = "or-test-key-not-real-0002"


class FakeResponse:
    def __init__(self, payload, headers=None):
        self._body = json.dumps(payload).encode()
        self.headers = headers or {"x-request-id": "req-1"}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code, body):
    return urllib.error.HTTPError("https://example.invalid", code, "error", {}, io.BytesIO(json.dumps(body).encode()))


class Base(unittest.TestCase):
    def setUp(self):
        self.config = tempfile.mkdtemp(prefix="ct-jev-")
        self.addCleanup(shutil.rmtree, self.config, True)
        env = {k: v for k, v in os.environ.items() if k not in ("TYPESAFE_API_KEY", "OPENROUTER_API_KEY")}
        env["CREATOR_TEARDOWN_CONFIG"] = self.config
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        delays = mock.patch.object(jev_client, "RETRY_DELAYS", (0, 0, 0, 0))
        delays.start()
        self.addCleanup(delays.stop)
        self.requests = []

    def urlopen(self, *responses):
        queue = list(responses)

        def fake(request, timeout=None):
            self.requests.append(request)
            item = queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return mock.patch.object(jev_client.urllib.request, "urlopen", side_effect=fake)


class Decide(Base):
    def test_happy_path_sends_pinned_model_and_bearer(self):
        os.environ["TYPESAFE_API_KEY"] = FAKE_TS_KEY
        with self.urlopen(FakeResponse(GOOD)):
            response = jev_client.decide({"text": "Do this first."}, QUESTIONS, decision_id="test.v1")
        self.assertEqual(response.answers["kind"]["choice"], "tip")
        self.assertEqual(response.provider, "typesafe")
        self.assertEqual(response.request_id, "req-1")
        self.assertEqual(response.usage["input_tokens"], 120)
        request = self.requests[0]
        self.assertEqual(request.full_url, jev_client.TYPESAFE_ENDPOINT)
        self.assertEqual(request.get_header("Authorization"), f"Bearer {FAKE_TS_KEY}")
        body = json.loads(request.data)
        self.assertEqual(body["model"], "jev-1.13.0")
        self.assertEqual(body["state"], {"text": "Do this first."})
        self.assertEqual(set(body["questions"]), set(QUESTIONS))

    def test_429_retries_then_falls_back_to_openrouter(self):
        os.environ["TYPESAFE_API_KEY"] = FAKE_TS_KEY
        os.environ["OPENROUTER_API_KEY"] = FAKE_OR_KEY
        busy = [http_error(429, {"message": "slow down"}) for _ in jev_client.RETRY_DELAYS]
        with self.urlopen(*busy, FakeResponse(GOOD)):
            response = jev_client.decide("state", QUESTIONS)
        self.assertEqual(response.provider, "openrouter")
        self.assertEqual(len(self.requests), len(jev_client.RETRY_DELAYS) + 1)
        fallback = self.requests[-1]
        self.assertEqual(fallback.full_url, jev_client.OPENROUTER_ENDPOINT)
        self.assertEqual(fallback.get_header("Authorization"), f"Bearer {FAKE_OR_KEY}")
        self.assertEqual(json.loads(fallback.data)["model"], "typesafe/jev-1.13")

    def test_529_without_fallback_key_is_unavailable(self):
        os.environ["TYPESAFE_API_KEY"] = FAKE_TS_KEY
        busy = [http_error(529, {"message": "overloaded"}) for _ in jev_client.RETRY_DELAYS]
        with self.urlopen(*busy), self.assertRaises(jev_client.JevUnavailable):
            jev_client.decide("state", QUESTIONS)

    def test_401_and_422_raise_at_once_without_fallback(self):
        os.environ["TYPESAFE_API_KEY"] = FAKE_TS_KEY
        os.environ["OPENROUTER_API_KEY"] = FAKE_OR_KEY
        for code in (401, 422):
            self.requests.clear()
            with self.urlopen(http_error(code, {"message": "nope"})), self.assertRaises(jev_client.JevAPIError) as caught:
                jev_client.decide("state", QUESTIONS)
            self.assertEqual(caught.exception.status, code)
            self.assertEqual(len(self.requests), 1)

    def test_missing_key_makes_no_request(self):
        with self.urlopen(), self.assertRaises(jev_client.JevUnavailable) as caught:
            jev_client.decide("state", QUESTIONS)
        self.assertEqual(self.requests, [])
        self.assertIn("TYPESAFE_API_KEY", str(caught.exception))
        self.assertFalse(jev_client.has_key())

    def test_key_from_config_env_file(self):
        Path(self.config, ".env").write_text(f"# keys\nexport TYPESAFE_API_KEY='{FAKE_TS_KEY}'\n")
        self.assertTrue(jev_client.has_key())
        with self.urlopen(FakeResponse(GOOD)):
            jev_client.decide("state", QUESTIONS)
        self.assertEqual(self.requests[0].get_header("Authorization"), f"Bearer {FAKE_TS_KEY}")

    def test_key_never_appears_in_errors(self):
        os.environ["TYPESAFE_API_KEY"] = FAKE_TS_KEY
        echo = http_error(400, {"message": f"bad key {FAKE_TS_KEY}"})
        with self.urlopen(echo), self.assertRaises(jev_client.JevAPIError) as caught:
            jev_client.decide("state", QUESTIONS)
        self.assertNotIn(FAKE_TS_KEY, str(caught.exception))
        offline = urllib.error.URLError(f"refused {FAKE_TS_KEY}")
        with self.urlopen(offline), self.assertRaises(jev_client.JevUnavailable) as caught:
            jev_client.decide("state", QUESTIONS)
        self.assertNotIn(FAKE_TS_KEY, str(caught.exception))

    def test_kill_switches(self):
        os.environ["TYPESAFE_API_KEY"] = FAKE_TS_KEY
        Path(self.config, "jev-test.v1.off").touch()
        with self.urlopen(), self.assertRaises(jev_client.JevDisabled):
            jev_client.decide("state", QUESTIONS, decision_id="test.v1")
        with self.urlopen(FakeResponse(GOOD)):
            jev_client.decide("state", QUESTIONS, decision_id="other.v1")
        self.assertEqual(len(self.requests), 1)
        Path(self.config, "jev.off").touch()
        with self.urlopen(), self.assertRaises(jev_client.JevDisabled):
            jev_client.decide("state", QUESTIONS, decision_id="other.v1")
        self.assertEqual(len(self.requests), 1)

    def test_answer_outside_the_form_is_invalid(self):
        os.environ["TYPESAFE_API_KEY"] = FAKE_TS_KEY
        bad = json.loads(json.dumps(GOOD))
        bad["answers"]["kind"]["choice"] = "rant"
        with self.urlopen(FakeResponse(bad)), self.assertRaises(jev_client.JevInvalidResponse):
            jev_client.decide("state", QUESTIONS)
        bad = json.loads(json.dumps(GOOD))
        bad["answers"]["detail"]["score"] = 7
        with self.urlopen(FakeResponse(bad)), self.assertRaises(jev_client.JevInvalidResponse):
            jev_client.decide("state", QUESTIONS)

    def test_too_large_and_bad_form_fail_before_the_network(self):
        os.environ["TYPESAFE_API_KEY"] = FAKE_TS_KEY
        with self.urlopen(), self.assertRaises(jev_client.JevTooLarge):
            jev_client.decide("x" * 200_000, QUESTIONS)
        with self.urlopen(), self.assertRaises(ValueError):
            jev_client.decide("state", {"kind": {"type": "choice", "instructions": "x", "criteria": {"only": "one"}}})
        self.assertEqual(self.requests, [])


class Many(Base):
    def test_order_kept_and_errors_in_their_slot(self):
        os.environ["TYPESAFE_API_KEY"] = FAKE_TS_KEY

        def fake(state, questions, **kw):
            if state == "bad":
                raise jev_client.JevAPIError(422, "schema")
            return jev_client.Response(answers={"echo": state}, usage={}, latency_ms=1.0, provider="typesafe",
                                       request_id=None)
        with mock.patch.object(jev_client, "decide", side_effect=fake):
            out = jev_client.decide_many(["a", "bad", "c", "d"], QUESTIONS, workers=3, decision_id="test.v1")
        self.assertEqual([r.answers["echo"] for r in (out[0], out[2], out[3])], ["a", "c", "d"])
        self.assertIsInstance(out[1], jev_client.JevAPIError)

    def test_estimate_and_price(self):
        self.assertEqual(jev_client.estimate_tokens("x" * 400, {}), (400 + 2) // 4)
        self.assertAlmostEqual(jev_client.PRICE_PER_INPUT_TOKEN_USD * 1_000_000, 0.042)


if __name__ == "__main__":
    unittest.main()
