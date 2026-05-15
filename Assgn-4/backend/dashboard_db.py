import sqlite3
import json
from pathlib import Path

DB_PATH = Path(__file__).parent / "dashboards.db"

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dashboards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT,
                title TEXT,
                spec TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

def save_dashboard(spec: dict, topic: str = None, title: str = "Untitled Dashboard"):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO dashboards (topic, title, spec) VALUES (?, ?, ?)",
            (topic, title, json.dumps(spec))
        )

def delete_dashboard(dashboard_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM dashboards WHERE id = ?", (dashboard_id,))

def get_dashboards(topic: str = None):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        if topic:
            cur.execute("SELECT id, topic, title, spec, created_at FROM dashboards WHERE topic = ? ORDER BY created_at DESC", (topic,))
        else:
            cur.execute("SELECT id, topic, title, spec, created_at FROM dashboards ORDER BY created_at DESC")
        
        rows = cur.fetchall()
        return [
            {
                "id": r[0],
                "topic": r[1],
                "title": r[2],
                "spec": json.loads(r[3]),
                "created_at": r[4]
            }
            for r in rows
        ]

if __name__ == "__main__":
    init_db()
