// Talks to the backend: send a topic, then show which tools the agent
// called and the transcript that came back.

const form = document.getElementById("form");
const topicInput = document.getElementById("topic");
const goButton = document.getElementById("go");

const statusBox = document.getElementById("status");
const statusText = document.getElementById("status-text");
const errorBox = document.getElementById("error");
const stepsBox = document.getElementById("steps-box");
const stepsList = document.getElementById("steps");
const resultBox = document.getElementById("result-box");
const transcriptEl = document.getElementById("transcript");
const metaEl = document.getElementById("meta");
const sourceLink = document.getElementById("source");
const copyButton = document.getElementById("copy");

// Messages shown while we wait, so the page doesn't look frozen during the
// 15-30 seconds the transcription usually takes.
const PROGRESS = [
  "Asking the agent to pick a tool…",
  "Searching YouTube for a good video…",
  "Found a video — sending it to be transcribed…",
  "Transcribing the audio, this is the slow part…",
  "Still transcribing — longer videos take a while…",
  "Almost there, tidying up the transcript…",
];
let progressTimer = null;

// Clicking an example chip fills the box and runs it straight away.
document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    topicInput.value = chip.textContent.trim();
    form.requestSubmit();
  });
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const topic = topicInput.value.trim();
  if (!topic) {
    topicInput.focus();
    return;
  }

  // Reset the page for a fresh run.
  hide(errorBox);
  hide(stepsBox);
  hide(resultBox);
  stepsList.innerHTML = "";
  setBusy(true);

  try {
    const response = await fetch("/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic }),
    });

    let data;
    try {
      data = await response.json();
    } catch (err) {
      // A serverless timeout returns a gateway page, not JSON.
      showError(
        "The server took too long to answer. Very long videos can time " +
          "out — try a shorter one."
      );
      return;
    }

    if (!response.ok) {
      showError(data.error || "Something went wrong.");
      if (data.steps && data.steps.length) renderSteps(data.steps);
      return;
    }

    renderSteps(data.steps || []);
    renderTranscript(data.answer || "", data.source || "");
  } catch (err) {
    showError("Could not reach the server. Is it still running?");
  } finally {
    setBusy(false);
  }
});

function renderSteps(steps) {
  stepsList.innerHTML = "";
  steps.forEach((step, index) => {
    const li = document.createElement("li");
    li.className = "step" + (step.ok ? "" : " bad");
    li.style.animationDelay = index * 60 + "ms";

    const dot = document.createElement("span");
    dot.className = "dot";

    const body = document.createElement("div");

    const name = document.createElement("div");
    name.className = "name";
    name.textContent = step.tool;

    const detail = document.createElement("div");
    detail.className = "detail";

    if (step.tool === "video_search" && step.ok && step.url) {
      detail.append(step.title || "");
      detail.append(" — ");
      const link = document.createElement("a");
      link.href = step.url;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = step.url;
      detail.append(link);
    } else if (step.tool === "transcribe_video" && step.ok) {
      detail.textContent = "transcript saved (" + step.chars + " characters)";
    } else {
      detail.textContent = step.summary || "";
    }

    body.append(name, detail);
    li.append(dot, body);
    stepsList.append(li);
  });
  show(stepsBox);
}

function renderTranscript(answer, source) {
  // The answer ends with a "Source: <url>" line; show the transcript on its
  // own and put the link in the Source button.
  const transcript = answer.replace(/\n?Source:.*$/i, "").trim() || answer;
  transcriptEl.textContent = transcript;

  const words = transcript.split(/\s+/).filter(Boolean).length;
  metaEl.textContent =
    words.toLocaleString() + " words · " +
    transcript.length.toLocaleString() + " characters";

  if (source) {
    sourceLink.href = source;
    show(sourceLink);
  } else {
    hide(sourceLink);
  }
  show(resultBox);
  resultBox.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

copyButton.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(transcriptEl.textContent);
    copyButton.textContent = "Copied ✓";
  } catch (err) {
    copyButton.textContent = "Copy failed";
  }
  setTimeout(() => (copyButton.textContent = "Copy"), 1600);
});

function setBusy(busy) {
  goButton.disabled = busy;
  goButton.querySelector(".go-label").textContent = busy
    ? "Working…"
    : "Find & Transcribe";

  clearInterval(progressTimer);
  if (busy) {
    let i = 0;
    statusText.textContent = PROGRESS[0];
    show(statusBox);
    progressTimer = setInterval(() => {
      i = Math.min(i + 1, PROGRESS.length - 1);
      statusText.textContent = PROGRESS[i];
    }, 6000);
  } else {
    hide(statusBox);
  }
}

function showError(message) {
  errorBox.textContent = message;
  show(errorBox);
}

function show(el) { el.hidden = false; }
function hide(el) { el.hidden = true; }
