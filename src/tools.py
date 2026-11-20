"""
The two tools our AI agent can call.

Tool 1: video_search(query)     -> finds a YouTube video with SerpApi and
                                   returns its title and URL.
Tool 2: transcribe_video(url)   -> transcribes that video with the Gemini
                                   API and saves the transcript to the
                                   knowledge_base folder.

Each tool is a plain Python function. Below the functions we also describe
the tools in the JSON format that Groq's tool-calling API expects, plus a
small dispatch helper (run_tool) so the agent can call a tool by name.
"""

import os
import re
import json
import datetime
import tempfile

import requests

import config


def video_search(query):
    """
    Search YouTube through SerpApi and return the first result that is no
    longer than config.MAX_VIDEO_SECONDS, so transcription fits the time limit.

    Returns a dict: {"title": ..., "url": ..., "seconds": ...}.
    Raises a RuntimeError with a readable message on failure.
    """
    api_key = os.environ.get("SERPAPI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "SERPAPI_API_KEY is not set. "
            "Copy .env.example to .env and paste in your key."
        )

    # SerpApi's "youtube" engine returns YouTube search results as JSON.
    params = {
        "engine": "youtube",
        "search_query": query,
        "api_key": api_key,
    }
    response = requests.get(
        "https://serpapi.com/search.json", params=params, timeout=60
    )
    response.raise_for_status()
    data = response.json()

    results = data.get("video_results", [])
    if not results:
        raise RuntimeError("SerpApi found no videos for: " + query)

    # Only take a video short enough to transcribe inside the time limit.
    for result in results:
        url = result.get("link")
        seconds = _duration_seconds(result.get("length"))
        if url and seconds is not None and seconds <= config.MAX_VIDEO_SECONDS:
            return {"title": result.get("title", "(no title)"), "url": url, "seconds": seconds}

    raise RuntimeError(
        "No video of " + str(config.MAX_VIDEO_SECONDS // 60) + " minutes or less "
        "came up for: " + query + ". Try a more specific topic."
    )


def _duration_seconds(length):
    """'4:32' or '1:02:10' (SerpApi's YouTube length) to seconds; None if unknown."""
    if not length or not isinstance(length, str):
        return None
    parts = length.strip().split(":")
    if not parts or not all(part.isdigit() for part in parts):
        return None
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return seconds


def transcribe_video(url):
    """
    Transcribe a public YouTube video with Gemini and save the transcript.

    Returns a dict with the url, the transcript text, and the file it was
    saved to. Raises a RuntimeError with a readable message on failure.
    """
    # Imported here so the script still starts even if the library is only
    # needed for this one tool.
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. "
            "Copy .env.example to .env and paste in your key."
        )

    client = _gemini_client(api_key, config.TRANSCRIBE_TIMEOUT_SECONDS)

    # We hand Gemini the YouTube URL directly (as a "file" part) plus our
    # transcription instruction, and let its multimodal model do the work.
    # A big output limit leaves room for a long transcript.
    response, _, _ = _generate_with_fallback(
        client,
        contents=types.Content(
            parts=[
                types.Part(file_data=types.FileData(file_uri=url)),
                types.Part(text=config.TRANSCRIBE_PROMPT),
            ]
        ),
        settings=types.GenerateContentConfig(
            max_output_tokens=32000,
            thinking_config=types.ThinkingConfig(thinking_level=config.TRANSCRIBE_THINKING_LEVEL),
        ),
    )

    transcript = (response.text or "").strip()
    if not transcript:
        # Explain WHY it was empty instead of a vague "try again". The most
        # common reason is Gemini's RECITATION filter, which blocks verbatim
        # transcripts of videos it recognizes (popular videos with indexed
        # captions). Less-indexed / shorter videos usually go through.
        reason = _finish_reason(response)
        if reason == "RECITATION":
            raise RuntimeError(
                "Gemini blocked this transcript (RECITATION): it will not "
                "reproduce the full text of a video it recognizes. Try a "
                "different or less well-known video."
            )
        raise RuntimeError(
            "Gemini returned no transcript (finish reason: " + reason + ")."
        )

    saved_to = save_transcript(url, transcript)
    return {"url": url, "transcript": transcript, "saved_to": saved_to}


def _gemini_client(api_key, timeout_seconds):
    """
    A Gemini client on the pinned API version (config.GEMINI_API_VERSION).

    The SDK retries a busy or rate-limited model up to five times with
    growing pauses, which can eat the whole 60 second function limit. Here
    each call is tried once, with a timeout, and _generate_with_fallback moves
    on to the next model instead.
    """
    from google import genai
    from google.genai import types

    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            api_version=config.GEMINI_API_VERSION,
            timeout=int(timeout_seconds * 1000),
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )


# The model that last answered, so later calls in the same process skip
# models already found to be retired.
_working_model = None

# Answers that mean "this model, not this request": retired (404), out of
# quota (429), or busy (500, 503). The next model is tried for these. A 504
# (deadline exceeded) is treated like a timeout: no time is left to retry.
_SKIP_CODES = {404, 429, 500, 503}


def _transcribe_models():
    """The model that last worked, then the configured one, then the fallbacks."""
    models = [_working_model, config.TRANSCRIBE_MODEL] + list(
        config.TRANSCRIBE_FALLBACK_MODELS
    )
    return [m for m in dict.fromkeys(models) if m]


