#!/bin/bash
# bootstrap script - sets up camcorder system on a fresh raspberry pi
# can be run on any fresh raspberry pi os installation
# usage: curl -sSL https://raw.githubusercontent.com/wolces/main/bootstrap.sh | sudo bash

set -e

# configuration
GIT_REPO="https://github.com/wolces/camcorder.git"
GIT_BRANCH="main"
INSTALL_USER="camcorder"
WIFI_SSID="Camcorder"
WIFI_PASSWORD="recording"

echo "=== camcorder system bootstrap ==="
echo ""
echo "this will set up a complete camcorder system on this raspberry pi"
echo ""

# check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "please run as root: sudo bash bootstrap.sh"
    exit 1
fi

# create user if doesn't exist
if ! id "$INSTALL_USER" &>/dev/null; then
    echo "creating user: $INSTALL_USER"
    useradd -m -G video,audio,render -s /bin/bash "$INSTALL_USER"
    echo "$INSTALL_USER:camcorder" | chpasswd
    echo "$INSTALL_USER ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/$INSTALL_USER
fi

USER_HOME=$(eval echo ~$INSTALL_USER)

echo "installing system packages..."
apt-get update
apt-get install -y \
    git \
    hostapd \
    dnsmasq \
    python3-flask \
    python3-pip \
    python3-gpiozero \
    ffmpeg \
    v4l-utils

# stop conflicting services
systemctl stop dnsmasq 2>/dev/null || true
systemctl stop hostapd 2>/dev/null || true
systemctl disable dnsmasq 2>/dev/null || true
systemctl disable hostapd 2>/dev/null || true

echo "cloning repository..."
if [ -d "$USER_HOME/.git" ]; then
    echo "git repository already exists, pulling latest..."
    cd "$USER_HOME"
    sudo -u "$INSTALL_USER" git pull
else
    # backup existing files if any
    if [ -d "$USER_HOME" ] && [ "$(ls -A $USER_HOME)" ]; then
        BACKUP_DIR="$USER_HOME.backup.$(date +%s)"
        echo "backing up existing files to $BACKUP_DIR"
        mv "$USER_HOME" "$BACKUP_DIR"
    fi
    
    sudo -u "$INSTALL_USER" git clone "$GIT_REPO" "$USER_HOME"
    cd "$USER_HOME"
    sudo -u "$INSTALL_USER" git checkout "$GIT_BRANCH"
fi

# update wifi credentials
if [ -f "$USER_HOME/hostapd.conf" ]; then
    sed -i "s/^ssid=.*/ssid=$WIFI_SSID/" "$USER_HOME/hostapd.conf"
    sed -i "s/^wpa_passphrase=.*/wpa_passphrase=$WIFI_PASSWORD/" "$USER_HOME/hostapd.conf"
fi

# run the install script
if [ -f "$USER_HOME/install.sh" ]; then
    echo "running installation script..."
    bash "$USER_HOME/install.sh"
else
    echo "error: install.sh not found in repository"
    exit 1
fi

echo ""
echo "=== bootstrap complete ==="
echo ""
echo "the system is ready. you should:"
echo "1. review wifi settings in $USER_HOME/hostapd.conf if you want to change them"
echo "2. reboot: sudo reboot"
echo ""
echo "after reboot:"
echo "  - wifi network: $WIFI_SSID"
echo "  - wifi password: $WIFI_PASSWORD"
echo "  - web interface: http://192.168.4.1:8080"
echo ""
