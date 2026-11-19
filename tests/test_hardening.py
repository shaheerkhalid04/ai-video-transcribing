"""Checks for the model swap, the health route and the video length cap.

Groq and SerpApi are never called: the network pieces are replaced with fakes.
Run from the project root:  python -m pytest -q
"""

import os
import sys
import types
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

import agent  # noqa: E402
import config  # noqa: E402
import tools  # noqa: E402


class FakeCompletions:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("model_decommissioned")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="OK"))])


def install_fake_groq(monkeypatch, completions):
    module = types.ModuleType("groq")

    class Groq:
        def __init__(self, api_key=None):
            self.chat = SimpleNamespace(completions=completions)

    module.Groq = Groq
    module.BadRequestError = type("BadRequestError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "groq", module)


def test_default_model_is_not_retired():
    assert config.AGENT_MODEL != "llama-3.3-70b-versatile"
    assert config.AGENT_MODEL.startswith("openai/gpt-oss") or "GROQ_MODEL" in os.environ


def test_verify_model_makes_a_real_call_with_low_reasoning(monkeypatch):
    completions = FakeCompletions()
    install_fake_groq(monkeypatch, completions)
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setattr(config, "AGENT_MODEL", "openai/gpt-oss-120b")

    result = agent.verify_model()

    assert result["ok"] is True
    assert result["model"] == "openai/gpt-oss-120b"
    assert isinstance(result["latency_ms"], float)
    call = completions.calls[0]
    assert call["extra_body"] == {"reasoning_effort": "low"}
    assert call["max_tokens"] >= 32


def test_verify_model_reports_failure_without_raising(monkeypatch):
    install_fake_groq(monkeypatch, FakeCompletions(fail=True))
    monkeypatch.setenv("GROQ_API_KEY", "test")
    assert agent.verify_model()["ok"] is False

    monkeypatch.delenv("GROQ_API_KEY")
    result = agent.verify_model()
    assert result["ok"] is False and "latency_ms" not in result


def test_replayed_turn_drops_reasoning():
    call = SimpleNamespace(id="c1", function=SimpleNamespace(name="video_search", arguments='{"query":"x"}'))
    message = SimpleNamespace(content=None, tool_calls=[call], reasoning="private thoughts")

    data = agent._replayable(message)

    assert "reasoning" not in data and "reasoning_content" not in data
    assert data["content"] == ""
    assert data["tool_calls"][0]["function"]["name"] == "video_search"


def test_reasoning_kwargs_only_for_gpt_oss(monkeypatch):
    monkeypatch.setattr(config, "AGENT_MODEL", "some-other-model")
    assert agent._reasoning_kwargs() == {}


def test_duration_parsing():
    assert tools._duration_seconds("4:32") == 272
    assert tools._duration_seconds("1:02:10") == 3730
    assert tools._duration_seconds(None) is None
    assert tools._duration_seconds("LIVE") is None


def test_video_search_skips_long_and_unknown_videos(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "test")
    monkeypatch.setattr(config, "MAX_VIDEO_SECONDS", 300)
    results = [
        {"title": "Long", "link": "https://youtube.com/watch?v=long", "length": "45:00"},
        {"title": "Live", "link": "https://youtube.com/watch?v=live"},
        {"title": "Short", "link": "https://youtube.com/watch?v=short", "length": "2:05"},
    ]
    response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"video_results": results})
    monkeypatch.setattr(tools.requests, "get", lambda *a, **k: response)

    picked = tools.video_search("recursion")

    assert picked == {"title": "Short", "url": "https://youtube.com/watch?v=short", "seconds": 125}


def test_video_search_says_so_when_nothing_is_short_enough(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "test")
    monkeypatch.setattr(config, "MAX_VIDEO_SECONDS", 300)
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"video_results": [{"title": "Long", "link": "https://youtube.com/x", "length": "1:00:00"}]},
    )
    monkeypatch.setattr(tools.requests, "get", lambda *a, **k: response)

    try:
        tools.video_search("recursion")
    except RuntimeError as error:
        assert "5 minutes" in str(error)
    else:
        raise AssertionError("expected a RuntimeError")


def test_health_route(monkeypatch):
    import app as webapp

    monkeypatch.setattr(agent, "verify_model", lambda: {"ok": True, "model": "m", "latency_ms": 12.5})
    client = webapp.app.test_client()

    plain = client.get("/api/health").get_json()
    assert plain["ok"] is True and "latency_ms" not in plain

    verified = client.get("/api/health?verify=1").get_json()
    assert verified["latency_ms"] == 12.5
    assert client.get("/health").status_code == 200
