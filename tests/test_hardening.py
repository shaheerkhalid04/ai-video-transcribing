"""Checks for the model swaps, the health route, the video length cap and
the run ending on a failed transcription.

Groq, Gemini and SerpApi are never called: the network pieces are replaced with fakes.
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
    monkeypatch.setattr(tools, "verify_transcribe_model", lambda: {"ok": True, "model": "g", "latency_ms": 30.0})
    client = webapp.app.test_client()

    plain = client.get("/api/health").get_json()
    assert plain["ok"] is True and "latency_ms" not in plain
    assert plain["transcribe_model"] == config.TRANSCRIBE_MODEL

    verified = client.get("/api/health?verify=1").get_json()
    assert verified["ok"] is True
    assert verified["latency_ms"] == 12.5
    assert verified["transcribe"] == {"ok": True, "model": "g", "latency_ms": 30.0}
    assert verified["transcribe_model"] == "g"
    assert client.get("/health").status_code == 200


def test_health_verify_fails_when_gemini_is_gone(monkeypatch):
    import app as webapp

    monkeypatch.setattr(agent, "verify_model", lambda: {"ok": True, "model": "m", "latency_ms": 12.5})
    monkeypatch.setattr(
        tools, "verify_transcribe_model", lambda: {"ok": False, "model": "g", "error": "not found"}
    )

    verified = webapp.app.test_client().get("/api/health?verify=1").get_json()

    assert verified["ok"] is False
    assert verified["transcribe"]["error"] == "not found"


# ---------------------------------------------------------------------------
# Gemini: model choice, fallback on 404, and the health check.
# ---------------------------------------------------------------------------


class FakeAPIError(Exception):
    def __init__(self, code, status="", message=""):
        super().__init__(message)
        self.code = code
        self.status = status
        self.message = message


class FakeModels:
    """generate_content answers per model: an exception to raise, or text."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def generate_content(self, model, contents, config=None):
        self.calls.append(model)
        answer = self.answers.get(model, FakeAPIError(404, "NOT_FOUND", "models/" + model + " is not found"))
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(text=answer, candidates=[])


def install_fake_genai(monkeypatch, models):
    """Stand in for google.genai so no request leaves the machine."""
    created = []

    class Client:
        def __init__(self, api_key=None, http_options=None):
            created.append(http_options)
            self.models = models

    def record(**kwargs):
        return SimpleNamespace(**kwargs)

    genai = types.ModuleType("google.genai")
    genai.Client = Client
    genai.types = SimpleNamespace(
        HttpOptions=record, Content=record, Part=record, FileData=record, GenerateContentConfig=record
    )
    genai.errors = SimpleNamespace(APIError=FakeAPIError)
    google = types.ModuleType("google")
    google.genai = genai
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", genai.types)
    monkeypatch.setitem(sys.modules, "google.genai.errors", genai.errors)
    monkeypatch.setattr(tools, "_working_model", None)
    monkeypatch.setattr(tools, "save_transcript", lambda url, text: "(test)")
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    return created


def test_default_gemini_model_is_current():
    assert config.TRANSCRIBE_MODEL != "gemini-flash-latest" or "GEMINI_MODEL" in os.environ
    assert config.GEMINI_API_VERSION == "v1beta" or "GEMINI_API_VERSION" in os.environ


def test_transcription_falls_back_when_a_model_is_retired(monkeypatch):
    monkeypatch.setattr(config, "TRANSCRIBE_MODEL", "retired-model")
    monkeypatch.setattr(config, "TRANSCRIBE_FALLBACK_MODELS", ["also-retired", "current-model"])
    models = FakeModels({"current-model": "hello world"})
    created = install_fake_genai(monkeypatch, models)

    result = tools.transcribe_video("https://www.youtube.com/watch?v=abcdefghijk")

    assert result["transcript"] == "hello world"
    assert models.calls == ["retired-model", "also-retired", "current-model"]
    assert created[0].api_version == config.GEMINI_API_VERSION

    # The model that worked is tried first next time.
    tools.transcribe_video("https://www.youtube.com/watch?v=abcdefghijk")
    assert models.calls[-1] == "current-model" and len(models.calls) == 4


