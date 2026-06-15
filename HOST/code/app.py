"""
CaptureBox — app.py
Complete Flask web application — all routes
"""
from flask import Flask, render_template, jsonify, request, redirect, url_for, flash
import json
import sqlite3
from datetime import datetime
from database import (
    init_db, get_db, get_setting, set_setting,
    get_factions, get_faction_player_counts, get_blocked_factions,
    get_all_boxes, get_box, upsert_box, mark_box_stolen,
    get_card, get_all_cards, register_card, reset_card, block_card,
    get_faction_scores, get_player_leaderboard, get_box_usage_stats,
    get_recent_events, log_event, queue_command, ack_command,
    get_current_owner, end_ownership, start_ownership,
    update_box_heartbeat, update_card_seen, check_cooldown,
    trim_box_events, get_pending_commands
)
from discord_notify import notify_discord

app = Flask(__name__)
app.secret_key = 'capturebox-secret-change-me'

# =============================================================
#  HELPERS
# =============================================================
def game_status():
    return get_setting('game_status', 'stopped')

def build_cfg_payload():
    """Compact settings payload pushed to boxes."""
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
        'game':     'on' if game_status() == 'active' else 'off',
    }

@app.context_processor
def inject_globals():
    return {
        'game_status': game_status(),
        'factions': get_factions(),
        'now': datetime.utcnow().strftime('%H:%M:%S')
    }

# =============================================================
#  DASHBOARD
# =============================================================
@app.route('/')
def dashboard():
    return render_template('dashboard.html',
        scores=get_faction_scores(),
        boxes=get_all_boxes(),
        events=get_recent_events(30),
        players=get_faction_player_counts())

# =============================================================
#  LEADERBOARD
# =============================================================
@app.route('/leaderboard')
def leaderboard():
    return render_template('leaderboard.html',
        scores=get_faction_scores(),
        players=get_player_leaderboard(),
        usage=get_box_usage_stats())

# =============================================================
#  BOX MANAGEMENT
# =============================================================
@app.route('/boxes')
def boxes():
    return render_template('boxes.html', boxes=get_all_boxes())

@app.route('/boxes/add', methods=['GET','POST'])
def box_add():
    if request.method == 'POST':
        box_id = request.form.get('box_id','').strip().upper()
        if not box_id:
            flash('Box ID is required','error')
            return redirect(url_for('box_add'))
        upsert_box(box_id,
            name=request.form.get('name','').strip(),
            location_desc=request.form.get('location_desc','').strip(),
            lat=request.form.get('lat') or None,
            lng=request.form.get('lng') or None,
            notes=request.form.get('notes','').strip())
        flash(f'Box {box_id} added','success')
        return redirect(url_for('boxes'))
    return render_template('box_form.html', box=None, title='Add Box')

@app.route('/boxes/<box_id>/edit', methods=['GET','POST'])
def box_edit(box_id):
    box = get_box(box_id)
    if not box:
        flash('Box not found','error')
        return redirect(url_for('boxes'))
    if request.method == 'POST':
        upsert_box(box_id,
            name=request.form.get('name','').strip(),
            location_desc=request.form.get('location_desc','').strip(),
            lat=request.form.get('lat') or None,
            lng=request.form.get('lng') or None,
            active=int(request.form.get('active',1)),
            notes=request.form.get('notes','').strip())
        flash(f'Box {box_id} updated','success')
        return redirect(url_for('boxes'))
    return render_template('box_form.html', box=box, title=f'Edit {box_id}')

