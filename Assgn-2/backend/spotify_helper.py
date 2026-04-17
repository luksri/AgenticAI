import pandas as pd
import random
import os

CSV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "spotify", "spotify_songs.csv")

try:
    df = pd.read_csv(CSV_PATH)
except Exception as e:
    print(f"Error loading CSV at {CSV_PATH}: {e}")
    df = None

def get_song_recommendation(mood, spice_up=False):
    """
    Recommends a song based on the user's mood.
    Valence: Positivity (0 to 1). Energy: Intensity (0 to 1).
    """
    if df is None or df.empty:
        return {"name": "No song found. Database error.", "artist": "", "url": ""}
        
    mood_lower = mood.lower()
    
    # Defaults mapping mood to desired audio features
    # If they want to spice it up, we aim for higher valence/energy than their current state dictates
    min_valence = 0.4
    max_valence = 1.0
    min_energy = 0.4
    max_energy = 1.0
    
    if "sad" in mood_lower or "depressed" in mood_lower or "burn" in mood_lower:
        # If spice_up is true, give them a huge boost. If false, gentle boost.
        min_valence = 0.7 if spice_up else 0.5
        min_energy = 0.6 if spice_up else 0.4
    elif "tire" in mood_lower or "exhaust" in mood_lower or "stress" in mood_lower:
        # Soothing but positive if not spice_up. If spice_up, energetic.
        min_valence = 0.6 if spice_up else 0.5
        min_energy = 0.8 if spice_up else 0.2
        max_energy = 1.0 if spice_up else 0.5
    elif "happy" in mood_lower or "good" in mood_lower or "excit" in mood_lower:
        min_valence = 0.7
        min_energy = 0.8 if spice_up else 0.6
    else:
        # Neutral or unknown
        min_valence = 0.6
        min_energy = 0.7 if spice_up else 0.5

    # Filter dataframe
    filtered = df[(df['valence'] >= min_valence) & (df['valence'] <= max_valence) &
                  (df['energy'] >= min_energy) & (df['energy'] <= max_energy)]
                  
    if filtered.empty:
        # Fallback if too strict
        filtered = df[(df['valence'] >= 0.5)]
        if filtered.empty:
            filtered = df
            
    # Pick a random song from the filtered list
    song = filtered.sample(1).iloc[0]
    
    # We'll create a fake URL or just return the name and artist
    # Since track_id is present, we could form a spotify URL: https://open.spotify.com/track/{track_id}
    track_id = song.get('track_id', '')
    url = f"https://open.spotify.com/track/{track_id}" if track_id else ""
    
    return {
        "name": song.get('track_name', 'Unknown Song'),
        "artist": song.get('track_artist', 'Unknown Artist'),
        "url": url
    }
