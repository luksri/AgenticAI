const ALARMS = {
  eyes: {
    periodInMinutes: 20,
    title: "Time for an Eye Rest! (20-20-20 Rule)",
    message: "Look 20 feet away for 20 seconds. This prevents digital eye strain and blurred vision."
  },
  water: {
    periodInMinutes: 150,
    title: "Drink Water! (250ml)",
    message: "Time to drink a glass of water. Staying hydrated keeps your brain sharp and energy levels stable throughout the day."
  },
  standup: {
    periodInMinutes: 60,
    title: "Stand Up! (10 mins)",
    message: "Take 10 minutes to stand. Standing burns more calories, improves posture, and enhances circulation compared to sitting."
  },
  stretch_walk: {
    periodInMinutes: 120,
    title: "Stretch & Walk! (5 mins)",
    message: "Take 5 minutes to stretch and walk around. This relieves muscle tension, reduces joint pain, and prevents stiffness."
  }
};

// A transparent 1x1 pixel data URL used as a required placeholder for Chrome notification icons
const DEFAULT_ICON = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=";

chrome.runtime.onInstalled.addListener(() => {
  // Create alarms for each ergonomic reminder
  for (const [name, config] of Object.entries(ALARMS)) {
    chrome.alarms.create(name, { periodInMinutes: config.periodInMinutes });
  }

  // Confirm extension is active immediately on install/reload
  chrome.notifications.create("install_" + Date.now(), {
    type: "basic",
    iconUrl: DEFAULT_ICON,
    title: "Ergonomic Alerts Active!",
    message: "Your timers are running in the background. You'll get your first reminder soon!",
    priority: 2
  });
});

chrome.alarms.onAlarm.addListener((alarm) => {
  const currentHour = new Date().getHours();

  // Only alert during work hours: 9 AM to 6 PM
  if (currentHour >= 9 && currentHour < 18) {
    const alarmConfig = ALARMS[alarm.name];
    if (alarmConfig) {
      chrome.notifications.create(alarm.name + "_" + Date.now(), {
        type: "basic",
        iconUrl: DEFAULT_ICON,
        title: alarmConfig.title,
        message: alarmConfig.message,
        priority: 2
      });
    }
  }
});