@app.route('/boxes/<box_id>/command', methods=['POST'])
def box_command(box_id):
    cmd = request.form.get('command')
    payload = {}
    if cmd == 'set_volume':
        payload = {'vol': int(request.form.get('volume',20))}
    elif cmd == 'set_brightness':
        payload = {'bri_a': int(request.form.get('brightness',80))}
    elif cmd == 'activate':
        upsert_box(box_id, active=1)
    elif cmd == 'deactivate':
        upsert_box(box_id, active=0)
    elif cmd == 'mark_stolen':
        mark_box_stolen(box_id, True)
    elif cmd == 'clear_stolen':
        mark_box_stolen(box_id, False)
    elif cmd == 'reset_ownership':
        end_ownership(box_id)
        log_event(box_id, None, None, 'admin_reset', 'Reset by admin')
    queue_command(box_id, cmd, payload if payload else None)
    flash(f'Command "{cmd}" queued for {box_id}','success')
    return redirect(url_for('boxes'))

@app.route('/boxes/<box_id>/events')
def box_events(box_id):
    return render_template('box_events.html',
        box=get_box(box_id),
        events=get_recent_events(100, box_id=box_id))

# =============================================================
#  POWER MANAGEMENT
# =============================================================
@app.route('/boxes/<box_id>/power', methods=['POST'])
def box_power_settings(box_id):
    payload = {
        'bri_a':    int(request.form.get('bri_active',   80)),
        'bri_i':    int(request.form.get('bri_idle',     20)),
        'bri_s':    int(request.form.get('bri_sleep',      5)),
        'dim_i':    int(request.form.get('dim_idle_sec', 120)),
        'dim_s':    int(request.form.get('dim_sleep_sec',600)),
        'lora_pwr': int(request.form.get('lora_power',   14)),
        'hb':       int(request.form.get('heartbeat_sec', 30)),
        'wifi_m':   int(request.form.get('wifi_mode',      0)),
    }
    queue_command(box_id, 'cfg', payload)
    flash(f'Power settings queued for {box_id}','success')
    return redirect(url_for('boxes'))

@app.route('/boxes/<box_id>/wifi_cred', methods=['POST'])
def box_wifi_credentials(box_id):
    ssid     = request.form.get('ssid','').strip()
    password = request.form.get('password','').strip()
    pi_ip    = request.form.get('pi_ip','').strip()
    if not ssid and not pi_ip:
        flash('Provide at least SSID or Pi IP','error')
        return redirect(url_for('boxes'))
    payload = {}
    if ssid:     payload['ssid'] = ssid
    if password: payload['pass'] = password
    if pi_ip:    payload['ip']   = pi_ip
    queue_command(box_id, 'wcred', payload)
    flash(f'WiFi credentials queued for {box_id} — sent via LoRa on next heartbeat','success')
    return redirect(url_for('boxes'))

@app.route('/boxes/<box_id>/wifi_mode', methods=['POST'])
def box_wifi_mode(box_id):
    mode = int(request.form.get('mode', 0))
    queue_command(box_id, 'wmode', {'m': mode})
    labels = {0:'Auto',1:'WiFi forced',2:'LoRa forced'}
    flash(f'{box_id} → {labels.get(mode,"?")} mode queued','success')
    return redirect(url_for('boxes'))

@app.route('/boxes/broadcast_power', methods=['POST'])
def broadcast_power():
    payload = {
        'bri_a':    int(request.form.get('bri_active',   80)),
        'bri_i':    int(request.form.get('bri_idle',     20)),
        'bri_s':    int(request.form.get('bri_sleep',      5)),
        'dim_i':    int(request.form.get('dim_idle_sec', 120)),
        'dim_s':    int(request.form.get('dim_sleep_sec',600)),
        'lora_pwr': int(request.form.get('lora_power',   14)),
        'hb':       int(request.form.get('heartbeat_sec', 30)),
        'wifi_m':   int(request.form.get('wifi_mode',      0)),
        'vol':      int(request.form.get('volume',        20)),
    }
    queue_command('ALL','cfg',payload)
    for k,v in [('bri_active',payload['bri_a']),('bri_idle',payload['bri_i']),
                ('bri_sleep',payload['bri_s']),('dim_idle_sec',payload['dim_i']),
                ('dim_sleep_sec',payload['dim_s']),('lora_tx_power',payload['lora_pwr']),
                ('heartbeat_sec',payload['hb']),('wifi_mode',payload['wifi_m']),
                ('volume_default',payload['vol'])]:
        set_setting(k,str(v))
    flash('Power settings broadcast to all boxes','success')
    return redirect(url_for('settings'))

