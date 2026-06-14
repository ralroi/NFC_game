#!/usr/bin/env python3
# =============================================================
#  CaptureBox — LoRa Receiver Service
#  Waveshare SX1262 HAT on Raspberry Pi
#  Runs as a separate systemd service
#  Receives packets from ESP32 boxes, writes to SQLite DB
# =============================================================

import sys
import os
import json
import time
import hmac
import hashlib
import logging
import sqlite3
from datetime import datetime

# Waveshare SX1262 HAT uses their own library
# Clone from: https://github.com/waveshare/sx1262-lorahat
# into /home/pi/sx1262-lorahat and add to path
sys.path.insert(0, '/home/pi/sx1262-lorahat/python')
from lora import SX1262

# =============================================================
#  CONFIG
# =============================================================
DB_PATH        = '/home/pi/capturebox/capturebox.db'
LOG_PATH       = '/home/pi/capturebox/lora_receiver.log'
FREQUENCY      = 868.0          # MHz — EU 868
BANDWIDTH      = 125            # kHz
SF             = 10             # Spreading factor (range vs speed)
CODING_RATE    = 5              # 4/5
HMAC_SECRET    = b'changeme123' # Must match secret in ESP32 firmware
COOLDOWN_MIN   = 10             # Minutes before same card can reclaim same box

# =============================================================
#  LOGGING
# =============================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger(__name__)

# =============================================================
#  DATABASE HELPERS
# =============================================================
def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def log_event(box_id, faction_id, card_uid):
    con = get_db()
    con.execute("""
        INSERT INTO events (box_id, faction_id, card_uid, timestamp)
        VALUES (?, ?, ?, datetime('now'))
    """, (box_id, faction_id, card_uid))
    con.commit()
    con.close()

def get_current_owner(box_id):
    """Returns (faction_id, started_at) or (None, None) if neutral."""
    con = get_db()
    cur = con.execute("""
        SELECT faction_id, started_at FROM ownership
        WHERE box_id = ? AND ended_at IS NULL
        ORDER BY started_at DESC LIMIT 1
    """, (box_id,))
    row = cur.fetchone()
    con.close()
    if row:
        return row['faction_id'], row['started_at']
    return None, None

def end_current_ownership(box_id):
    con = get_db()
    con.execute("""
        UPDATE ownership SET ended_at = datetime('now')
        WHERE box_id = ? AND ended_at IS NULL
    """, (box_id,))
    con.commit()
    con.close()

def start_ownership(box_id, faction_id):
    con = get_db()
    con.execute("""
        INSERT INTO ownership (box_id, faction_id, started_at)
        VALUES (?, ?, datetime('now'))
    """, (box_id, faction_id))
    con.commit()
    con.close()

def is_card_registered(card_uid):
    con = get_db()
    cur = con.execute("SELECT faction_id FROM cards WHERE uid = ?", (card_uid,))
    row = cur.fetchone()
    con.close()
    return row['faction_id'] if row else None

def check_cooldown(box_id, card_uid):
    """Returns True if card is still in cooldown on this box (rescan penalty)."""
    con = get_db()
    cur = con.execute("""
        SELECT timestamp FROM events
        WHERE box_id = ? AND card_uid = ?
        ORDER BY timestamp DESC LIMIT 1
    """, (box_id, card_uid))
    row = cur.fetchone()
    con.close()
    if not row:
        return False
    last = datetime.fromisoformat(row['timestamp'])
    elapsed = (datetime.utcnow() - last).total_seconds() / 60
    return elapsed < COOLDOWN_MIN

def log_unknown_scan(box_id, card_uid):
    con = get_db()
    con.execute("""
        INSERT INTO events (box_id, faction_id, card_uid, timestamp)
        VALUES (?, NULL, ?, datetime('now'))
    """, (box_id, card_uid))
    con.commit()
    con.close()
    log.info(f"Unknown card {card_uid} at box {box_id} — logged")

# =============================================================
#  PACKET FORMAT
#  JSON over LoRa:
#  {
#    "box":     "BOX_01",
#    "faction": 2,
#    "uid":     "A1-B2-C3-D4",
#    "event":   "capture"|"rescan"|"lost"|"heartbeat"|"unknown",
#    "rssi":    -87,
#    "sig":     "hmac_hex"
#  }
# =============================================================

