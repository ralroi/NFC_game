#!/bin/bash
# =============================================================
#  CaptureBox — Complete Install Script
#  Run from the folder containing the CaptureBox files:
#    chmod +x install.sh
#    sudo ./install.sh
# =============================================================
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="/home/pi_game/capturebox"
USER="pi_game"

echo ""
echo "╔═══════════════════════════════════════╗"
echo "║     CaptureBox Install Script         ║"
echo "╚═══════════════════════════════════════╝"
echo ""

# 1. System update
echo "► Updating system..."
apt update -q && apt upgrade -y -q
apt install -y -q python3 python3-pip python3-venv git sqlite3 i2c-tools unzip

# 2. Enable SPI and I2C
echo "► Enabling SPI and I2C..."
raspi-config nonint do_spi 0
raspi-config nonint do_i2c 0

# 3. Disable serial login shell (needed for LoRa HAT on ttyS0)
echo "► Configuring serial port..."
raspi-config nonint do_serial_hw 0
raspi-config nonint do_serial_cons 1

# 4. Add pi_game to dialout group for serial access
usermod -a -G dialout $USER

# 5. Create folder structure
echo "► Creating folders..."
mkdir -p $INSTALL_DIR/templates
mkdir -p $INSTALL_DIR/static/css
chown -R $USER:$USER $INSTALL_DIR

# 6. Copy project files
echo "► Copying files..."
cp "$SCRIPT_DIR"/*.py         $INSTALL_DIR/ 2>/dev/null || true
cp "$SCRIPT_DIR/templates"/*.html $INSTALL_DIR/templates/ 2>/dev/null || true
cp "$SCRIPT_DIR/static/css"/*.css $INSTALL_DIR/static/css/ 2>/dev/null || true
chown -R $USER:$USER $INSTALL_DIR
echo "  Files copied"

# 7. Get Waveshare LoRa library
echo "► Getting LoRa library..."
if [ ! -f "$INSTALL_DIR/sx126x.py" ]; then
    cd /home/$USER
    # Try direct download
    wget -q "https://files.waveshare.com/upload/a/a1/Sx126x_lorawan_hat_code.zip" \
         -O sx126x_tmp.zip 2>/dev/null || true
    if [ -f sx126x_tmp.zip ] && unzip -t sx126x_tmp.zip >/dev/null 2>&1; then
        unzip -q sx126x_tmp.zip
        find . -name "sx126x.py" -exec cp {} $INSTALL_DIR/sx126x.py \; 2>/dev/null || true
        rm -f sx126x_tmp.zip
        echo "  sx126x.py installed from download"
    else
        rm -f sx126x_tmp.zip
        echo ""
        echo "  ⚠  Could not download sx126x.py automatically."
        echo "  Download it manually from the Waveshare wiki and copy to:"
        echo "  $INSTALL_DIR/sx126x.py"
        echo ""
    fi
else
    echo "  sx126x.py already present"
fi

# 8. Python virtual environment
echo "► Creating Python environment..."
sudo -u $USER python3 -m venv $INSTALL_DIR/venv
sudo -u $USER $INSTALL_DIR/venv/bin/pip install --quiet \
    flask mfrc522 spidev RPi.GPIO smbus2 requests pyserial
echo "  Python packages installed"

# 9. Initialise database
echo "► Initialising database..."
cd $INSTALL_DIR
sudo -u $USER $INSTALL_DIR/venv/bin/python database.py
echo "  Database ready"

# 10. Install systemd services
echo "► Installing services..."
cp "$SCRIPT_DIR/capturebox.service"      /etc/systemd/system/
cp "$SCRIPT_DIR/capturebox-lora.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable capturebox capturebox-lora
systemctl start  capturebox
sleep 2
systemctl start  capturebox-lora

# 11. Result
IP=$(hostname -I | awk '{print $1}')
echo ""
echo "╔═══════════════════════════════════════╗"
echo "║          Install Complete!            ║"
echo "╚═══════════════════════════════════════╝"
echo ""
echo "  Dashboard : http://$IP:5000"
echo ""
echo "  Service status:"
systemctl is-active capturebox      && echo "  ✓ capturebox (web)" || echo "  ✗ capturebox (web) — check logs"
systemctl is-active capturebox-lora && echo "  ✓ capturebox-lora"  || echo "  ✗ capturebox-lora  — check logs"
echo ""
echo "  ⚠  Edit /home/pi_game/capturebox/lora_receiver.py"
echo "     Change HMAC_SECRET to something unique"
echo ""
echo "  ⚠  Reboot recommended: sudo reboot"
echo ""
