"""
Configuration for the video search + transcription agent.

All the "settings" of the project live here so the rest of the code stays
simple. If you want to swap a model or change the wording of a prompt, this
is the only file you need to touch.
"""

import os

# The Groq model that acts as the agent's "brain". It reads the request,
# decides which tool to call, and writes the final answer. It must be a
# model that supports tool calling. See https://console.groq.com/docs/tool-use
# Groq retired llama-3.3-70b-versatile on 16 Aug 2026; override with GROQ_MODEL.
AGENT_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")

# Only videos at most this long are picked, so a transcription fits inside the
# serverless time limit.
MAX_VIDEO_SECONDS = int(os.environ.get("MAX_VIDEO_SECONDS", "300"))

# The Gemini multimodal model that actually watches the video and writes the
# transcript. It accepts a public YouTube URL directly. Override it with
# GEMINI_MODEL. If the model is retired, out of quota or busy (404, 429, 500,
# 503), the next one in TRANSCRIBE_FALLBACK_MODELS is tried.
# Flash-Lite is the default because it answers in well under a second; on
# 20 Nov 2026 gemini-3.8-flash and often gemini-3.6-flash took more than 10
# seconds even for a one-line reply, too slow for the 60 second limit.
TRANSCRIBE_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
TRANSCRIBE_FALLBACK_MODELS = [
    "gemini-3.6-flash",
    "gemini-3.8-flash",
    "gemini-flash-latest",
]

# Transcribing needs no reasoning, so the model is asked to think little.
TRANSCRIBE_THINKING_LEVEL = "low"

# Gemini API version. Google documents YouTube URL input on v1beta, and the
# "-latest" aliases are not served on v1, which the November 2026 SDKs call
# by default. So the version is pinned here instead of left to the SDK.
GEMINI_API_VERSION = os.environ.get("GEMINI_API_VERSION", "v1beta")

# How long one Gemini call may take. Past it the run stops, since there is no
# time left in the function to try another model. The transcription gets most
# of the 60 second limit; the health check needs only a short call (Gemini
# rejects deadlines under 10 seconds).
TRANSCRIBE_TIMEOUT_SECONDS = 40
VERIFY_TIMEOUT_SECONDS = 12

# The instruction we send to Gemini. We ask for a plain transcript only, so
# the agent never has to "make up" a summary of the video on its own.
TRANSCRIBE_PROMPT = (
    "Transcribe the spoken words in this video into clean, readable text. "
    "Write only the transcript of what is actually said, in order. "
    "Do not summarize, translate, or add any commentary of your own."
)

# The system prompt that tells the agent how to behave. The rules matter:
# the whole point of the assignment is that the transcript comes from the
# TranscriptionTool, not from the agent inventing one.
SYSTEM_PROMPT = (
    "You are a research assistant that has two tools:\n"
    "  1. video_search      - find a YouTube video about a topic.\n"
    "  2. transcribe_video  - get the transcript of a video URL.\n\n"
    "To handle a request you MUST:\n"
    "  - First call video_search to find one relevant video.\n"
    "  - Then call transcribe_video on that video's URL to get its "
    "transcript.\n\n"
    "Rules you must always follow:\n"
    "  - Never write the transcript yourself. The transcript may ONLY come "
    "from the transcribe_video tool.\n"
    "  - Do not summarize, shorten, or reword the transcript. Return it "
    "exactly as the tool produced it.\n"
    "  - End your final answer with a line in this exact form:\n"
    "        Source: <the video url>"
)

# Safety limit so a confused model cannot loop forever calling tools.
MAX_STEPS = 6

# Where transcripts (our little "knowledge base") are saved.
KNOWLEDGE_BASE_DIR = "knowledge_base"
