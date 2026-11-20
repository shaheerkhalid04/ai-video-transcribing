# AI Video Transcriber

An AI agent that takes a topic, **finds a YouTube video about it, and
transcribes that video** — by calling two tools on its own. The agent never
writes the transcript itself; it only decides which tool to run and when. The
transcript always comes from the transcription tool, and every result ends
with the source video URL.

It comes with both a **command-line script** and a **web app**.

**Live demo: <https://ai-video-transcribing.vercel.app>**

![tools: SerpApi search, Gemini transcription, Groq agent](https://img.shields.io/badge/tools-SerpApi%20%C2%B7%20Gemini%20%C2%B7%20Groq-7c5cff)

## How it works

```
you: "find a video about recursion in 100 seconds"
        |
        v
   [ AI Agent ]   -> Groq model, decides which tool to call (tool calling)
     |       |
     |       └── Tool 2: transcribe_video  -> Gemini transcribes the video,
     |                                         transcript saved to knowledge_base/
     └────────── Tool 1: video_search      -> SerpApi finds a YouTube URL
```

1. **VideoSearchTool** (`video_search`) — uses **SerpApi** to search YouTube
   and return the top video's URL.
2. **TranscriptionTool** (`transcribe_video`) — uses the **Gemini API**'s
   multimodal model to transcribe that video, and saves the transcript to the
   `knowledge_base/` folder.
3. The agent returns the transcript and ends with `Source: <video url>`.

The agent's brain is a **Groq** model doing real tool calling: it reads the
request, calls `video_search`, then calls `transcribe_video` with the URL it
found, and finally hands back the transcript. A small guardrail makes sure it
only ever transcribes the video it actually searched for.

## Tech stack

| Part            | Used for                              |
| --------------- | ------------------------------------- |
| **SerpApi**     | YouTube video search (Tool 1)         |
| **Gemini API**  | Video transcription (Tool 2)          |
| **Groq API**    | The agent's tool-calling "brain"      |
| **Flask**       | The web frontend                      |
| **Python**      | Everything else                       |

## Project layout

```
ai-video-transcribing/
├── app.py                     # web frontend (Flask), also the Vercel entry point
├── vercel.json                # hosting config
├── templates/
│   └── index.html             # the page
├── static/
│   ├── style.css
│   └── app.js
├── src/
│   ├── config.py              # models, prompts, and settings
│   ├── tools.py               # the two tools + their Groq tool schema
│   ├── agent.py               # the tool-calling loop
│   └── run_agent.py           # command-line script
├── knowledge_base/            # saved transcripts (one file per video)
├── requirements.txt
├── .env.example
└── README.md
```

## Setup

1. Create a virtual environment and activate it:

   ```
   python -m venv venv
   venv\Scripts\activate         # macOS/Linux: source venv/bin/activate
   ```

2. Install the libraries:

   ```
   pip install -r requirements.txt
   ```

3. Add your API keys:

   ```
   copy .env.example .env        # macOS/Linux: cp .env.example .env
   ```

   Then open `.env` and paste in your three keys (all have a free tier):

   - Groq — <https://console.groq.com/keys>
   - Gemini — <https://aistudio.google.com/apikey>
   - SerpApi — <https://serpapi.com/manage-api-key>

## Run the web app

```
python app.py
```

Then open <http://127.0.0.1:5000> in your browser, type a topic, and press
**Find & Transcribe**. The page shows which tools ran and the finished
transcript, with a link back to the source video.

## Run from the command line

```
python src/run_agent.py "recursion in 100 seconds"
```

Or run it with no topic and it will ask you for one. Example output:

```
Agent is working on: recursion in 100 seconds
(tool calls are shown below)

  [tool] video_search({"query": "recursion in 100 seconds"})
    -> Recursion in 100 Seconds -> https://www.youtube.com/watch?v=rf60MejMz3E
  [tool] transcribe_video({"url": "https://www.youtube.com/watch?v=rf60MejMz3E"})
    -> transcript saved (1900 chars) -> knowledge_base/20260722_144600_rf60MejMz3E.txt

============================================================
FINAL ANSWER (transcript + source)
============================================================
A recursive function is a function that calls itself inside of its own
definition. It's like having a dream inside of a dream...
Source: https://www.youtube.com/watch?v=rf60MejMz3E
```

Each transcript is also saved in `knowledge_base/` with its source URL inside
the file, so it is always traceable back to the video.

## Deploying

The app is hosted on Vercel at
<https://ai-video-transcribing.vercel.app>. To deploy your own copy:

1. Install the CLI and log in:

   ```
   npm i -g vercel
   vercel login
   ```

2. From the project folder, link and deploy:

   ```
   vercel link
   vercel deploy --prod
   ```

3. Add the same three keys as environment variables, so the hosted app can
   reach the APIs:

   ```
   vercel env add GROQ_API_KEY production
   vercel env add GEMINI_API_KEY production
   vercel env add SERPAPI_API_KEY production
   ```

The project uses Vercel's Flask preset, which serves the `app` in `app.py` and
sends every request to it; `vercel.json` only sets its 60 second limit and the
folders to bundle. Because hosted filesystems are read-only, transcripts are
written to a temporary folder there instead of `knowledge_base/`; running
locally still saves them to `knowledge_base/` as normal.

> **Note on hosting limits:** a Vercel function can run for up to 60 seconds
> on the free plan. That is why the search tool only picks a video of
> `MAX_VIDEO_SECONDS` or less (300, so 5 minutes, by default) and skips any
> result whose length SerpApi does not report. Running locally has no time
> limit, so raise it there if you like.

### Optional settings

| Variable            | Default               | What it does                                   |
| ------------------- | --------------------- | ---------------------------------------------- |
| `GROQ_MODEL`        | `openai/gpt-oss-120b` | The agent's tool-calling model                 |
| `GEMINI_MODEL`      | `gemini-3.5-flash-lite` | The transcription model                      |
| `GEMINI_API_VERSION`| `v1beta`              | Gemini API version                             |
| `MAX_VIDEO_SECONDS` | `300`                 | Longest video the search tool will pick        |

Groq retired `llama-3.3-70b-versatile` on 16 Aug 2026, so the default is now
`openai/gpt-oss-120b`. It reasons before answering, so the agent asks for low
reasoning effort and never sends that reasoning back on the next step.

If Gemini says the transcription model is retired, out of quota or busy
(404, 429, 500 or 503), the fallbacks in `src/config.py` are tried in order:
`gemini-3.6-flash`, `gemini-3.8-flash`, then the `gemini-flash-latest`
alias. Any other error stops at once, and so does a call that runs past its
deadline, since the function has no time left to try another model. Each call
is made once (the SDK's own retries with growing pauses could use up the whole
60 seconds) and asks the model to think little, since transcribing needs no
reasoning.

Flash-Lite is the default because it answers in well under a second. On
20 Nov 2026 `gemini-3.8-flash`, and often `gemini-3.6-flash`, took more
than 10 seconds even for a one-line reply. The API version is pinned because
the November 2026 Gemini SDKs call `v1` by default, which does not serve the
`-latest` aliases, and YouTube URL input is documented on `v1beta`.

If the transcription fails, the run ends there with the error instead of
searching for more videos, and `/run` answers 502 with the error and the
steps so far.

### Health check

- `GET /api/health` says the server is up and which models it is set to use.
- `GET /api/health?verify=1` also makes one tiny real call to the Groq model
  and one to the Gemini model. It returns `{"ok": true, "model": ...,
  "latency_ms": ..., "transcribe": {"ok": true, "model": ..., "latency_ms":
  ...}}`. `ok` is false if either model cannot be reached, with the reason
  in `error` (Groq) or `transcribe.error` (Gemini). If Gemini had to fall
  back, `transcribe.skipped` lists each model passed over and why.

## Tests

```
python -m pytest -q
```

The tests replace Groq and SerpApi with fakes, so they need no keys.

## Notes

- Only **public** YouTube videos can be transcribed (Gemini can't open
  private or unlisted ones).
- Shorter videos transcribe faster and are easier on the free tiers.
- Gemini has a **RECITATION** filter: it refuses to output a full verbatim
  transcript of some very popular videos whose captions it already knows. If
  that happens the tool says so clearly — just pick a shorter or less
  well-known video.
- The Gemini model falls back to the next one in the list when a specific
  model version is retired (see Optional settings).
