"""
The AI agent.

It uses Groq's tool-calling API as the "brain". Groq reads the request and
decides which tool to call; we run that tool locally, hand the result back,
and let Groq continue. This repeats until Groq has a final answer with no
more tool calls.

The important part: the agent does the video search and transcription by
CALLING TOOLS, not by making things up. run_agent returns both the final
answer and a record of every tool call ("steps"), so the command-line script
and the web page can both show that the tools were really used.
"""

import os
import json

import config
import tools


def run_agent(user_request, verbose=True):
    """
    Run the tool-calling loop for one user request.

    Returns a dict:
        {
          "answer": <final text: the transcript, ending with the source>,
          "steps":  [ {tool, args, ok, summary, ...}, ... ],
          "source": <the video URL that was transcribed, or None>,
        }
    """
    from groq import Groq

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not set. "
            "Copy .env.example to .env and paste in your key."
        )

    client = Groq(api_key=api_key)

    messages = [
        {"role": "system", "content": config.SYSTEM_PROMPT},
        {"role": "user", "content": user_request},
    ]

    steps = []            # a record of every tool call, for the trace / web UI
    source = None         # the URL of the video we transcribed
    last_search_url = None  # the URL the search tool actually returned

    # Loop with a hard limit so a confused model can't call tools forever.
    for _ in range(config.MAX_STEPS):
        response = _chat_with_retry(client, messages)
        message = response.choices[0].message

        # Remember what the agent said (including any tool calls) so the next
        # request keeps the full conversation.
        messages.append(_replayable(message))

        # No tool calls means the agent is done and this is the answer.
        if not message.tool_calls:
            return {"answer": message.content, "steps": steps, "source": source}

        # Otherwise run every tool the agent asked for and feed back results.
        for tool_call in message.tool_calls:
            name = tool_call.function.name
            args = json.loads(tool_call.function.arguments or "{}")

            # Guardrail: only ever transcribe the video the search tool
            # actually found. Now and then the model invents a URL for
            # transcribe_video; if it doesn't match the searched one, we
            # replace it so we never transcribe the wrong (or a made-up)
            # video.
            if (
                name == "transcribe_video"
                and last_search_url
                and args.get("url") != last_search_url
            ):
                args["url"] = last_search_url

            if verbose:
                print("  [tool] " + name + "(" + json.dumps(args) + ")")

            record = {"tool": name, "args": args, "ok": True}
            try:
                result = tools.run_tool(name, args)
                record.update(_describe(name, result))
                # Track the video URL so we can show the source easily.
                if name == "video_search":
                    last_search_url = result.get("url")
                    if source is None:
                        source = result.get("url")
                elif name == "transcribe_video":
                    source = result.get("url")
                if verbose:
                    print("    -> " + record["summary"])
            except Exception as error:
                # Report the error back to the agent instead of crashing, so
                # it can try again or explain what went wrong.
                result = {"error": str(error)}
                record["ok"] = False
                record["summary"] = "ERROR: " + str(error)
                if verbose:
                    print("    -> ERROR: " + str(error))

            steps.append(record)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": name,
                    "content": json.dumps(result),
                }
            )

    return {
        "answer": (
            "Stopped after " + str(config.MAX_STEPS) + " steps without a "
            "final answer. Check the tool steps above."
        ),
        "steps": steps,
        "source": source,
    }


def _reasoning_kwargs():
    """gpt-oss models reason before answering; low effort keeps each step quick.
    Sent as extra_body so it works on every groq SDK version."""
    if config.AGENT_MODEL.startswith("openai/gpt-oss"):
        return {"extra_body": {"reasoning_effort": "low"}}
    return {}


def _replayable(message):
    """The assistant turn as a plain dict: content and tool calls only, so the
    model's private reasoning is never sent back on the next step."""
    data = {"role": "assistant", "content": message.content or ""}
    if message.tool_calls:
        data["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments or "{}",
                },
            }
            for call in message.tool_calls
        ]
    return data


def verify_model():
    """One real, tiny call to the agent model, for the health check.

    Returns {"ok": True, "model", "latency_ms"} when the model answers, and
    {"ok": False, "model", "error"} when it does not (missing key, retired
    model, rate limit). It never raises, so the health route stays a 200.
    """
    import time

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return {"ok": False, "model": config.AGENT_MODEL, "error": "GROQ_API_KEY is not set."}

    try:
        from groq import Groq

        client = Groq(api_key=api_key)
        started = time.perf_counter()
        # Reasoning tokens count against max_tokens, so leave room for them.
        client.chat.completions.create(
            model=config.AGENT_MODEL,
            max_tokens=64,
            messages=[{"role": "user", "content": "Reply with OK."}],
            **_reasoning_kwargs(),
        )
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
    except Exception as error:  # the health check reports, it never crashes
        return {"ok": False, "model": config.AGENT_MODEL, "error": type(error).__name__}

    return {"ok": True, "model": config.AGENT_MODEL, "latency_ms": latency_ms}


def _chat_with_retry(client, messages, attempts=3):
    """
    Ask Groq for the next step, retrying a couple of times.

    Now and then the model emits a malformed tool call and Groq answers with
    a 400 "tool_use_failed" error. It is intermittent, so simply asking again
    usually fixes it.
    """
    from groq import BadRequestError

    for attempt in range(attempts):
        try:
            return client.chat.completions.create(
                model=config.AGENT_MODEL,
                messages=messages,
                tools=tools.TOOLS,
                tool_choice="auto",
                **_reasoning_kwargs(),
            )
        except BadRequestError as error:
            if "tool_use_failed" in str(error) and attempt < attempts - 1:
                print("    (retrying: the model sent a malformed tool call)")
                continue
            raise


def _describe(name, result):
    """Turn a tool result into fields (incl. a one-line summary) for the UI."""
    if name == "video_search":
        title = result.get("title", "")
        url = result.get("url", "")
        return {"title": title, "url": url, "summary": title + " -> " + url}
    if name == "transcribe_video":
        chars = len(result.get("transcript", ""))
        saved_to = result.get("saved_to", "")
        return {
            "url": result.get("url", ""),
            "chars": chars,
            "saved_to": saved_to,
            "summary": "transcript saved (" + str(chars) + " chars) -> "
            + saved_to,
        }
    return {"summary": "ok"}
