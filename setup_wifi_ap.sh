#!/bin/bash
# setup wifi access point for camcorder

set -e

echo "configuring wifi access point..."

# configure wlan0 with static ip
ip addr flush dev wlan0
ip addr add 192.168.4.1/24 dev wlan0
ip link set wlan0 up

# enable ip forwarding (in case we want to bridge to internet later)
echo 1 > /proc/sys/net/ipv4/ip_forward

# add port forwarding: redirect port 80 to 8080 for web interface
# this allows users to access http://camcorder.local without :8080
iptables -t nat -F  # flush existing nat rules
iptables -t nat -A PREROUTING -p tcp --dport 80 -j REDIRECT --to-port 8080

# start dnsmasq
dnsmasq -C /home/camcorder/dnsmasq.conf

# start hostapd
hostapd -B /home/camcorder/hostapd.conf

echo "wifi access point ready: ssid=Camcorder, password=recording, ip=192.168.4.1"
echo "web interface: http://camcorder.local or http://192.168.4.1"