"""
CaptureBox v3 — LoRa Receiver + Command Sender
Handles extended heartbeat (comms_mode, wifi_rssi)
Sends queued Pi commands to boxes via LoRa on heartbeat
"""
import sys, os, json, time, hmac, hashlib, logging, sqlite3
from datetime import datetime

sys.path.insert(0, '/home/pi_game/capturebox')
sys.path.insert(0, '/home/pi_game')

from database import (
    init_db, get_card, register_card, get_current_owner,
    end_ownership, start_ownership, log_event, upsert_box,
    check_cooldown, get_setting, update_card_seen,
    get_pending_commands, ack_command, queue_command
)
from discord_notify import notify_discord

# =============================================================
#  CONFIG
# =============================================================
SERIAL_PORT  = '/dev/ttyS0'
FREQUENCY    = 868
ADDRESS      = 0
POWER        = 22
AIR_SPEED    = 2400
HMAC_SECRET  = b'changeme123'
LOG_PATH     = '/home/pi_game/capturebox/lora_receiver.log'
DB_PATH      = '/home/pi_game/capturebox/capturebox.db'

_box_seq = {}   # {box_id: last_seq}

# =============================================================
#  LOGGING
# =============================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()]
)
log = logging.getLogger(__name__)

# =============================================================
#  FACTION MAPPING
# =============================================================
FACTION_MAP = {'B':1,'R':2,'Y':3,'G':4,'N':0}
def faction_id(letter): return FACTION_MAP.get(str(letter).upper(), 0)

# =============================================================
#  HMAC VERIFY
# =============================================================
def verify_hmac(payload):
    received = payload.get('sig','')
    msg = f"{payload.get('b','')}{payload.get('e','')}{payload.get('f','N')}{payload.get('u','')}{payload.get('seq',0)}"
    expected = hmac.new(HMAC_SECRET, msg.encode(), hashlib.sha256).hexdigest()[:8]
    return hmac.compare_digest(received, expected)

# =============================================================
#  SEQUENCE CHECK
# =============================================================
def check_sequence(box_id, seq):
    last = _box_seq.get(box_id, seq-1)
    gap  = seq - last - 1
    if gap > 0:
        log.warning(f"Seq gap {box_id}: expected {last+1} got {seq} (missed {gap})")
        for missing in range(last+1, min(seq, last+5)):
            queue_command(box_id, 'rsd', {'seq': missing})
    _box_seq[box_id] = seq
    return gap

