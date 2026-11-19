"""
Web frontend for the video search + transcription agent.

A tiny Flask server with one page. You type a topic, it runs the same agent
the command line uses (search a video, then transcribe it), and shows the
tool steps and the transcript in the browser.

Run it from the project root:

    python app.py

then open http://127.0.0.1:5000 in your browser.
"""

import os
import sys

# The agent code lives in the src/ folder, so add it to the import path.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify

import agent
import config

# Load the API keys from .env before the agent needs them.
load_dotenv()

app = Flask(__name__)


@app.route("/")
def index():
    """Serve the single page."""
    return render_template("index.html")


@app.route("/health")
@app.route("/api/health")
def health():
    """Liveness by default; ?verify=1 also makes one real call to the agent model.

    A plain 200 only says the server is up. The portfolio treats the demo as
    live only when verify returns ok with latency_ms.
    """
    body = {
        "ok": True,
        "model": config.AGENT_MODEL,
        "max_video_seconds": config.MAX_VIDEO_SECONDS,
    }
    if request.args.get("verify") == "1":
        body = {**body, **agent.verify_model()}
    return jsonify(body)


@app.route("/run", methods=["POST"])
def run():
    """Run the agent for the topic sent from the page and return JSON."""
    data = request.get_json(silent=True) or {}
    topic = (data.get("topic") or "").strip()
    if not topic:
        return jsonify({"error": "Please enter a topic."}), 400

    user_request = (
        "Find one good YouTube video about '" + topic + "' and transcribe it."
    )
    try:
        result = agent.run_agent(user_request, verbose=False)
    except Exception as error:
        # Send the reason back so the page can show it.
        return jsonify({"error": str(error)}), 500

    return jsonify(result)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
