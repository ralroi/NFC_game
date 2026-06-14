# CaptureBox — Raspberry Pi Setup Guide 

## What this is

CaptureBox is a real-world territory capture game. Physical boxes are placed around a game area. Players scan NFC cards at boxes to claim them for their faction. The faction that holds boxes the longest wins. This Raspberry Pi runs the game server, dashboard, NFC card admin, and LoRa radio receiver.
Beside the Pi/host, you need to build boxes as well where the card can be scanned. Please check NFC_game_box.
---

## Hardware required

| Item | Notes |
|---|---|
| Raspberry Pi 4B | Any RAM version |
| USB SSD (120GB+) | Much more reliable than SD card |
| MicroSD (8GB+) | Temporary — only for initial setup |
| USB-C power supply (5V 3A) | Official Pi supply recommended |
| Waveshare SX1262 868M LoRa HAT | Must be 868MHz for Europe |
| 40-pin GPIO stacking header | Allows RC522 wires above the HAT |
| RC522 NFC reader module | For card admin station |
| DS3231 RTC module | With CR2032 battery — keeps time when off |
| 868MHz SMA antenna | Usually included with HAT |
| Jumper wires (female-female) | For RC522 wiring |

---

## Step 1 — Install Raspberry Pi OS

1. Download **Raspberry Pi Imager** from raspberrypi.com/software
2. Insert your microSD card into your computer
3. In Imager: Choose OS → **Raspberry Pi OS (64-bit, Desktop)**
4. Click the settings cog (⚙) and set:
   - Hostname: `capturebox`
   - Username: `pi_game` ← **must be exactly this**
   - Password: choose something you will remember
   - WiFi: enter your network name and password
   - Enable SSH: yes
5. Flash to microSD, insert into Pi, power on

---

## Step 2 — Boot from SSD (recommended)

1. Connect SSD to a blue USB 3 port on the Pi
2. Open a terminal and run:
```bash
sudo raspi-config
```
3. Go to **Advanced Options → Boot Order → USB Boot**
4. Open **Raspberry Pi Imager** from within the Pi desktop
5. Flash Raspberry Pi OS (64-bit, Desktop) to the SSD
6. Shut down, remove microSD, reboot from SSD

---

## Step 3 — Enable hardware interfaces

```bash
sudo raspi-config
```

Enable under **Interface Options**:
- SPI ← for RC522 NFC reader
- I2C ← for DS3231 clock
- SSH ← for remote access

Under **Interface Options → Serial Port**:
- Login shell over serial: **No**
- Serial hardware enabled: **Yes**
  ← needed for LoRa HAT on /dev/ttyS0

Reboot after changes.

---

## Step 4 — Wire the hardware

### Fit the LoRa HAT
1. Press the stacking header onto the Pi GPIO pins
2. Press the LoRa HAT onto the stacking header
3. Screw the antenna onto the SMA connector (gently)

> ⚠ Never power the LoRa HAT without the antenna — it can damage the radio chip.

### Wire the RC522 NFC reader

| RC522 | Pi Pin | Function |
|---|---|---|
| 3.3V | Pin 1 | Power |
| GND | Pin 6 | Ground |
| MOSI | Pin 19 | SPI MOSI |
| MISO | Pin 21 | SPI MISO |
| SCK | Pin 23 | SPI Clock |
| SDA | Pin 24 | SPI CS0 |
| RST | Pin 22 | GPIO 25 |
| IRQ | — | Not connected |

> ⚠ RC522 is 3.3V only. Connecting to 5V destroys it.

### Wire the DS3231 RTC clock

| DS3231 | Pi Pin | Function |
|---|---|---|
| VCC | Pin 1 | 3.3V |
| GND | Pin 9 | Ground |
| SDA | Pin 3 | I2C SDA |
| SCL | Pin 5 | I2C SCL |

Insert CR2032 battery into the DS3231 module.

---

## Step 5 — Install CaptureBox

Copy all files from the CaptureBox package to the Pi (USB stick or SCP), then run the install script:

```bash
chmod +x install.sh
sudo ./install.sh
```

The script automatically:
- Updates the system
- Enables SPI, I2C, and serial
- Creates the project folder
- Copies all files
- Downloads the LoRa library
- Creates Python virtual environment
- Installs all Python packages
- Initialises the database with all scenarios
- Installs and starts both services

---

## Step 6 — Install LoRa library (if install.sh couldn't download it)

If the automatic download failed, do this manually:

1. Open a browser on the Pi and go to: `https://www.waveshare.com/wiki/SX1262_868M_LoRa_HAT`
2. Find **Resources** at the bottom and download the demo code zip
3. Extract it and find `sx126x.py`
4. Copy it:
```bash
cp sx126x.py /home/pi_game/capturebox/sx126x.py
```