# =============================================================
#  CARD MANAGEMENT
# =============================================================
@app.route('/cards')
def cards():
    return render_template('cards.html',
        cards=get_all_cards(), factions=get_factions())

@app.route('/cards/register', methods=['POST'])
def card_register():
    uid     = request.form.get('uid','').strip()
    faction = request.form.get('faction_id')
    name    = request.form.get('player_name','').strip()
    if not uid or not faction:
        flash('UID and faction are required','error')
        return redirect(url_for('cards'))
    register_card(uid, int(faction), player_name=name or None, card_type='manual')
    flash(f'Card {uid} registered','success')
    return redirect(url_for('cards'))

@app.route('/cards/<uid>/reset', methods=['POST'])
def card_reset(uid):
    reset_card(uid)
    flash(f'Card {uid} reset','success')
    return redirect(url_for('cards'))

@app.route('/cards/<uid>/block', methods=['POST'])
def card_block(uid):
    block_card(uid, True)
    flash(f'Card {uid} blocked','warning')
    return redirect(url_for('cards'))

@app.route('/cards/<uid>/unblock', methods=['POST'])
def card_unblock(uid):
    block_card(uid, False)
    flash(f'Card {uid} unblocked','success')
    return redirect(url_for('cards'))

# =============================================================
#  NFC ADMIN
# =============================================================
@app.route('/nfc')
def nfc_admin():
    return render_template('nfc_admin.html', factions=get_factions())

_nfc_reader = None

def get_nfc_reader():
    global _nfc_reader
    if _nfc_reader is None:
        try:
            import RPi.GPIO as GPIO
            GPIO.setwarnings(False)
            import mfrc522
            _nfc_reader = mfrc522.SimpleMFRC522()
        except Exception as e:
            return None, str(e)
    return _nfc_reader, None

@app.route('/api/nfc/scan')
def api_nfc_scan():
    try:
        reader, err = get_nfc_reader()
        if err:
            return jsonify({'error': err}), 500
        uid, text = reader.read_no_block()
        if not uid:
            return jsonify({'uid': None})
        uid_str   = str(uid)
        card_type = 'ntag' if uid > 0xFFFFFFFFFF else 'mifare'
        card = get_card(uid_str)
        if card:
            faction = next((f for f in get_factions() if f['id']==card['faction_id']),None)
            return jsonify({
                'uid': uid_str, 'card_type': card_type, 'registered': True,
                'faction_id': card['faction_id'],
                'faction_name': faction['name'] if faction else '?',
                'color_hex': faction['color_hex'] if faction else '#888',
                'player_name': card['player_name'],
                'scan_count': card['scan_count'],
                'blocked': bool(card['blocked']),
            })
        return jsonify({'uid': uid_str, 'card_type': card_type, 'registered': False})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/nfc/status')
def api_nfc_status():
    try:
        import mfrc522
        reader, err = get_nfc_reader()
        return jsonify({'available': err is None, 'error': err})
    except ImportError:
        return jsonify({'available': False, 'error': 'mfrc522 not installed'})

# =============================================================
#  GAME CONTROL
# =============================================================
@app.route('/game')
def game_control():
    with get_db() as con:
        scenarios = [dict(r) for r in
            con.execute("SELECT * FROM scenarios ORDER BY id").fetchall()]
        games = [dict(r) for r in con.execute("""
            SELECT g.*, s.name as scenario_name FROM games g
            LEFT JOIN scenarios s ON g.scenario_id=s.id
            ORDER BY g.id DESC LIMIT 10
        """).fetchall()]
    return render_template('game_control.html',
        scenarios=scenarios, games=games, current_status=game_status())