def verify_hmac(payload: dict) -> bool:
    """Verify packet signature. Box signs: box+faction+uid+event."""
    received_sig = payload.get('sig', '')
    msg = f"{payload.get('box')}{payload.get('faction')}{payload.get('uid')}{payload.get('event')}"
    expected = hmac.new(HMAC_SECRET, msg.encode(), hashlib.sha256).hexdigest()[:16]
    return hmac.compare_digest(received_sig, expected)

def handle_packet(raw: str):
    log.info(f"Raw packet: {raw}")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("Invalid JSON — ignoring packet")
        return

    box_id    = payload.get('box')
    faction_id = payload.get('faction')
    card_uid  = payload.get('uid')
    event     = payload.get('event')

    if not all([box_id, card_uid, event]):
        log.warning("Incomplete packet — ignoring")
        return

    # --- Signature check ---
    if not verify_hmac(payload):
        log.warning(f"HMAC failed for packet from {box_id} — possible spoofing")
        return

    # --- Heartbeat (no ownership change) ---
    if event == 'heartbeat':
        log.info(f"Heartbeat from {box_id}")
        return

    # --- Unknown / unregistered card ---
    if event == 'unknown':
        log_unknown_scan(box_id, card_uid)
        return

    # --- Verify card is registered ---
    registered_faction = is_card_registered(card_uid)
    if registered_faction is None:
        log.info(f"Unregistered card {card_uid} at {box_id}")
        log_unknown_scan(box_id, card_uid)
        return

    if registered_faction != faction_id:
        log.warning(f"Faction mismatch: card says {registered_faction}, packet says {faction_id}")
        return

    # --- Cooldown / rescan check ---
    if check_cooldown(box_id, card_uid):
        log.info(f"Cooldown active: card {card_uid} at box {box_id} — rescan penalty")
        log_event(box_id, faction_id, card_uid)
        return

    # --- Ownership change ---
    current_faction, started_at = get_current_owner(box_id)

    if current_faction == faction_id:
        log.info(f"Box {box_id} already owned by faction {faction_id} — no change")
        log_event(box_id, faction_id, card_uid)
        return

    # Close previous ownership, open new one
    if current_faction is not None:
        end_current_ownership(box_id)
        log.info(f"Box {box_id} lost by faction {current_faction}")

    start_ownership(box_id, faction_id)
    log_event(box_id, faction_id, card_uid)
    log.info(f"Box {box_id} captured by faction {faction_id} (card {card_uid})")

# =============================================================
#  LORA INIT — Waveshare SX1262 HAT
# =============================================================
def init_lora():
    lora = SX1262(spi_bus=0, clk=11, mosi=10, miso=9,
                  cs=8, irq=24, rst=18, gpio=5)

    lora.begin(
        freq        = FREQUENCY,
        bw          = BANDWIDTH,
        sf          = SF,
        cr          = CODING_RATE,
        syncWord    = 0x12,       # Private network — must match ESP32
        power       = 14,
        currentLimit = 60.0,
        preambleLength = 8,
        implicit    = False,
        implicitLen = 0xFF,
        crcOn       = True,
        txIq        = False,
        rxIq        = False,
        tcxoVoltage = 1.7,
        useRegulatorLDO = False,
        blocking    = True
    )
    return lora

# =============================================================
#  MAIN LOOP
# =============================================================
def main():
    log.info("=== CaptureBox LoRa Receiver starting ===")
    log.info(f"Frequency: {FREQUENCY} MHz  SF: {SF}  BW: {BANDWIDTH} kHz")

    lora = init_lora()
    log.info("LoRa HAT initialised — listening for packets")

    while True:
        try:
            data, rssi = lora.recv(timeout_ms=0)  # blocking
            if data:
                raw = bytes(data).decode('utf-8', errors='ignore').strip()
                handle_packet(raw)
        except Exception as e:
            log.error(f"Receive error: {e}")
            time.sleep(1)

if __name__ == '__main__':
    main()