---

## Step 7 — Change the HMAC secret

The HMAC secret is used to verify radio packets. Change it to something unique — it must match in both the Pi and all boxes.

```bash
nano /home/pi_game/capturebox/lora_receiver.py
```

Find and change:
```python
HMAC_SECRET = b'changeme123'
```

Use the same secret in `config.h` on every ESP32 box.

---

## Step 8 — Set a static IP address

The boxes need to know the Pi's IP. Set a fixed IP on your router:

```bash
hostname -I
```

Note the IP, then log into your router and assign that IP permanently to the Pi's MAC address.

---

## Step 9 — Test everything

### Check services are running
```bash
sudo systemctl status capturebox
sudo systemctl status capturebox-lora
```
Both should show `active (running)`.

### Check hardware
```bash
# SPI (RC522)
ls /dev/spidev*
# Should show: /dev/spidev0.0  /dev/spidev0.1

# I2C (DS3231)
i2cdetect -y 1
# Should show device at address 0x68

# Serial (LoRa HAT)
ls /dev/ttyS0
# Should show: /dev/ttyS0

# NFC reader
cd /home/pi_game/capturebox
source venv/bin/activate
python3 -c "import mfrc522; r=mfrc522.SimpleMFRC522(); print('RC522 OK')"
```

### Open the dashboard
On any device on the same network, open:
```
http://<pi-ip>:5000
```

---

## RC522 NFC wiring diagram

```
RC522    Pi
3.3V  →  Pin 1  (red wire)
GND   →  Pin 6  (black wire)
MOSI  →  Pin 19 (blue wire)
MISO  →  Pin 21 (purple wire)
SCK   →  Pin 23 (orange wire)
SDA   →  Pin 24 (yellow wire)
RST   →  Pin 22 (green wire)
IRQ      not connected
```

---

## Useful commands

```bash
# View logs in real time
journalctl -u capturebox -f
journalctl -u capturebox-lora -f

# Restart services
sudo systemctl restart capturebox
sudo systemctl restart capturebox-lora

# Run Flask manually (for debugging)
cd /home/pi_game/capturebox
source venv/bin/activate
python app.py

# Open database directly
sqlite3 /home/pi_game/capturebox/capturebox.db

# Reset a card via CLI
cd /home/pi_game/capturebox
source venv/bin/activate
python nfc_admin.py
```

---

## File structure

```
/home/pi_game/capturebox/
├── app.py              Flask web application
├── database.py         Database layer
├── lora_receiver.py    LoRa radio receiver service
├── discord_notify.py   Optional Discord notifications
├── nfc_admin.py        CLI card management tool
├── sx126x.py           Waveshare LoRa HAT library
├── capturebox.db       SQLite game database (auto-created)
├── lora_receiver.log   LoRa log (auto-managed)
├── templates/          HTML dashboard pages
├── static/css/         Stylesheet
└── venv/               Python virtual environment

/etc/systemd/system/
├── capturebox.service       Web app — starts on boot
└── capturebox-lora.service  LoRa receiver — starts on boot
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Dashboard not loading | `sudo systemctl restart capturebox` then check `journalctl -u capturebox -n 20` |
| Database error on startup | `sed -i "s\|/home/pi/\|/home/pi_game/\|g" /home/pi_game/capturebox/*.py` |
| LoRa receiver not starting | Check sx126x.py exists in capturebox folder |
| NFC scanner not working | `sudo raspi-config` → Interface → SPI → Enable |
| No /dev/ttyS0 | Enable serial hardware in raspi-config, disable login shell |
| RC522 GPIO warning | Normal — harmless conflict with LoRa HAT GPIO setup |
| Service keeps restarting | Check logs: `journalctl -u capturebox -n 30 --no-pager` |

---

## Game scenarios

| Scenario | Hold | Decay | Cooldown | Notes |
|---|---|---|---|---|
| Classic | 30s | 30 min | 10 min | Standard 3-day game |
| Blitz | 10s | Off | None | Fast 1-hour game |
| Siege | 45s | 1 hour | 15 min | Defenders vs attackers |
| King of Hill | 30s | 30 min | 5 min | One box scores 5× |
| Decay | 20s | 10 min | None | Fast decay, keep moving |
| Sabotage | 40s | 40 min | 10 min | Green instant vs others |
| Alliance | 30s | 30 min | 10 min | Blue+Green vs Red+Yellow |
| Blackout | 30s | 30 min | 10 min | No dashboard during game |
