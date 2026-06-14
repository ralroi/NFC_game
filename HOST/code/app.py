from flask import Flask, render_template, jsonify, request
from database import init_db, get_faction_totals, get_box_status, get_recent_events
import sqlite3

app = Flask(__name__)
DB = "capturebox.db"

FACTIONS = {
    1: {"name": "Red",    "color": "#e74c3c"},
    2: {"name": "Blue",   "color": "#2980b9"},
    3: {"name": "Green",  "color": "#27ae60"},
    4: {"name": "Yellow", "color": "#f1c40f"},
}

@app.route("/")
def index():
    totals = get_faction_totals()
    boxes  = get_box_status()
    events = get_recent_events()
    return render_template("index.html",
        totals=totals, boxes=boxes,
        events=events, factions=FACTIONS)

@app.route("/api/status")
def api_status():
    return jsonify({
        "totals": get_faction_totals(),
        "boxes":  get_box_status(),
        "events": get_recent_events(10)
    })

@app.route("/api/register_box", methods=["POST"])
def register_box():
    data = request.json
    con = sqlite3.connect(DB)
    con.execute("""
        INSERT OR REPLACE INTO boxes (box_id, name, location, lat, lng)
        VALUES (?, ?, ?, ?, ?)
    """, (data["box_id"], data["name"], data["location"],
          data.get("lat"), data.get("lng")))
    con.commit()
    con.close()
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)