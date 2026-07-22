# AI Video Transcriber

An AI agent that takes a topic, **finds a YouTube video about it, and
transcribes that video** — by calling two tools on its own. The agent never
writes the transcript itself; it only decides which tool to run and when. The
transcript always comes from the transcription tool, and every result ends
with the source video URL.

It comes with both a **command-line script** and a small **web page**.

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
├── app.py                     # web frontend (Flask)
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

## Notes

- Only **public** YouTube videos can be transcribed (Gemini can't open
  private or unlisted ones).
- Shorter videos transcribe faster and are easier on the free tiers.
- Gemini has a **RECITATION** filter: it refuses to output a full verbatim
  transcript of some very popular videos whose captions it already knows. If
  that happens the tool says so clearly — just pick a shorter or less
  well-known video.
- `gemini-flash-latest` is used so the code keeps working when a specific
  model version is retired.
