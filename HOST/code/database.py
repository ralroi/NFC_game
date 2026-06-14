import sqlite3
from datetime import datetime

DB = "capturebox.db"

def init_db():
    con = sqlite3.connect(DB)
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS cards (
            uid TEXT PRIMARY KEY,
            faction_id INTEGER,
            registered_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS boxes (
            box_id TEXT PRIMARY KEY,
            name TEXT,
            location TEXT,
            lat REAL,
            lng REAL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            box_id TEXT,
            faction_id INTEGER,
            card_uid TEXT,
            timestamp TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ownership (
            box_id TEXT,
            faction_id INTEGER,
            started_at TEXT,
            ended_at TEXT
        )
    """)

    con.commit()
    con.close()

def get_faction_totals():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("""
        SELECT faction_id, SUM(
            (julianday(COALESCE(ended_at, datetime('now'))) - julianday(started_at)) * 24
        ) as hours
        FROM ownership
        GROUP BY faction_id
        ORDER BY hours DESC
    """)
    rows = cur.fetchall()
    con.close()
    return rows

def get_box_status():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("""
        SELECT b.box_id, b.name, b.lat, b.lng,
               o.faction_id, o.started_at
        FROM boxes b
        LEFT JOIN ownership o ON b.box_id = o.box_id AND o.ended_at IS NULL
    """)
    rows = cur.fetchall()
    con.close()
    return rows

def get_recent_events(limit=20):
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("""
        SELECT timestamp, box_id, faction_id, card_uid
        FROM events
        ORDER BY timestamp DESC
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    con.close()
    return rows

if __name__ == "__main__":
    init_db()
    print("Database initialized.")