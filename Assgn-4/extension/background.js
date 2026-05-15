// background.js — Service worker for Knowledge Collector extension

const BACKEND_URL = "http://localhost:8000";

// ── Register context menus on install ──────────────────────────────────────
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "send-selection",
    title: "📝 Send selected text to Knowledge Base",
    contexts: ["selection"],
  });

  chrome.contextMenus.create({
    id: "send-page",
    title: "🌐 Send this page to Knowledge Base",
    contexts: ["page", "link"],
  });

  chrome.contextMenus.create({
    id: "send-youtube",
    title: "▶️ Send YouTube video to Knowledge Base",
    contexts: ["page", "link"],
    documentUrlPatterns: ["*://*.youtube.com/watch*"],
  });
});

// ── Context menu click handler ─────────────────────────────────────────────
chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const topic = await getActiveTopic();

  if (!topic) {
    // No active topic set — open popup for user to set one, then retry
    chrome.storage.local.set({ pendingAction: { info, tabId: tab.id } });
    chrome.action.openPopup();
    return;
  }

  if (info.menuItemId === "send-selection") {
    await sendToBackend({
      type: "text",
      content: info.selectionText,
      source: info.pageUrl || tab.url,
      topic,
    });
  } else if (info.menuItemId === "send-page") {
    await scrapeAndSend(tab, topic);
  } else if (info.menuItemId === "send-youtube") {
    const url = info.linkUrl || info.pageUrl || tab.url;
    await sendToBackend({
      type: "youtube",
      url,
      source: url,
      topic,
    });
  }
});

// ── Scrape page content via content script ─────────────────────────────────
async function scrapeAndSend(tab, topic) {
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ["content.js"],
    });
    const pageData = results[0]?.result;
    if (!pageData) throw new Error("Could not extract page content");

    await sendToBackend({
      type: "page",
      content: pageData.text,
      title: pageData.title,
      source: tab.url,
      topic,
    });
  } catch (err) {
    console.error("Scrape error:", err);
    setBadge("ERR", "#e74c3c");
  }
}

// ── Send payload to backend ────────────────────────────────────────────────
async function sendToBackend(payload) {
  setBadge("...", "#f39c12");
  try {
    const res = await fetch(`${BACKEND_URL}/ingest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    // Store last result for popup display
    chrome.storage.local.set({
      lastResult: {
        status: "success",
        message: `✅ Saved to "${data.topic}" (${data.doc_count} docs total)`,
        timestamp: Date.now(),
      },
    });
    setBadge("✓", "#2ecc71");
    setTimeout(() => clearBadge(), 3000);
  } catch (err) {
    console.error("Backend error:", err);
    chrome.storage.local.set({
      lastResult: {
        status: "error",
        message: `❌ Failed: ${err.message}`,
        timestamp: Date.now(),
      },
    });
    setBadge("ERR", "#e74c3c");
    setTimeout(() => clearBadge(), 5000);
  }
}

// ── Helpers ────────────────────────────────────────────────────────────────
async function getActiveTopic() {
  return new Promise((resolve) => {
    chrome.storage.local.get(["activeTopic"], (result) => {
      resolve(result.activeTopic || null);
    });
  });
}

function setBadge(text, color) {
  chrome.action.setBadgeText({ text });
  chrome.action.setBadgeBackgroundColor({ color });
}

function clearBadge() {
  chrome.action.setBadgeText({ text: "" });
}

// ── Listen for messages from popup ─────────────────────────────────────────
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "TOPIC_SET") {
    // After topic is set in popup, retry any pending action
    chrome.storage.local.get(["pendingAction"], async (result) => {
      if (result.pendingAction) {
        chrome.storage.local.remove("pendingAction");
        const { info, tabId } = result.pendingAction;
        const tab = await chrome.tabs.get(tabId);
        if (info.menuItemId === "send-page") {
          await scrapeAndSend(tab, msg.topic);
        } else if (info.menuItemId === "send-selection") {
          await sendToBackend({
            type: "text",
            content: info.selectionText,
            source: info.pageUrl || tab.url,
            topic: msg.topic,
          });
        } else if (info.menuItemId === "send-youtube") {
          const url = info.linkUrl || info.pageUrl || tab.url;
          await sendToBackend({ type: "youtube", url, source: url, topic: msg.topic });
        }
      }
    });
    sendResponse({ ok: true });
  }
  return true;
});
