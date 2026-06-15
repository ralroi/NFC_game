"""
CaptureBox — database.py
Complete database layer with all v3 additions
"""
import sqlite3
import json
from datetime import datetime
from contextlib import contextmanager

DB_PATH = '/home/pi_game/capturebox/capturebox.db'

@contextmanager
def get_db():
    con = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

# =============================================================
#  SCHEMA
# =============================================================
def init_db():
    with get_db() as con:

        con.execute("""
            CREATE TABLE IF NOT EXISTS factions (
                id          INTEGER PRIMARY KEY,
                name        TEXT NOT NULL,
                color_hex   TEXT NOT NULL,
                color_name  TEXT NOT NULL,
                max_players INTEGER DEFAULT 0
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS boxes (
                box_id          TEXT PRIMARY KEY,
                name            TEXT,
                location_desc   TEXT,
                lat             REAL,
                lng             REAL,
                active          INTEGER DEFAULT 1,
                stolen          INTEGER DEFAULT 0,
                battery_pct     INTEGER,
                last_heartbeat  TEXT,
                firmware_ver    TEXT,
                rssi            INTEGER,
                wifi_rssi       INTEGER,
                comms_mode      TEXT DEFAULT 'unknown',
                notes           TEXT,
                created_at      TEXT DEFAULT (datetime('now'))
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                uid             TEXT PRIMARY KEY,
                faction_id      INTEGER REFERENCES factions(id),
                player_name     TEXT,
                blocked         INTEGER DEFAULT 0,
                registered_at   TEXT DEFAULT (datetime('now')),
                registered_box  TEXT REFERENCES boxes(box_id),
                last_seen_at    TEXT,
                last_seen_box   TEXT REFERENCES boxes(box_id),
                scan_count      INTEGER DEFAULT 0,
                card_type       TEXT DEFAULT 'ntag'
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS ownership (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                box_id      TEXT REFERENCES boxes(box_id),
                faction_id  INTEGER REFERENCES factions(id),
                started_at  TEXT DEFAULT (datetime('now')),
                ended_at    TEXT
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT DEFAULT (datetime('now')),
                box_id      TEXT REFERENCES boxes(box_id),
                faction_id  INTEGER,
                card_uid    TEXT,
                event_type  TEXT,
                detail      TEXT,
                rssi        INTEGER
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS scenarios (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                name                 TEXT NOT NULL,
                description          TEXT,
                capture_hold_seconds INTEGER DEFAULT 30,
                green_instant        INTEGER DEFAULT 1,
                cooldown_minutes     INTEGER DEFAULT 10,
                decay_seconds        INTEGER DEFAULT 1800,
                max_per_faction      INTEGER DEFAULT 0,
                game_duration_hours  INTEGER DEFAULT 72,
                rescan_penalty       INTEGER DEFAULT 1,
                king_box_id          TEXT,
                king_multiplier      INTEGER DEFAULT 5,
                alliance_mode        INTEGER DEFAULT 0,
                active               INTEGER DEFAULT 0,
                created_at           TEXT DEFAULT (datetime('now'))
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS games (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                scenario_id     INTEGER REFERENCES scenarios(id),
                name            TEXT,
                started_at      TEXT,
                ended_at        TEXT,
                status          TEXT DEFAULT 'pending',
                winner_faction  INTEGER,
                notes           TEXT
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS commands (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                box_id      TEXT,
                command     TEXT,
                payload     TEXT,
                status      TEXT DEFAULT 'pending',
                created_at  TEXT DEFAULT (datetime('now')),
                sent_at     TEXT,
                acked_at    TEXT
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key     TEXT PRIMARY KEY,
                value   TEXT
            )
        """)

        # Seed factions
        con.execute("""
            INSERT OR IGNORE INTO factions (id, name, color_hex, color_name) VALUES
            (1, 'The Foundation', '#2980b9', 'Blue'),
            (2, 'The Opposition', '#e74c3c', 'Red'),
            (3, 'Aliens',         '#f1c40f', 'Yellow'),
            (4, 'Rebellion',      '#27ae60', 'Green')
        """)

        # Seed scenarios
        scenarios = [
            (1, 'Classic',        'Standard game. Hold to capture, decay keeps teams moving.',         30, 1800, 10,  0, 72, 1),
            (2, 'Blitz',          'Fast 1-hour game. Short holds, no decay, no cooldown.',             10,    0,  0,  0,  1, 0),
            (3, 'Siege',          'Defenders start owning all boxes. Attackers must flip them.',        45, 3600, 15,  0,  4, 0),
            (4, 'King of Hill',   'One central box scores 5x. Set king box in Pi settings.',           30, 1800,  5,  0, 24, 0),
            (5, 'Decay',          'Boxes decay fast. Players must keep visiting their boxes.',          20,  600,  0,  0, 12, 0),
            (6, 'Sabotage',       'Green instant capture vs all others.',                              40, 2400, 10,  0,  8, 0),
            (7, 'Alliance',       'Blue+Green vs Red+Yellow. Pi combines faction scores.',             30, 1800, 10,  0, 24, 0),
            (8, 'Blackout',       'No live dashboard during game. Scores revealed at the end.',        30, 1800, 10,  0, 72, 0),
        ]
        for s in scenarios:
            con.execute("""
                INSERT OR IGNORE INTO scenarios
                (id,name,description,capture_hold_seconds,decay_seconds,
                 cooldown_minutes,alliance_mode,game_duration_hours,rescan_penalty,active)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, s)

        # Seed settings
        defaults = [
            ('volume_default',  '20'),
            ('silent_from',     '22'),
            ('silent_until',    '8'),
            ('bri_active',      '80'),
            ('bri_idle',        '20'),
            ('bri_sleep',       '5'),
            ('dim_idle_sec',    '120'),
            ('dim_sleep_sec',   '600'),
            ('lora_tx_power',   '14'),
            ('heartbeat_sec',   '30'),
            ('rssi_good',       '-65'),
            ('rssi_poor',       '-80'),
            ('wifi_mode',       '0'),
            ('discord_enabled', '0'),
            ('discord_webhook', ''),
            ('discord_events',  'capture,lost,game_start,game_end'),
            ('game_status',     'stopped'),
            ('cooldown_minutes','10'),
        ]
        for k, v in defaults:
            con.execute("INSERT OR IGNORE INTO settings (key,value) VALUES (?,?)", (k, v))

        # Indexes
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_box  ON events(box_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_card ON events(card_uid)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_time ON events(timestamp)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_own_box     ON ownership(box_id)")

    print("✓ Database initialised at", DB_PATH)

# =============================================================
#  SETTINGS
# =============================================================
def get_setting(key, default=None):
    with get_db() as con:
        row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row['value'] if row else default

def set_setting(key, value):
    with get_db() as con:
        con.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, str(value)))

# =============================================================
#  FACTIONS
# =============================================================
def get_factions():
    with get_db() as con:
        return [dict(r) for r in con.execute("SELECT * FROM factions ORDER BY id").fetchall()]

def get_faction_player_counts():
    with get_db() as con:
        rows = con.execute("""
            SELECT f.id, f.name, f.color_hex, f.color_name, f.max_players,
                   COUNT(c.uid) as player_count
            FROM factions f
            LEFT JOIN cards c ON c.faction_id=f.id AND c.blocked=0
            GROUP BY f.id
        """).fetchall()
        return [dict(r) for r in rows]

def get_blocked_factions():
    rows = get_faction_player_counts()
    return [r['id'] for r in rows if r['max_players']>0 and r['player_count']>=r['max_players']]

# =============================================================
#  BOXES
# =============================================================
def get_all_boxes():
    with get_db() as con:
        rows = con.execute("""
            SELECT b.*, o.faction_id as current_faction,
                   o.started_at as owned_since,
                   f.color_hex, f.color_name, f.name as faction_name
            FROM boxes b
            LEFT JOIN ownership o ON b.box_id=o.box_id AND o.ended_at IS NULL
            LEFT JOIN factions f ON o.faction_id=f.id
            ORDER BY b.name
        """).fetchall()
        return [dict(r) for r in rows]

def get_box(box_id):
    with get_db() as con:
        row = con.execute("SELECT * FROM boxes WHERE box_id=?", (box_id,)).fetchone()
        return dict(row) if row else None

def upsert_box(box_id, name=None, location_desc=None, lat=None,
               lng=None, active=None, notes=None):
    with get_db() as con:
        ex = con.execute("SELECT box_id FROM boxes WHERE box_id=?", (box_id,)).fetchone()
        if ex:
            fields, vals = [], []
            for col, val in [('name',name),('location_desc',location_desc),
                             ('lat',lat),('lng',lng),('active',active),('notes',notes)]:
                if val is not None:
                    fields.append(f"{col}=?"); vals.append(val)
            if fields:
                vals.append(box_id)
                con.execute(f"UPDATE boxes SET {','.join(fields)} WHERE box_id=?", vals)
        else:
            con.execute("""
                INSERT INTO boxes (box_id,name,location_desc,lat,lng,active,notes)
                VALUES (?,?,?,?,?,?,?)
            """, (box_id, name or box_id, location_desc, lat, lng,
                  1 if active is None else active, notes))

def update_box_heartbeat(box_id, battery_pct=None, rssi=None,
                         firmware_ver=None, comms_mode=None, wifi_rssi=None):
    with get_db() as con:
        con.execute("""
            UPDATE boxes SET last_heartbeat=datetime('now'),
            battery_pct  = COALESCE(?,battery_pct),
            rssi         = COALESCE(?,rssi),
            firmware_ver = COALESCE(?,firmware_ver),
            comms_mode   = COALESCE(?,comms_mode),
            wifi_rssi    = COALESCE(?,wifi_rssi)
            WHERE box_id=?
        """, (battery_pct, rssi, firmware_ver, comms_mode, wifi_rssi, box_id))

def mark_box_stolen(box_id, stolen=True):
    with get_db() as con:
        con.execute("UPDATE boxes SET stolen=? WHERE box_id=?", (1 if stolen else 0, box_id))

# =============================================================
#  CARDS
# =============================================================
def get_card(uid):
    with get_db() as con:
        row = con.execute("SELECT * FROM cards WHERE uid=?", (uid,)).fetchone()
        return dict(row) if row else None

def get_all_cards():
    with get_db() as con:
        rows = con.execute("""
            SELECT c.*, f.color_name, f.color_hex, f.name as faction_name
            FROM cards c
            LEFT JOIN factions f ON c.faction_id=f.id
            ORDER BY c.registered_at DESC
        """).fetchall()
        return [dict(r) for r in rows]

def register_card(uid, faction_id, player_name=None,
                  registered_box=None, card_type='ntag'):
    with get_db() as con:
        con.execute("""
            INSERT OR REPLACE INTO cards
            (uid,faction_id,player_name,registered_box,card_type,registered_at)
            VALUES (?,?,?,?,?,datetime('now'))
        """, (uid, faction_id, player_name, registered_box, card_type))

def reset_card(uid):
    with get_db() as con:
        con.execute("DELETE FROM cards WHERE uid=?", (uid,))

def block_card(uid, blocked=True):
    with get_db() as con:
        con.execute("UPDATE cards SET blocked=? WHERE uid=?", (1 if blocked else 0, uid))

def update_card_seen(uid, box_id):
    with get_db() as con:
        con.execute("""
            UPDATE cards SET last_seen_at=datetime('now'),
            last_seen_box=?, scan_count=scan_count+1 WHERE uid=?
        """, (box_id, uid))

# =============================================================
#  OWNERSHIP
# =============================================================
def get_current_owner(box_id):
    with get_db() as con:
        row = con.execute("""
            SELECT faction_id, started_at FROM ownership
            WHERE box_id=? AND ended_at IS NULL
            ORDER BY started_at DESC LIMIT 1
        """, (box_id,)).fetchone()
        return (row['faction_id'], row['started_at']) if row else (None, None)

def end_ownership(box_id):
    with get_db() as con:
        con.execute("""
            UPDATE ownership SET ended_at=datetime('now')
            WHERE box_id=? AND ended_at IS NULL
        """, (box_id,))

def start_ownership(box_id, faction_id):
    with get_db() as con:
        con.execute("INSERT INTO ownership (box_id,faction_id) VALUES (?,?)",
                    (box_id, faction_id))

# =============================================================
#  EVENTS
# =============================================================
def log_event(box_id, faction_id, card_uid, event_type, detail=None, rssi=None):
    with get_db() as con:
        con.execute("""
            INSERT INTO events (box_id,faction_id,card_uid,event_type,detail,rssi)
            VALUES (?,?,?,?,?,?)
        """, (box_id, faction_id, card_uid, event_type, detail, rssi))

def get_recent_events(limit=50, box_id=None):
    with get_db() as con:
        if box_id:
            rows = con.execute("""
                SELECT e.*, f.color_hex, f.color_name, f.name as faction_name,
                       b.name as box_name, c.player_name
                FROM events e
                LEFT JOIN factions f ON e.faction_id=f.id
                LEFT JOIN boxes b ON e.box_id=b.box_id
                LEFT JOIN cards c ON e.card_uid=c.uid
                WHERE e.box_id=?
                ORDER BY e.timestamp DESC LIMIT ?
            """, (box_id, limit)).fetchall()
        else:
            rows = con.execute("""
                SELECT e.*, f.color_hex, f.color_name, f.name as faction_name,
                       b.name as box_name, c.player_name
                FROM events e
                LEFT JOIN factions f ON e.faction_id=f.id
                LEFT JOIN boxes b ON e.box_id=b.box_id
                LEFT JOIN cards c ON e.card_uid=c.uid
                ORDER BY e.timestamp DESC LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]

