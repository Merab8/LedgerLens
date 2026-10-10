import json
from datetime import date, timedelta
from decimal import Decimal as D
from types import SimpleNamespace

import ai_assistant as ai
import finance as f

TODAY = date(2026, 10, 10)
KEY = "gsk_SECRET_TEST_KEY_123"


def snapshot(amount=50000):
    d = f.load_sample_data(TODAY)
    s = f.Scenario("Equipment purchase", D(amount), TODAY + timedelta(days=7), D(30000))
    return f.build_snapshot(d, TODAY, TODAY - timedelta(days=30), TODAY, s, 30, D(30000))


class FakeClient:
    def __init__(self, text="Mocked answer.", exc=None):
        self.calls, self._text, self._exc = [], text, exc
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        if self._exc:
            raise self._exc
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self._text))])


def cfg(key=KEY, model="test/model"):
    return ai.AIConfig(key, model)


def test_missing_key_gives_setup_message(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(ai, "load_dotenv", lambda *a, **k: None, raising=False)
    r = ai.generate_answer("hi", [], snapshot())
    assert not r.ok and r.error_code == "missing_key" and ".env" in r.message


def test_placeholder_key_counts_as_missing(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "your_api_key_here")
    assert not ai.get_config().configured


def test_model_is_configurable_through_environment(monkeypatch):
    monkeypatch.setenv("GROQ_MODEL", "some/other-model")
    assert ai.get_config().model == "some/other-model"
    monkeypatch.delenv("GROQ_MODEL")
    assert ai.get_config().model == ai.DEFAULT_MODEL == "openai/gpt-oss-120b"


def test_success_uses_selected_model_and_current_scenario_figures():
    client = FakeClient()
    r = ai.generate_answer("Can I afford it?", [], snapshot(50000), lambda c: client, cfg(model="test/model"))
    assert r.ok and r.text == "Mocked answer." and r.model == "test/model"
    call = client.calls[0]
    assert call["model"] == "test/model"
    prompt = call["messages"][-1]["content"]
    sc = snapshot(50000)["active_scenario"]
    assert sc["scenario_lowest_balance"]["amount"] in prompt and "Equipment purchase" in prompt


def test_context_is_refreshed_each_call_not_stale():
    c1, c2 = FakeClient(), FakeClient()
    ai.generate_answer("q", [], snapshot(50000), lambda c: c1, cfg())
    ai.generate_answer("q", [{"role": "assistant", "content": "old figure PKR 1"}], snapshot(90000), lambda c: c2, cfg())
    assert '"purchase_amount": "50000.00"' in c1.calls[0]["messages"][-1]["content"]
    assert '"purchase_amount": "90000.00"' in c2.calls[0]["messages"][-1]["content"]


def test_system_prompt_forbids_inventing_facts():
    msgs = ai.build_messages("q", [], snapshot())
    sys = msgs[0]["content"]
    assert msgs[0]["role"] == "system"
    assert "Do not invent transactions, balances" in sys and "not guaranteed cash" in sys
    assert "untrusted data" in sys


def test_history_is_limited_and_fallbacks_are_not_sent():
    hist = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"} for i in range(20)]
    hist.append({"role": "assistant", "content": "deterministic", "kind": "fallback"})
    msgs = ai.build_messages("q", hist, snapshot())
    assert len(msgs) <= 1 + ai.MAX_HISTORY_MESSAGES + 1
    assert all(m["content"] != "deterministic" for m in msgs)


def test_api_failures_are_handled_without_leaking_secrets():
    class RateLimitError(Exception):
        status_code = 429

    class AuthenticationError(Exception):
        status_code = 401

    class APITimeoutError(Exception):
        pass

    class APIConnectionError(Exception):
        pass

    for exc, code in [(RateLimitError(f"too many {KEY}"), "rate_limit"), (AuthenticationError(f"bad {KEY}"), "auth"),
                      (APITimeoutError(KEY), "timeout"), (APIConnectionError(KEY), "network"),
                      (RuntimeError(f"boom {KEY}"), "unknown")]:
        r = ai.generate_answer("q", [], snapshot(), lambda c, e=exc: FakeClient(exc=e), cfg())
        assert not r.ok and r.error_code == code
        assert KEY not in r.message and r.message


def test_empty_model_response_is_reported():
    r = ai.generate_answer("q", [], snapshot(), lambda c: FakeClient(text="  "), cfg())
    assert not r.ok and r.error_code == "empty"


def test_context_contains_no_secrets():
    assert KEY not in json.dumps(ai.build_messages("q", [], snapshot()))


def test_deterministic_summary_is_labelled_data_not_ai():
    text = ai.deterministic_summary(snapshot())
    assert "PKR 200,000" in text and "Equipment purchase" in text
