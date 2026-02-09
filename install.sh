#!/bin/bash
# installation script for camcorder system
# run as: sudo bash install.sh

set -e

echo "=== camcorder system installation ==="
echo ""

# check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "please run as root: sudo bash install.sh"
    exit 1
fi

# detect actual user
ACTUAL_USER=${SUDO_USER:-camcorder}
USER_HOME=$(eval echo ~$ACTUAL_USER)

echo "installing for user: $ACTUAL_USER"
echo "home directory: $USER_HOME"
echo ""

# install required packages
echo "installing packages..."
apt-get update
apt-get install -y \
    hostapd \
    dnsmasq \
    python3-flask \
    python3-pip \
    git \
    ffmpeg \
    v4l-utils \
    python3-gpiozero

# stop services that might interfere
echo "stopping conflicting services..."
systemctl stop dnsmasq 2>/dev/null || true
systemctl stop hostapd 2>/dev/null || true

# unmask services (they may have been masked)
echo "unmasking services..."
systemctl unmask dnsmasq 2>/dev/null || true
systemctl unmask hostapd 2>/dev/null || true

# disable services from auto-starting (we'll start them via our own service)
echo "disabling default service auto-start..."
systemctl disable dnsmasq 2>/dev/null || true
systemctl disable hostapd 2>/dev/null || true

# configure NetworkManager to ignore wlan0
echo "configuring NetworkManager to ignore wlan0..."
mkdir -p /etc/NetworkManager/conf.d
cat > /etc/NetworkManager/conf.d/unmanage-wlan0.conf <<EOF
[keyfile]
unmanaged-devices=interface-name:wlan0
EOF
echo "  - wrote /etc/NetworkManager/conf.d/unmanage-wlan0.conf"

# configure dhcpcd to ignore wlan0 (if dhcpcd is in use)
if [ -f /etc/dhcpcd.conf ]; then
    echo "configuring dhcpcd to ignore wlan0..."
    if ! grep -q "denyinterfaces wlan0" /etc/dhcpcd.conf; then
        echo "denyinterfaces wlan0" >> /etc/dhcpcd.conf
        echo "  - added denyinterfaces wlan0 to /etc/dhcpcd.conf"
    else
        echo "  - already configured"
    fi
fi

# check if NetworkManager is active before trying to restart it
echo "checking NetworkManager status..."
if systemctl is-active --quiet NetworkManager; then
    echo "restarting NetworkManager (timeout: 10s)..."
    timeout 10 systemctl restart NetworkManager 2>/dev/null || {
        echo "  - NetworkManager restart timed out or failed, continuing anyway..."
    }
else
    echo "  - NetworkManager not active, skipping restart"
fi

# disconnect wlan0 from any existing connections
echo "disconnecting wlan0 from existing connections..."
nmcli device disconnect wlan0 2>/dev/null || true
systemctl restart dhcpcd 2>/dev/null || true

# make scripts executable
echo "setting permissions..."
chmod +x $USER_HOME/setup_wifi_ap.sh
chmod +x $USER_HOME/auto_update.py
chown $ACTUAL_USER:$ACTUAL_USER $USER_HOME/*.py
chown $ACTUAL_USER:$ACTUAL_USER $USER_HOME/*.sh

# copy service files
echo "installing systemd services..."
cp $USER_HOME/recorder.service /etc/systemd/system/
cp $USER_HOME/web_server.service /etc/systemd/system/
cp $USER_HOME/wifi_ap.service /etc/systemd/system/
cp $USER_HOME/auto_update.service /etc/systemd/system/

# create templates directory if it doesn't exist
echo "verifying templates directory..."
mkdir -p $USER_HOME/templates
chown $ACTUAL_USER:$ACTUAL_USER $USER_HOME/templates

# check if index.html is in the right place
if [ -f "$USER_HOME/index.html" ] && [ ! -f "$USER_HOME/templates/index.html" ]; then
    echo "  - moving index.html into templates directory..."
    mv "$USER_HOME/index.html" "$USER_HOME/templates/"
fi

if [ ! -f "$USER_HOME/templates/index.html" ]; then
    echo "  - WARNING: templates/index.html not found!"
    echo "    Make sure index.html is in the templates/ directory in your git repo"
fi

# reload systemd
echo "reloading systemd..."
systemctl daemon-reload

# enable services
echo "enabling services..."
systemctl enable recorder.service
systemctl enable web_server.service
systemctl enable wifi_ap.service
systemctl enable auto_update.service

# setup git repo (if not already done)
if [ ! -d "$USER_HOME/.git" ]; then
    echo ""
    echo "git repository not initialized."
    echo "you should initialize it with:"
    echo "  cd $USER_HOME"
    echo "  git init"
    echo "  git remote add origin YOUR_REPO_URL"
    echo "  git add ."
    echo "  git commit -m 'initial commit'"
    echo "  git push -u origin main"
fi

# add sudoers entry for auto-update
echo "configuring sudo permissions..."
SUDOERS_LINE="$ACTUAL_USER ALL=(ALL) NOPASSWD: /bin/systemctl daemon-reload, /bin/systemctl restart web_server.service, /bin/systemctl restart wifi_ap.service, /bin/cp * /etc/systemd/system/*, /sbin/shutdown"

if ! grep -q "$ACTUAL_USER.*systemctl daemon-reload" /etc/sudoers.d/camcorder 2>/dev/null; then
    echo "$SUDOERS_LINE" > /etc/sudoers.d/camcorder
    chmod 440 /etc/sudoers.d/camcorder
fi

echo ""
echo "=== installation complete ==="
echo ""
echo "next steps:"
echo "1. edit hostapd.conf to change wifi ssid/password if desired"
echo "2. setup git repository for auto-updates"
echo "3. reboot or start services manually:"
echo "   sudo systemctl start recorder.service"
echo "   sudo systemctl start web_server.service"
echo "   sudo systemctl start wifi_ap.service"
echo "   sudo systemctl start auto_update.service"
echo ""
echo "wifi access point:"
echo "  ssid: Camcorder"
echo "  password: recording"
echo "  web interface: http://192.168.4.1:8080"
echo ""
echo "auto-update:"
echo "  plug in ethernet cable to trigger update check"
echo ""
