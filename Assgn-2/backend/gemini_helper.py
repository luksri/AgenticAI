import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY", "")
client = genai.Client(api_key=api_key) if api_key else genai.Client()

def get_joke():
    """Fetches a joke from Gemini."""
    prompt = "Tell me a short, funny, and clean joke to spice up someone's mood."
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        return response.text.strip()
    except Exception as e:
        print("Error getting joke:", e)
        return "Why did the programmer quit his job? Because he didn't get arrays!"

def analyze_user_mood(user_text, current_time, activity):
    """
    Analyzes the user's mood based on what they said, what they are doing, and the time.
    Returns a short JSON-like summary of mood.
    """
    prompt = f"""
    You are an empathetic assistant analyzing a user's state.
    Here is what they said: "{user_text}"
    Current activity: {activity}
    Current time: {current_time}
    
    Based on this, what is their likely mood? (e.g., Stressed, Happy, Sad, Tired, Bored)
    Also, recommend a short, non-music activity they can do right now to improve or spice up their mood (like "call a friend", "take a 5 min walk").
    
    Return the response strictly in this format:
    Mood: [One word mood]
    Recommendation: [Short activity recommendation]
    """
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        lines = response.text.strip().split('\n')
        mood = "Unknown"
        rec = "Take a deep breath and give yourself a break."
        for line in lines:
            if line.startswith("Mood:"):
                mood = line.split(":", 1)[1].strip()
            elif line.startswith("Recommendation:"):
                rec = line.split(":", 1)[1].strip()
        return {"mood": mood, "activity_recommendation": rec}
    except Exception as e:
        print("Error analyzing mood:", e)
        return {"mood": "Neutral", "activity_recommendation": "Take a short break."}