def _generate_with_fallback(client, contents, settings=None):
    """
    Call Gemini's generate_content, moving to the next model when one is
    retired, out of quota or busy. Any other error (a bad or private video,
    a bad key, a timeout) stops at once.

    Returns (response, the model that answered, [skipped models and why]).
    """
    global _working_model
    from google.genai import errors

    skipped = []
    for model in _transcribe_models():
        try:
            response = client.models.generate_content(
                model=model, contents=contents, config=settings
            )
        except errors.APIError as error:
            if error.code == 504:
                raise RuntimeError(
                    "Gemini (" + model + ") did not answer in time. Try a shorter video."
                ) from error
            if error.code in _SKIP_CODES:
                skipped.append({"model": model, "reason": str(error.code) + " " + str(error.status or "")})
                continue
            raise RuntimeError(
                "Gemini (" + model + ") answered " + str(error.code) + " "
                + str(error.status or "") + ": " + str(error.message or error)
            ) from error
        except Exception as error:
            # Too slow: there is no time left in the function to try another.
            if "Timeout" in type(error).__name__:
                raise RuntimeError(
                    "Gemini (" + model + ") did not answer in time. Try a shorter video."
                ) from error
            raise
        _working_model = model
        return response, model, skipped

    raise RuntimeError(
        "No Gemini model answered on API " + config.GEMINI_API_VERSION + " ("
        + ", ".join(s["model"] + ": " + s["reason"].strip() for s in skipped)
        + "). Set GEMINI_MODEL to a current model."
    )


def verify_transcribe_model():
    """One real, tiny call to the Gemini model, for the health check.

    Returns {"ok": True, "model", "latency_ms"} when a model answers, and
    {"ok": False, "model", "error"} when none does (missing key, every model
    retired). It never raises, so the health route stays a 200.
    """
    import time

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {"ok": False, "model": config.TRANSCRIBE_MODEL, "error": "GEMINI_API_KEY is not set."}

    try:
        from google.genai import types

        client = _gemini_client(api_key, config.VERIFY_TIMEOUT_SECONDS)
        started = time.perf_counter()
        _, model, skipped = _generate_with_fallback(
            client,
            contents="Reply with OK.",
            settings=types.GenerateContentConfig(
                max_output_tokens=16,
                thinking_config=types.ThinkingConfig(thinking_level=config.TRANSCRIBE_THINKING_LEVEL),
            ),
        )
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
    except Exception as error:  # the health check reports, it never crashes
        return {"ok": False, "model": config.TRANSCRIBE_MODEL, "error": str(error)[:300]}

    result = {"ok": True, "model": model, "latency_ms": latency_ms}
    if skipped:
        result["skipped"] = skipped
    return result


def _finish_reason(response):
    """Return the model's finish reason as a plain string (best effort)."""
    try:
        return str(response.candidates[0].finish_reason.name)
    except Exception:
        return "UNKNOWN"


def save_transcript(url, transcript):
    """
    Save one transcript to knowledge_base/<time>_<video-id>.txt.

    When the app runs on a hosting platform the project folder is usually
    read-only, so we fall back to the system temp folder instead of
    crashing. Saving is a nice-to-have; the transcript is returned either
    way.
    """
    # Build a tidy filename from the current time and the YouTube video id.
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    name = stamp + "_" + _video_id(url) + ".txt"

    body = (
        "Source: " + url + "\n"
        + "Transcribed: " + stamp + "\n"
        + "-" * 40 + "\n\n"
        + transcript + "\n"
    )

    # Try the project folder first, then a writable temp folder.
    for folder in (config.KNOWLEDGE_BASE_DIR, tempfile.gettempdir()):
        try:
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, name)
            with open(path, "w", encoding="utf-8") as f:
                # Keep the source URL inside the file too, so a saved
                # transcript is always traceable back to its video.
                f.write(body)
            return path
        except OSError:
            continue

    return "(not saved: no writable folder)"


def _video_id(url):
    """Pull the YouTube video id out of a URL (best effort, for filenames)."""
    match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", url)
    return match.group(1) if match else "video"


# ---------------------------------------------------------------------------
# Tool descriptions and dispatch for the Groq agent.
# ---------------------------------------------------------------------------

# This is the JSON schema Groq needs so the model knows the tools exist and
# what arguments each one takes. The "name" here must match the Python
# function names in TOOL_FUNCTIONS below.
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "video_search",
            "description": (
                "Search YouTube for a video about a topic and return the "
                "top result's title and URL."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for on YouTube.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "transcribe_video",
            "description": (
                "Transcribe a public YouTube video from its URL and save the "
                "transcript. Returns the full transcript text."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The YouTube video URL to transcribe.",
                    }
                },
                "required": ["url"],
            },
        },
    },
]

# Lookup table so the agent can run a tool by the name the model gave us.
TOOL_FUNCTIONS = {
    "video_search": video_search,
    "transcribe_video": transcribe_video,
}


def run_tool(name, args):
    """Run the tool called `name` with the dict of `args` from the model."""
    if name not in TOOL_FUNCTIONS:
        raise RuntimeError("Unknown tool: " + name)
    return TOOL_FUNCTIONS[name](**args)
