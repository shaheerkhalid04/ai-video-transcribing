"""
Entry point for the video search + transcription agent.

Run it from the project root, giving the topic you want a video about:

    python src/run_agent.py "how neural networks work"

If you don't pass a topic on the command line, it will ask you for one.

What happens:
  1. The agent searches YouTube for a video (VideoSearchTool / SerpApi).
  2. It transcribes that video (TranscriptionTool / Gemini).
  3. The transcript is saved in the knowledge_base/ folder.
  4. The final answer prints the transcript and the source video URL.
"""

import sys

from dotenv import load_dotenv

import agent

# Read the API keys from the .env file in the project root so you don't have
# to set environment variables by hand.
load_dotenv()


def main():
    """Read the topic, run the agent, and print the result."""
    if len(sys.argv) > 1:
        topic = " ".join(sys.argv[1:]).strip()
    else:
        topic = input(
            "What topic should I find and transcribe a video about? "
        ).strip()

    if not topic:
        print("No topic given. Nothing to do.")
        return

    # Phrase it as a request so the agent knows to use both tools in order.
    user_request = (
        "Find one good YouTube video about '" + topic + "' and transcribe it."
    )

    print("\nAgent is working on: " + topic)
    print("(tool calls are shown below)\n")

    result = agent.run_agent(user_request)

    if result.get("error"):
        print("\n" + result["error"])
        sys.exit(1)

    print("\n" + "=" * 60)
    print("FINAL ANSWER (transcript + source)")
    print("=" * 60)
    print(result["answer"])


if __name__ == "__main__":
    main()
