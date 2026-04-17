from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json
import os
from datetime import datetime
from gemini_helper import get_joke, analyze_user_mood
from spotify_helper import get_song_recommendation

app = FastAPI()

# Allow CORS for Chrome Extension
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

LOG_FILE = "logs.json"

def log_interaction(event_type, data):
    """Helper to track user queries and recommendations to a local file."""
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "event": event_type,
        "data": data
    }
    logs = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            try:
                logs = json.load(f)
            except:
                logs = []
    logs.append(log_entry)
    with open(LOG_FILE, "w") as f:
        json.dump(logs, f, indent=4)


@app.get("/joke")
def fetch_joke():
    joke = get_joke()
    log_interaction("joke_fetched", {"joke": joke})
    return {"joke": joke}


class MoodInput(BaseModel):
    user_text: str
    current_time: str
    activity: str

@app.post("/analyze_mood")
def analyze_mood(data: MoodInput):
    result = analyze_user_mood(data.user_text, data.current_time, data.activity)
    log_interaction("mood_analyzed", {
        "input": data.dict(),
        "result": result
    })
    return result


class RecommendInput(BaseModel):
    mood: str
    spice_up: bool = False

@app.post("/recommend")
def recommend_song(data: RecommendInput):
    song = get_song_recommendation(data.mood, data.spice_up)
    log_interaction("song_recommended", {
        "input": data.dict(),
        "song": song
    })
    return song

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