def trim_box_events(box_id, keep=2):
    """Keep only last N scan events per box to avoid DB bloat."""
    with get_db() as con:
        con.execute("""
            DELETE FROM events WHERE box_id=?
            AND event_type NOT IN ('heartbeat','admin_reset')
            AND id NOT IN (
                SELECT id FROM events WHERE box_id=?
                AND event_type NOT IN ('heartbeat','admin_reset')
                ORDER BY timestamp DESC LIMIT ?
            )
        """, (box_id, box_id, keep))

# =============================================================
#  SCORES & LEADERBOARD
# =============================================================
def get_faction_scores():
    with get_db() as con:
        rows = con.execute("""
            SELECT f.id, f.name, f.color_hex, f.color_name,
                   COALESCE(SUM(
                       (julianday(COALESCE(o.ended_at,datetime('now')))
                        - julianday(o.started_at)) * 1440
                   ),0) as minutes_owned,
                   COUNT(DISTINCT CASE WHEN o.ended_at IS NULL THEN o.box_id END) as boxes_held
            FROM factions f
            LEFT JOIN ownership o ON f.id=o.faction_id
            GROUP BY f.id ORDER BY minutes_owned DESC
        """).fetchall()
        return [dict(r) for r in rows]

def get_player_leaderboard():
    with get_db() as con:
        rows = con.execute("""
            SELECT c.uid, c.player_name, c.faction_id, c.scan_count,
                   f.color_hex, f.color_name, f.name as faction_name,
                   COUNT(DISTINCT CASE WHEN e.event_type='capture' THEN e.id END) as captures,
                   c.last_seen_at, c.last_seen_box
            FROM cards c
            LEFT JOIN factions f ON c.faction_id=f.id
            LEFT JOIN events e ON c.uid=e.card_uid
            GROUP BY c.uid ORDER BY captures DESC, c.scan_count DESC
        """).fetchall()
        return [dict(r) for r in rows]