def test_transcription_stops_on_errors_other_than_not_found(monkeypatch):
    monkeypatch.setattr(config, "TRANSCRIBE_MODEL", "m1")
    monkeypatch.setattr(config, "TRANSCRIBE_FALLBACK_MODELS", ["m2"])
    models = FakeModels({"m1": FakeAPIError(400, "INVALID_ARGUMENT", "bad video")})
    install_fake_genai(monkeypatch, models)

    try:
        tools.transcribe_video("https://www.youtube.com/watch?v=abcdefghijk")
    except RuntimeError as error:
        assert "400" in str(error) and "bad video" in str(error)
    else:
        raise AssertionError("expected a RuntimeError")
    assert models.calls == ["m1"]


def test_transcription_names_every_missing_model(monkeypatch):
    monkeypatch.setattr(config, "TRANSCRIBE_MODEL", "m1")
    monkeypatch.setattr(config, "TRANSCRIBE_FALLBACK_MODELS", ["m2"])
    install_fake_genai(monkeypatch, FakeModels({}))

    try:
        tools.transcribe_video("https://www.youtube.com/watch?v=abcdefghijk")
    except RuntimeError as error:
        assert "m1, m2" in str(error) and "GEMINI_MODEL" in str(error)
    else:
        raise AssertionError("expected a RuntimeError")


def test_verify_transcribe_model(monkeypatch):
    monkeypatch.setattr(config, "TRANSCRIBE_MODEL", "retired-model")
    monkeypatch.setattr(config, "TRANSCRIBE_FALLBACK_MODELS", ["current-model"])
    install_fake_genai(monkeypatch, FakeModels({"current-model": "OK"}))

    result = tools.verify_transcribe_model()
    assert result["ok"] is True and result["model"] == "current-model"
    assert isinstance(result["latency_ms"], float)

    install_fake_genai(monkeypatch, FakeModels({}))
    failed = tools.verify_transcribe_model()
    assert failed["ok"] is False and "not found" in failed["error"]

    monkeypatch.delenv("GEMINI_API_KEY")
    assert tools.verify_transcribe_model()["ok"] is False


# ---------------------------------------------------------------------------
# A failed transcription ends the run instead of searching again.
# ---------------------------------------------------------------------------


def tool_call(call_id, name, arguments):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=arguments))


class ScriptedCompletions:
    """Answers with search, then transcribe, then (if still asked) search again."""

    def __init__(self):
        self.calls = 0
        self.script = [
            [tool_call("c1", "video_search", '{"query": "recursion"}')],
            [tool_call("c2", "transcribe_video", '{"url": "https://www.youtube.com/watch?v=abcdefghijk"}')],
        ]

    def create(self, **kwargs):
        calls = self.script[self.calls] if self.calls < len(self.script) else self.script[0]
        self.calls += 1
        message = SimpleNamespace(content=None, tool_calls=calls)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_failed_transcription_ends_the_run(monkeypatch):
    completions = ScriptedCompletions()
    install_fake_groq(monkeypatch, completions)
    monkeypatch.setenv("GROQ_API_KEY", "test")

    def fake_tool(name, args):
        if name == "video_search":
            return {"title": "Recursion", "url": "https://www.youtube.com/watch?v=abcdefghijk", "seconds": 100}
        raise RuntimeError("No Gemini model answered on API v1beta")

    monkeypatch.setattr(tools, "run_tool", fake_tool)

    result = agent.run_agent("Find a video about recursion and transcribe it.", verbose=False)

    assert completions.calls == 2
    assert [s["tool"] for s in result["steps"]] == ["video_search", "transcribe_video"]
    assert result["steps"][1]["ok"] is False
    assert "Could not transcribe the video" in result["error"]
    assert "No Gemini model answered" in result["error"]
    assert result["answer"] == result["error"]


def test_run_route_answers_502_when_transcription_fails(monkeypatch):
    import app as webapp

    failed = {"answer": "Could not transcribe the video. x", "error": "Could not transcribe the video. x",
              "steps": [{"tool": "transcribe_video", "ok": False, "summary": "ERROR: x"}], "source": None}
    monkeypatch.setattr(agent, "run_agent", lambda *a, **k: failed)

    response = webapp.app.test_client().post("/run", json={"topic": "recursion"})

    assert response.status_code == 502
    body = response.get_json()
    assert body["error"].startswith("Could not transcribe") and body["steps"][0]["ok"] is False
