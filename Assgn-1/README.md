# Ergonomic Alerts Chrome Extension

A simple and effective Google Chrome extension designed to keep you healthy and active during your working hours (9 AM - 6 PM). 

## Features

This extension runs quietly in the background and sends you periodic native Chrome notifications with educational context to remind you to take care of your body:

- 👁️ **Eye Rest (Every 20 mins):** Reminds you of the 20-20-20 rule to prevent digital eye strain.
- 🧍 **Stand Up (Every 1 hour):** Reminds you to take 10 minutes to stand, burning more calories and improving posture.
- 🚶 **Stretch & Walk (Every 2 hours):** Reminds you to take 5 minutes to stretch and walk, relieving muscle tension and preventing stiffness.
- 💧 **Drink Water (Every 2.5 hours):** Ensures you stay hydrated throughout the day to keep your brain sharp and energy stable.

## Installation

1. Clone or download this repository to your local machine.
2. Open Google Chrome and navigate to `chrome://extensions/`.
3. Enable **Developer mode** in the top right corner of the page.
4. Click the **Load unpacked** button and select the directory containing this extension.
5. The extension will automatically start running and send you a welcome notification!

## How it Works

The extension uses the `chrome.alarms` and `chrome.notifications` APIs to schedule and deliver reminders without needing a constant background page. Alerts are intelligently scoped to only trigger during typical work hours (9 AM to 6 PM) so they won't disturb your personal time.