def get_box_usage_stats():
    with get_db() as con:
        rows = con.execute("""
            SELECT b.box_id, b.name,
                   COUNT(e.id) as total_scans,
                   COUNT(DISTINCT e.card_uid) as unique_cards,
                   COUNT(DISTINCT CASE WHEN e.event_type='capture' THEN e.id END) as captures,
                   MAX(e.timestamp) as last_activity
            FROM boxes b
            LEFT JOIN events e ON b.box_id=e.box_id
            GROUP BY b.box_id ORDER BY total_scans DESC
        """).fetchall()
        return [dict(r) for r in rows]

# =============================================================
#  COOLDOWN
# =============================================================
def check_cooldown(box_id, card_uid, minutes=10):
    with get_db() as con:
        row = con.execute("""
            SELECT timestamp FROM events
            WHERE box_id=? AND card_uid=?
            ORDER BY timestamp DESC LIMIT 1
        """, (box_id, card_uid)).fetchone()
        if not row: return False
        last = datetime.fromisoformat(row['timestamp'])
        return (datetime.utcnow()-last).total_seconds()/60 < minutes

# =============================================================
#  COMMANDS
# =============================================================
def queue_command(box_id, command, payload=None):
    with get_db() as con:
        con.execute("""
            INSERT INTO commands (box_id,command,payload)
            VALUES (?,?,?)
        """, (box_id, command, json.dumps(payload) if payload else None))

def get_pending_commands(box_id):
    with get_db() as con:
        rows = con.execute("""
            SELECT * FROM commands
            WHERE box_id=? AND status='pending'
            ORDER BY created_at
        """, (box_id,)).fetchall()
        return [dict(r) for r in rows]

def ack_command(cmd_id):
    with get_db() as con:
        con.execute("""
            UPDATE commands SET status='acked', acked_at=datetime('now')
            WHERE id=?
        """, (cmd_id,))

if __name__ == '__main__':
    init_db()
