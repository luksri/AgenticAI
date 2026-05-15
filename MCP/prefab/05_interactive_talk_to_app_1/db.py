import sqlite3
import json
from pathlib import Path

DB_PATH = Path(__file__).parent / "dashboard.db"

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dashboard (
                id INTEGER PRIMARY KEY,
                spec TEXT NOT NULL
            )
        """)
        # Seed with initial default spec if empty
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM dashboard")
        if cur.fetchone()[0] == 0:
            default_spec = {
                "template": "dashboard",
                "params": {
                    "title": "Interactive Dashboard",
                    "tabs": [
                        {
                            "name": "Welcome",
                            "widgets": [
                                {
                                    "kind": "text",
                                    "heading": "Welcome to the Persistent Dashboard!",
                                    "body": "Type a prompt below to add widgets or change the layout. Your changes will be saved to SQLite.",
                                    "level": "h2"
                                }
                            ]
                        }
                    ]
                }
            }
            conn.execute("INSERT INTO dashboard (id, spec) VALUES (1, ?)", (json.dumps(default_spec),))

def get_spec() -> dict:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT spec FROM dashboard WHERE id = 1")
        row = cur.fetchone()
        return json.loads(row[0]) if row else {}

def save_spec(spec: dict):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE dashboard SET spec = ? WHERE id = 1", (json.dumps(spec),))

if __name__ == "__main__":
    init_db()
    print("Database initialized.")
