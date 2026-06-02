document.addEventListener('DOMContentLoaded', async () => {
  const titleEl = document.getElementById('page-title');
  const urlEl = document.getElementById('page-url');
  const feedBtn = document.getElementById('feed-btn');
  const statusBox = document.getElementById('status-box');

  let activeTab = null;

  function showStatus(text, type) {
    statusBox.className = `status ${type}`;
    statusBox.textContent = text;
  }

  // Get active tab info
  try {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tabs && tabs[0]) {
      activeTab = tabs[0];
      titleEl.textContent = activeTab.title || 'Untitled Page';
      urlEl.textContent = activeTab.url || '';
      
      // Enable button only for http/https pages
      if (activeTab.url && (activeTab.url.startsWith('http://') || activeTab.url.startsWith('https://'))) {
        feedBtn.disabled = false;
      } else {
        showStatus('Can only feed web pages (http/https).', 'error');
      }
    } else {
      titleEl.textContent = 'No active tab found';
    }
  } catch (err) {
    titleEl.textContent = 'Error querying tab info';
    showStatus(err.message, 'error');
  }

  // Handle feed button click
  feedBtn.addEventListener('click', async () => {
    if (!activeTab) return;

    feedBtn.disabled = true;
    showStatus('Extracting content...', 'loading');

    try {
      // Execute script on tab to get visible text content
      const [{ result }] = await chrome.scripting.executeScript({
        target: { tabId: activeTab.id },
        func: () => {
          // Get clean innerText from body
          return document.body.innerText || '';
        }
      });

      if (!result || !result.trim()) {
        throw new Error('No readable text content found on the page.');
      }

      showStatus('Embedding and indexing...', 'loading');

      // Send payload to gateway server
      const response = await fetch('http://localhost:8107/v1/feed', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          url: activeTab.url,
          title: activeTab.title,
          content: result
        })
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Server returned ${response.status}: ${errorText}`);
      }

      const resData = await response.json();
      showStatus('Successfully indexed in vector store!', 'success');
    } catch (err) {
      showStatus(err.message, 'error');
      feedBtn.disabled = false;
    }
  });
});