# =============================================================
#  BOX STATUS UPDATE (extended for v3)
# =============================================================
def update_box_status(box_id, faction, battery, rssi, firmware,
                      comms_mode=None, wifi_rssi=None):
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        INSERT INTO boxes (box_id, name, active, battery_pct, rssi,
                          firmware_ver, last_heartbeat, comms_mode, wifi_rssi)
        VALUES (?,?,1,?,?,?,datetime('now'),?,?)
        ON CONFLICT(box_id) DO UPDATE SET
            battery_pct    = excluded.battery_pct,
            rssi           = excluded.rssi,
            firmware_ver   = excluded.firmware_ver,
            last_heartbeat = excluded.last_heartbeat,
            comms_mode     = COALESCE(excluded.comms_mode, comms_mode),
            wifi_rssi      = COALESCE(excluded.wifi_rssi, wifi_rssi)
    """, (box_id, box_id, battery, rssi, firmware, comms_mode, wifi_rssi))
    con.commit()
    con.close()

# =============================================================
#  EVENT TRIM — keep last 2 scan events per box
# =============================================================
def trim_events(box_id):
    try:
        con = sqlite3.connect(DB_PATH)
        con.execute("""
            DELETE FROM events WHERE box_id=?
            AND event_type NOT IN ('heartbeat','admin_reset')
            AND id NOT IN (
                SELECT id FROM events WHERE box_id=?
                AND event_type NOT IN ('heartbeat','admin_reset')
                ORDER BY timestamp DESC LIMIT 2
            )
        """, (box_id, box_id))
        con.commit()
        con.close()
    except Exception as e:
        log.error(f"Trim error: {e}")

# =============================================================
#  BUILD SETTINGS PAYLOAD for Pi→Box cfg command
# =============================================================
def build_cfg_payload():
    return {
        'vol':      int(get_setting('volume_default',   20)),
        'sil_f':    int(get_setting('silent_from',      22)),
        'sil_u':    int(get_setting('silent_until',      8)),
        'bri_a':    int(get_setting('bri_active',       80)),
        'bri_i':    int(get_setting('bri_idle',         20)),
        'bri_s':    int(get_setting('bri_sleep',         5)),
        'dim_i':    int(get_setting('dim_idle_sec',    120)),
        'dim_s':    int(get_setting('dim_sleep_sec',   600)),
        'lora_pwr': int(get_setting('lora_tx_power',   14)),
        'hb':       int(get_setting('heartbeat_sec',   30)),
        'rssi_g':   int(get_setting('rssi_good',       -65)),
        'rssi_p':   int(get_setting('rssi_poor',       -80)),
        'wifi_m':   int(get_setting('wifi_mode',        0)),
        'game':     'on' if get_setting('game_status')=='active' else 'off',
    }

# =============================================================
#  SEND QUEUED COMMANDS TO BOX via LoRa
# =============================================================
def send_pending_lora_commands(node, box_id):
    """Called on heartbeat — flush pending commands to box via LoRa."""
    cmds = get_pending_commands(box_id) + get_pending_commands('ALL')
    if not cmds:
        return

    for cmd in cmds:
        try:
            payload = json.loads(cmd['payload'] or '{}')
        except:
            payload = {}

        packet = {'b': box_id, 'c': cmd['command'], **payload}
        pkt_str = json.dumps(packet)

        # Build sx126x header + payload
        # dest=box_addr, src=pi_addr=0
        dest_freq_offset = 18  # 868-850
        header = bytes([0x00, 0x00, dest_freq_offset, 0x00, 0x00, dest_freq_offset])
        node.send(header + pkt_str.encode())

        ack_command(cmd['id'])
        log.info(f"LoRa CMD → {box_id}: {cmd['command']}")

# =============================================================
#  PACKET HANDLER
# =============================================================
def handle_packet(raw_bytes, node):
    try:
        payload_bytes = raw_bytes[3:-1]
        rssi_val = -(256 - raw_bytes[-1]) if len(raw_bytes) > 4 else None
        raw_str  = payload_bytes.decode('utf-8', errors='ignore').strip()
        payload  = json.loads(raw_str)
    except Exception as e:
        log.warning(f"Parse error: {e}"); return

    box_id   = payload.get('b')
    event    = payload.get('e','')
    f_letter = payload.get('f','N')
    fid      = faction_id(f_letter)
    uid      = payload.get('u','')
    battery  = payload.get('bat')
    seq      = payload.get('seq', 0)
    firmware = payload.get('fw','')
    # v3 extended fields
    comms_mode = payload.get('cm')   # 'w', 'l', or 'lf'
    wifi_rssi  = payload.get('wr')   # WiFi RSSI when in WiFi mode

    if not box_id:
        log.warning("No box_id"); return

    upsert_box(box_id)
    update_box_status(box_id, fid, battery, rssi_val, firmware,
                      comms_mode, wifi_rssi)

    # Heartbeat — update status and flush pending commands
    if event == 'hb':
        cm_label = {'w':'WiFi','l':'LoRa','lf':'LoRa(forced)'}.get(comms_mode,'?')
        log.info(f"HB {box_id} f={f_letter} bat={battery}% rssi={rssi_val} comms={cm_label}")
        send_pending_lora_commands(node, box_id)
        return

    # Sequence check
    check_sequence(box_id, seq)

    # HMAC verify
    if not verify_hmac(payload):
        log.warning(f"HMAC fail {box_id}"); return

    # Unknown / bank card
    if event in ('unk','bnk'):
        log_event(box_id, None, uid or 'unknown', event, rssi=rssi_val)
        trim_events(box_id)
        return

    # Card registration
    if event == 'reg':
        register_card(uid, fid, registered_box=box_id, card_type='ntag')
        log_event(box_id, fid, uid, 'card_registered', rssi=rssi_val)
        trim_events(box_id)
        # Send current settings back as cfg command
        queue_command(box_id, 'cfg', build_cfg_payload())
        log.info(f"Registered {uid} → faction {fid} via {box_id}")
        return

    # Verify card
    if uid:
        card = get_card(uid)
        if not card:
            log_event(box_id, None, uid, 'unknown', rssi=rssi_val)
            trim_events(box_id); return
        if card['blocked']:
            log_event(box_id, None, uid, 'blocked_card', rssi=rssi_val)
            trim_events(box_id); return
        update_card_seen(uid, box_id)

    # Rescan
    if event == 'rsn':
        log_event(box_id, fid, uid, 'rescan', rssi=rssi_val)
        trim_events(box_id); return

    # Capture
    if event == 'cap':
        cur, _ = get_current_owner(box_id)
        if cur and cur != fid:
            end_ownership(box_id)
            log_event(box_id, cur, uid, 'lost', f'→ {f_letter}', rssi=rssi_val)
            notify_discord(f'📦 **{box_id}** → {f_letter} (from {cur})', event='capture')
        if cur != fid:
            start_ownership(box_id, fid)
        log_event(box_id, fid, uid, 'capture', rssi=rssi_val)
        trim_events(box_id)
        log.info(f"{box_id} captured by {f_letter}")
        return

    # Lost / decay expired
    if event == 'lst':
        cur, _ = get_current_owner(box_id)
        if cur:
            end_ownership(box_id)
            log_event(box_id, cur, uid or '', 'lost', 'decay expired', rssi=rssi_val)
            trim_events(box_id)
            notify_discord(f'📦 **{box_id}** neutral (decay)', event='lost')
        return

    log.info(f"Unhandled event '{event}' from {box_id}")

# =============================================================
#  MAIN
# =============================================================
def main():
    log.info("=== CaptureBox LoRa Receiver v3 ===")
    init_db()

    try:
        import sx126x
    except ImportError:
        log.error("sx126x.py not found at /home/pi_game/capturebox/sx126x.py")
        sys.exit(1)

    node = sx126x.sx126x(
        serial_num=SERIAL_PORT, freq=FREQUENCY,
        addr=ADDRESS, power=POWER, rssi=True,
        air_speed=AIR_SPEED, relay=False
    )
    log.info(f"LoRa ready — {FREQUENCY}MHz addr={ADDRESS}")

    while True:
        try:
            if node.ser.inWaiting() > 0:
                time.sleep(0.4)
                raw = node.ser.read(node.ser.inWaiting())
                if raw:
                    handle_packet(raw, node)
            time.sleep(0.1)
        except KeyboardInterrupt:
            log.info("Stopped"); break
        except Exception as e:
            log.error(f"Error: {e}"); time.sleep(1)

if __name__ == '__main__':
    main()
