// popup.js — Knowledge Collector Extension Popup Logic

const BACKEND_URL = "http://localhost:8000";

const topicInput = document.getElementById("topic-input");
const setTopicBtn = document.getElementById("set-topic-btn");
const activeTopicDisplay = document.getElementById("active-topic-display");
const activeTopicName = document.getElementById("active-topic-name");
const clearTopicBtn = document.getElementById("clear-topic-btn");
const lastResult = document.getElementById("last-result");
const resultMessage = document.getElementById("result-message");
const resultTime = document.getElementById("result-time");
const topicsList = document.getElementById("topics-list");
const refreshBtn = document.getElementById("refresh-btn");
const statusDot = document.getElementById("status-dot");

// ── Init ───────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  await loadActiveTopic();
  await loadLastResult();
  await loadTopics();
  checkBackendStatus();
});

// ── Set Topic ──────────────────────────────────────────────────────────────
setTopicBtn.addEventListener("click", setTopic);
topicInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") setTopic();
});

async function setTopic() {
  const name = topicInput.value.trim();
  if (!name) return;

  chrome.storage.local.set({ activeTopic: name }, () => {
    topicInput.value = "";
    showActiveTopic(name);
    // Notify background to retry pending action if any
    chrome.runtime.sendMessage({ type: "TOPIC_SET", topic: name });
    // Refresh topics list
    loadTopics();
  });
}

// ── Clear Topic ────────────────────────────────────────────────────────────
clearTopicBtn.addEventListener("click", () => {
  chrome.storage.local.remove("activeTopic", () => {
    activeTopicDisplay.classList.add("hidden");
  });
});

// ── Load active topic from storage ─────────────────────────────────────────
async function loadActiveTopic() {
  return new Promise((resolve) => {
    chrome.storage.local.get(["activeTopic"], (result) => {
      if (result.activeTopic) showActiveTopic(result.activeTopic);
      resolve();
    });
  });
}

function showActiveTopic(name) {
  activeTopicName.textContent = name;
  activeTopicDisplay.classList.remove("hidden");
}

// ── Load last result ───────────────────────────────────────────────────────
async function loadLastResult() {
  return new Promise((resolve) => {
    chrome.storage.local.get(["lastResult"], (result) => {
      if (result.lastResult) {
        const { status, message, timestamp } = result.lastResult;
        resultMessage.textContent = message;
        resultMessage.className = `result-message ${status}`;
        resultTime.textContent = formatTime(timestamp);
        lastResult.classList.remove("hidden");
      }
      resolve();
    });
  });
}

// ── Load topics from backend ───────────────────────────────────────────────
refreshBtn.addEventListener("click", loadTopics);

async function loadTopics() {
  topicsList.innerHTML = '<div class="loading-text">Loading…</div>';
  try {
    const res = await fetch(`${BACKEND_URL}/topics`, { signal: AbortSignal.timeout(3000) });
    if (!res.ok) throw new Error("Backend unreachable");
    const data = await res.json();

    const activeTopic = await getActiveTopic();

    if (!data.topics || data.topics.length === 0) {
      topicsList.innerHTML = '<div class="loading-text">No topics yet</div>';
      return;
    }

    topicsList.innerHTML = "";
    for (const t of data.topics) {
      const item = document.createElement("div");
      item.className = `topic-item${t.name === activeTopic ? " active" : ""}`;
      item.innerHTML = `
        <span class="topic-item-name">📁 ${escHtml(t.name)}</span>
        <span class="topic-item-count">${t.doc_count} docs</span>
      `;
      item.addEventListener("click", () => {
        chrome.storage.local.set({ activeTopic: t.name }, () => {
          showActiveTopic(t.name);
          loadTopics();
        });
      });
      topicsList.appendChild(item);
    }
  } catch {
    topicsList.innerHTML = '<div class="loading-text" style="color:#ef4444">Backend offline</div>';
  }
}

// ── Backend health check ───────────────────────────────────────────────────
async function checkBackendStatus() {
  try {
    const res = await fetch(`${BACKEND_URL}/health`, { signal: AbortSignal.timeout(2000) });
    if (res.ok) setStatusDot("ok");
    else setStatusDot("err");
  } catch {
    setStatusDot("err");
  }
}

function setStatusDot(state) {
  statusDot.className = `status-dot ${state}`;
}

// ── Helpers ────────────────────────────────────────────────────────────────
function getActiveTopic() {
  return new Promise((resolve) => {
    chrome.storage.local.get(["activeTopic"], (r) => resolve(r.activeTopic || null));
  });
}

function formatTime(ts) {
  const d = new Date(ts);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function escHtml(str) {
  return str.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}
