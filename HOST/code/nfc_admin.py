"""
CaptureBox — NFC Admin Tool (RC522 on Pi)
Run standalone: python nfc_admin.py
Or called via web UI through /nfc route
"""

import time
import sys
import json

# Guard import so app.py can import functions without RPi hardware
try:
    import mfrc522
    HAS_NFC = True
except ImportError:
    HAS_NFC = False

from database import (
    get_card, register_card, reset_card, block_card,
    get_factions, get_blocked_factions, init_db
)

FACTIONS = {1: 'Blue (Foundation)', 2: 'Red (Opposition)',
            3: 'Yellow (Aliens)',   4: 'Green (Rebellion)'}

BANNER = """
╔═══════════════════════════════════════╗
║      CaptureBox NFC Admin Tool        ║
╚═══════════════════════════════════════╝
"""

# =============================================================
#  CORE NFC FUNCTIONS (used by both CLI and web socket)
# =============================================================
def read_card_uid(reader, timeout=10):
    """Scan for a card, return UID string or None on timeout."""
    start = time.time()
    while time.time() - start < timeout:
        uid, _ = reader.scan()
        if uid:
            return '-'.join(str(x) for x in uid)
        time.sleep(0.2)
    return None

def detect_card_type(reader):
    """
    Try to distinguish NTAG/MIFARE from bank cards.
    Bank cards (ISO 14443-4) respond to RATS command.
    Returns: 'ntag', 'mifare', 'bankcard', 'unknown'
    """
    try:
        uid, card_type_byte = reader.scan()
        if card_type_byte is None:
            return 'unknown'
        # SAK byte 0x20 = ISO 14443-4 compliant = likely bank card
        if card_type_byte == 0x20:
            return 'bankcard'
        # SAK 0x00 = MIFARE Ultralight / NTAG
        if card_type_byte == 0x00:
            return 'ntag'
        # SAK 0x08 = MIFARE Classic 1K
        if card_type_byte == 0x08:
            return 'mifare'
        return 'unknown'
    except Exception:
        return 'unknown'

# =============================================================
#  CLI INTERFACE
# =============================================================
def print_card_info(uid):
    card = get_card(uid)
    print(f"\n  UID      : {uid}")
    if card:
        faction = FACTIONS.get(card['faction_id'], 'Unknown')
        print(f"  Faction  : {faction}")
        print(f"  Player   : {card['player_name'] or '—'}")
        print(f"  Type     : {card['card_type']}")
        print(f"  Blocked  : {'YES' % card['blocked'] if card['blocked'] else 'No'}")
        print(f"  Registered: {card['registered_at']}")
        print(f"  Last seen : {card['last_seen_at'] or 'Never'}")
        print(f"  Scans     : {card['scan_count']}")
    else:
        print("  Status   : Not registered (blank)")

def menu_register(reader, uid):
    print("\n  Available factions:")
    blocked = get_blocked_factions()
    available = []
    for fid, fname in FACTIONS.items():
        status = ' [FULL]' if fid in blocked else ''
        print(f"    {fid}) {fname}{status}")
        if fid not in blocked:
            available.append(fid)

    if not available:
        print("\n  ⚠ All factions are full!")
        return

    while True:
        choice = input("\n  Select faction (or 0 to cancel): ").strip()
        if choice == '0':
            return
        try:
            fid = int(choice)
            if fid in FACTIONS:
                name = input("  Player name (optional, press Enter to skip): ").strip()
                register_card(uid, fid, player_name=name or None, card_type='ntag')
                print(f"\n  ✓ Card registered to {FACTIONS[fid]}")
                return
        except ValueError:
            pass
        print("  Invalid choice, try again.")

def main():
    print(BANNER)
    init_db()

    if not HAS_NFC:
        print("  ⚠  mfrc522 library not found.")
        print("  Install: pip install mfrc522")
        print("  Running in demo mode — no hardware scanning.\n")
        uid = input("  Enter UID manually to test (or q to quit): ").strip()
        if uid.lower() == 'q':
            return
    else:
        reader = mfrc522.SimpleMFRC522()

    while True:
        print("""
  ┌─────────────────────────────┐
  │  1) Scan & show card info   │
  │  2) Register card           │
  │  3) Reset card (blank)      │
  │  4) Block card              │
  │  5) Unblock card            │
  │  6) Show all factions       │
  │  q) Quit                    │
  └─────────────────────────────┘""")

        choice = input("  Choice: ").strip().lower()

        if choice == 'q':
            print("\n  Goodbye.\n")
            break

        if choice == '6':
            print()
            for row in get_factions():
                print(f"  Faction {row['id']}: {row['name']} ({row['color_name']})")
            continue

        if choice not in ('1','2','3','4','5'):
            print("  Invalid choice.")
            continue

        if HAS_NFC:
            print("\n  Hold card near reader... (10 sec timeout)")
            uid = read_card_uid(reader)
            if not uid:
                print("  No card detected.")
                continue
        else:
            uid = input("  Enter UID: ").strip()

        if choice == '1':
            print_card_info(uid)

        elif choice == '2':
            print_card_info(uid)
            menu_register(reader if HAS_NFC else None, uid)

        elif choice == '3':
            card = get_card(uid)
            if not card:
                print("  Card not registered — nothing to reset.")
                continue
            confirm = input(f"  Reset card {uid}? (y/N): ").strip().lower()
            if confirm == 'y':
                reset_card(uid)
                print("  ✓ Card reset.")

        elif choice == '4':
            block_card(uid, True)
            print(f"  ✓ Card {uid} blocked.")

        elif choice == '5':
            block_card(uid, False)
            print(f"  ✓ Card {uid} unblocked.")

if __name__ == '__main__':
    main()
