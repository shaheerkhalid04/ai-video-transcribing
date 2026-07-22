// Talks to the Flask backend: send a topic, show the tool steps and the
// transcript that comes back.

const form = document.getElementById("form");
const topicInput = document.getElementById("topic");
const goButton = document.getElementById("go");

const statusBox = document.getElementById("status");
const errorBox = document.getElementById("error");
const stepsBox = document.getElementById("steps-box");
const stepsList = document.getElementById("steps");
const resultBox = document.getElementById("result-box");
const transcriptEl = document.getElementById("transcript");
const sourceLink = document.getElementById("source");
const copyButton = document.getElementById("copy");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const topic = topicInput.value.trim();
  if (!topic) return;

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
    const data = await response.json();

    if (!response.ok) {
      showError(data.error || "Something went wrong.");
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
  steps.forEach((step) => {
    const li = document.createElement("li");
    li.className = "step" + (step.ok ? "" : " bad");

    const dot = document.createElement("span");
    dot.className = "dot";

    const body = document.createElement("div");
    const name = document.createElement("div");
    name.className = "name";
    name.textContent = step.tool;

    const detail = document.createElement("div");
    detail.className = "detail";
    if (step.tool === "video_search" && step.url) {
      detail.innerHTML =
        escapeHtml(step.title || "") +
        ' — <a href="' + step.url + '" target="_blank" rel="noopener">' +
        escapeHtml(step.url) + "</a>";
    } else if (step.tool === "transcribe_video" && step.ok) {
      detail.textContent =
        "transcript saved (" + step.chars + " chars)";
    } else {
      detail.textContent = step.summary || "";
    }

    body.appendChild(name);
    body.appendChild(detail);
    li.appendChild(dot);
    li.appendChild(body);
    stepsList.appendChild(li);
  });
  show(stepsBox);
}

function renderTranscript(answer, source) {
  // The answer ends with a "Source: <url>" line; show the transcript on its
  // own and put the source in the button.
  const transcript = answer.replace(/\n?Source:.*$/i, "").trim();
  transcriptEl.textContent = transcript || answer;

  if (source) {
    sourceLink.href = source;
    sourceLink.textContent = "Source ↗";
    show(sourceLink);
  } else {
    hide(sourceLink);
  }
  show(resultBox);
}

copyButton.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(transcriptEl.textContent);
    copyButton.textContent = "Copied";
    setTimeout(() => (copyButton.textContent = "Copy"), 1500);
  } catch (err) {
    copyButton.textContent = "Copy failed";
  }
});

function setBusy(busy) {
  goButton.disabled = busy;
  goButton.textContent = busy ? "Working…" : "Find & Transcribe";
  if (busy) {
    statusBox.innerHTML =
      '<span class="spinner"></span> Searching for a video and transcribing it…';
    show(statusBox);
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

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}
