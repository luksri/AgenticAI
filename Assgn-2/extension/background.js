// Set an alarm when the extension is installed or updated
chrome.runtime.onInstalled.addListener(() => {
    // Alarm every 60 minutes
    chrome.alarms.create('moodSpicerHourly', { periodInMinutes: 120 });
});

// Listen for the alarm
chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === 'moodSpicerHourly') {
        chrome.storage.local.get(['popupWindowId'], (result) => {
            const popupWindowId = result.popupWindowId;
            if (popupWindowId) {
                chrome.windows.get(popupWindowId, { populate: true }, (win) => {
                    if (chrome.runtime.lastError || !win) {
                        // Window doesn't exist anymore, create a new one
                        createPopupWindow();
                    } else {
                        // Window exists — reload the page for a fresh joke, then focus it
                        chrome.tabs.reload(win.tabs[0].id);
                        chrome.windows.update(popupWindowId, { focused: true });
                    }
                });
            } else {
                createPopupWindow();
            }
        });
    }
});

function createPopupWindow() {
    chrome.windows.create({
        url: "popup.html",
        type: "popup",
        width: 400,
        height: 600
    }, (window) => {
        // Save the window ID to local storage so we can focus it next time
        chrome.storage.local.set({ popupWindowId: window.id });
    });
}
