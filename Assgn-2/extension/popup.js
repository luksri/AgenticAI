const API_BASE = "http://127.0.0.1:8000";

document.addEventListener('DOMContentLoaded', async () => {
    const jokeText = document.getElementById('joke-text');
    const analyzeBtn = document.getElementById('analyze-btn');
    const spiceMoreBtn = document.getElementById('spice-more-btn');
    const resultsDiv = document.getElementById('results');
    
    // Store current mood to reuse for spice up
    let currentMood = "";

    // Fetch initial joke
    try {
        const res = await fetch(`${API_BASE}/joke`);
        if(res.ok) {
            const data = await res.json();
            jokeText.textContent = data.joke;
        } else {
            jokeText.textContent = "Couldn't load a joke right now. Server might be napping!";
        }
    } catch (e) {
        jokeText.textContent = "Backend server not reachable. Did you start the Python app?";
    }

    analyzeBtn.addEventListener('click', async () => {
        const dayInput = document.getElementById('day-input').value;
        const activityInput = document.getElementById('activity-input').value;

        if (!dayInput) return;

        analyzeBtn.textContent = "Analyzing...";
        analyzeBtn.disabled = true;

        const now = new Date().toLocaleTimeString();

        try {
            // 1. Analyze Mood
            const moodRes = await fetch(`${API_BASE}/analyze_mood`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    user_text: dayInput,
                    current_time: now,
                    activity: activityInput || "Unknown"
                })
            });
            const moodData = await moodRes.json();
            currentMood = moodData.mood;

            // 2. Fetch Song Recommendation
            const songRes = await fetch(`${API_BASE}/recommend`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    mood: currentMood,
                    spice_up: false
                })
            });
            const songData = await songRes.json();

            // 3. Update UI
            document.getElementById('mood-text').textContent = moodData.mood;
            document.getElementById('activity-rec-text').textContent = moodData.activity_recommendation;
            
            updateSongUI(songData);

            resultsDiv.classList.remove('hidden');
        } catch (e) {
            console.error(e);
            alert("Error communicating with backend. Check console/server.");
        } finally {
            analyzeBtn.textContent = "Spice up my mood!";
            analyzeBtn.disabled = false;
        }
    });

    spiceMoreBtn.addEventListener('click', async () => {
        spiceMoreBtn.textContent = "Spicing... 🔥";
        spiceMoreBtn.disabled = true;

        try {
            // Ask for a "spiced up" song based on the same mood
            const songRes = await fetch(`${API_BASE}/recommend`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    mood: currentMood,
                    spice_up: true
                })
            });
            const songData = await songRes.json();
            
            updateSongUI(songData);
        } catch(e) {
            console.error(e);
        } finally {
            spiceMoreBtn.textContent = "Spice it up MORE! 🔥";
            spiceMoreBtn.disabled = false;
        }
    });

    function updateSongUI(songData) {
        document.getElementById('song-name').textContent = songData.name;
        document.getElementById('song-artist').textContent = songData.artist;
        const urlBtn = document.getElementById('song-url');
        if (songData.url) {
            urlBtn.href = songData.url;
            urlBtn.style.display = 'inline-block';
        } else {
            urlBtn.style.display = 'none';
        }
    }
});
