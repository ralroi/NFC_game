# CaptureBox — LoRa Receiver Setup
# Waveshare SX1262 HAT on Raspberry Pi 4B

# =============================================================
# 1. ENABLE SPI (if not already done)
# =============================================================
sudo raspi-config
# Interface Options → SPI → Enable

# =============================================================
# 2. INSTALL WAVESHARE SX1262 LIBRARY
# =============================================================
cd /home/pi
git clone https://github.com/waveshare/sx1262-lorahat
cd sx1262-lorahat/python
# No pip install needed — lora_receiver.py adds path directly

# Install dependencies
source /home/pi/capturebox/venv/bin/activate
pip install RPi.GPIO spidev

# =============================================================
# 3. INSTALL LORA RECEIVER
# =============================================================
cp lora_receiver.py /home/pi/capturebox/

# =============================================================
# 4. SET YOUR HMAC SECRET
# =============================================================
# Edit lora_receiver.py line:
#   HMAC_SECRET = b'changeme123'
# Change to something unique, e.g.:
#   HMAC_SECRET = b'mygame2024secret'
# Use the EXACT same string in your ESP32 firmware

# =============================================================
# 5. INSTALL SYSTEMD SERVICE
# =============================================================
sudo cp capturebox-lora.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable capturebox-lora
sudo systemctl start capturebox-lora

# =============================================================
# 6. CHECK STATUS & LOGS
# =============================================================
sudo systemctl status capturebox-lora
journalctl -u capturebox-lora -f       # live log tail

# Or check the log file directly:
tail -f /home/pi/capturebox/lora_receiver.log

# =============================================================
# 7. VERIFY BOTH SERVICES ARE RUNNING
# =============================================================
sudo systemctl status capturebox        # Flask web app
sudo systemctl status capturebox-lora   # LoRa receiver

# =============================================================
# PACKET FORMAT (ESP32 must send this JSON over LoRa)
# =============================================================
# {
#   "box":     "BOX_01",
#   "faction": 2,
#   "uid":     "A1-B2-C3-D4",
#   "event":   "capture",
#   "sig":     "hmac_first16chars"
# }
#
# Events:
#   capture   — player successfully held box long enough
#   rescan    — same card scanned again too soon
#   lost      — box ownership changed away from this faction
#   heartbeat — periodic alive ping (no DB change)
#   unknown   — unregistered or bank card scanned
#
# HMAC signing (must match lora_receiver.py verify_hmac):
#   msg = box_id + faction_id + uid + event
#   sig = HMAC-SHA256(secret, msg)[0:16]