@app.route('/game/start', methods=['POST'])
def game_start():
    scenario_id = int(request.form.get('scenario_id',1))
    game_name   = request.form.get('game_name',
                  f'Game {datetime.utcnow().strftime("%Y%m%d")}')
    with get_db() as con:
        con.execute("""
            INSERT INTO games (scenario_id,name,started_at,status)
            VALUES (?,?,datetime('now'),'active')
        """, (scenario_id, game_name))
    set_setting('game_status','active')
    cfg = build_cfg_payload()
    cfg['game'] = 'on'
    queue_command('ALL','cfg',cfg)
    queue_command('ALL','gon',{})
    notify_discord(f'🎮 Game started: **{game_name}**')
    flash('Game started!','success')
    return redirect(url_for('game_control'))

@app.route('/game/stop', methods=['POST'])
def game_stop():
    with get_db() as con:
        con.execute("""
            UPDATE games SET ended_at=datetime('now'),status='finished'
            WHERE status='active'
        """)
    set_setting('game_status','stopped')
    queue_command('ALL','goff',{})
    scores = get_faction_scores()
    winner = scores[0]['name'] if scores else 'Unknown'
    notify_discord(f'🏁 Game ended! Winner: **{winner}**')
    flash('Game stopped','warning')
    return redirect(url_for('game_control'))

@app.route('/game/pause', methods=['POST'])
def game_pause():
    set_setting('game_status','paused')
    queue_command('ALL','gpause',{})
    flash('Game paused','warning')
    return redirect(url_for('game_control'))

# =============================================================
#  SETTINGS
# =============================================================
@app.route('/settings', methods=['GET','POST'])
def settings():
    if request.method == 'POST':
        for key in ['volume_default','silent_from','silent_until',
                    'bri_active','bri_idle','bri_sleep',
                    'dim_idle_sec','dim_sleep_sec',
                    'lora_tx_power','heartbeat_sec',
                    'rssi_good','rssi_poor','wifi_mode',
                    'discord_enabled','discord_webhook','discord_events']:
            val = request.form.get(key)
            if val is not None:
                set_setting(key, val)
        queue_command('ALL','cfg',build_cfg_payload())
        flash('Settings saved and pushed to boxes','success')
        return redirect(url_for('settings'))

    s = {k: get_setting(k, d) for k,d in [
        ('volume_default','20'),('silent_from','22'),('silent_until','8'),
        ('bri_active','80'),('bri_idle','20'),('bri_sleep','5'),
        ('dim_idle_sec','120'),('dim_sleep_sec','600'),
        ('lora_tx_power','14'),('heartbeat_sec','30'),
        ('rssi_good','-65'),('rssi_poor','-80'),('wifi_mode','0'),
        ('discord_enabled','0'),('discord_webhook',''),
        ('discord_events','capture,lost,game_start,game_end'),
    ]}
    return render_template('settings.html', s=s)

# =============================================================
#  USAGE REPORT
# =============================================================
@app.route('/usage')
def usage():
    return render_template('usage.html',
        stats=get_box_usage_stats(),
        events=get_recent_events(200))

