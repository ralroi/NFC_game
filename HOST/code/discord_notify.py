"""
CaptureBox — Discord Notifications (optional)
Set discord_enabled=1 and discord_webhook in settings to activate.
"""

import requests
import logging
from database import get_setting

log = logging.getLogger(__name__)

def notify_discord(message: str, event: str = 'general'):
    enabled = get_setting('discord_enabled', '0')
    if enabled != '1':
        return

    # Check if this event type is enabled
    allowed = get_setting('discord_events', 'capture,lost,game_start,game_end')
    if event != 'general' and event not in allowed.split(','):
        return

    webhook = get_setting('discord_webhook', '')
    if not webhook:
        return

    try:
        requests.post(webhook, json={'content': message}, timeout=5)
    except Exception as e:
        log.warning(f'Discord notify failed: {e}')