# =============================================================
#  REST API (for boxes)
# =============================================================
@app.route('/api/v1/checkin', methods=['POST'])
def api_checkin():
    data       = request.get_json(force=True)
    box_id     = data.get('b') or data.get('box')
    card_uid   = data.get('u') or data.get('uid','')
    f_letter   = data.get('f','N')
    event_type = data.get('e') or data.get('event','scan')
    rssi       = data.get('rssi')
    battery    = data.get('bat') or data.get('battery')
    comms_mode = data.get('cm')
    wifi_rssi  = data.get('wr')

    if not box_id:
        return jsonify({'error':'missing box'}),400

    if not get_box(box_id):
        upsert_box(box_id)

    # Map faction letter to ID
    faction_map = {'B':1,'R':2,'Y':3,'G':4,'N':0}
    faction_id  = faction_map.get(str(f_letter).upper(), 0)

    update_box_heartbeat(box_id,
        battery_pct=battery, rssi=rssi,
        comms_mode=comms_mode, wifi_rssi=wifi_rssi)

    response = {
        'status': 'ok',
        'game':   game_status(),
        'blk':    [['B','R','Y','G'][i-1] for i in get_blocked_factions()],
        'cfg':    build_cfg_payload(),
    }

    if event_type in ('hb','heartbeat') or not card_uid:
        # Send any pending commands
        cmds = get_pending_commands(box_id) + get_pending_commands('ALL')
        response['commands'] = [dict(c) for c in cmds]
        for c in cmds:
            from database import ack_command
            ack_command(c['id'])
        return jsonify(response)

    if event_type in ('unk','bnk','unknown','bankcard'):
        log_event(box_id, None, card_uid, event_type, rssi=rssi)
        return jsonify(response)

    card = get_card(card_uid)
    if not card:
        response['action'] = 'register'
        return jsonify(response)

    if card['blocked']:
        response['action'] = 'blocked'
        log_event(box_id, None, card_uid, 'blocked_card', rssi=rssi)
        return jsonify(response)

    update_card_seen(card_uid, box_id)

    cooldown_min = int(get_setting('cooldown_minutes',10))
    if check_cooldown(box_id, card_uid, cooldown_min):
        log_event(box_id, faction_id, card_uid, 'rescan', rssi=rssi)
        trim_box_events(box_id)
        response['action'] = 'rescan_penalty'
        return jsonify(response)

    current_faction, _ = get_current_owner(box_id)
    if current_faction != faction_id:
        if current_faction:
            end_ownership(box_id)
            log_event(box_id, current_faction, card_uid, 'lost',
                      f'→ faction {faction_id}', rssi=rssi)
            notify_discord(
                f'📦 Box **{box_id}** → faction {faction_id}',
                event='capture')
        start_ownership(box_id, faction_id)
        log_event(box_id, faction_id, card_uid, 'capture', rssi=rssi)
        trim_box_events(box_id)
        response['action'] = 'captured'
    else:
        log_event(box_id, faction_id, card_uid, 'rescan', rssi=rssi)
        trim_box_events(box_id)
        response['action'] = 'already_owned'

    return jsonify(response)

@app.route('/api/v1/register_card', methods=['POST'])
def api_register_card():
    data    = request.get_json(force=True)
    uid     = data.get('u') or data.get('uid')
    faction = data.get('f') or data.get('faction_id')
    box_id  = data.get('b') or data.get('box')
    if not uid or not faction:
        return jsonify({'error':'missing uid or faction'}),400
    # Convert letter to ID if needed
    if isinstance(faction, str) and not faction.isdigit():
        faction = {'B':1,'R':2,'Y':3,'G':4}.get(faction.upper(), 0)
    register_card(uid, int(faction), registered_box=box_id, card_type='ntag')
    log_event(box_id, faction, uid, 'card_registered')
    return jsonify({'status':'ok','uid':uid,'faction_id':faction})

@app.route('/api/v1/status')
def api_status():
    return jsonify({
        'game':   game_status(),
        'scores': get_faction_scores(),
        'boxes':  get_all_boxes(),
        'blk':    [['B','R','Y','G'][i-1] for i in get_blocked_factions()],
        'cfg':    build_cfg_payload(),
    })

@app.route('/api/v1/boxes/<box_id>/commands')
def api_box_commands(box_id):
    cmds = get_pending_commands(box_id) + get_pending_commands('ALL')
    with get_db() as con:
        for c in cmds:
            con.execute("""
                UPDATE commands SET status='sent', sent_at=datetime('now')
                WHERE id=?
            """, (c['id'],))
    return jsonify({'commands': [dict(c) for c in cmds]})

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=False)
