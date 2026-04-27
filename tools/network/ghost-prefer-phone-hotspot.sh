#!/usr/bin/env bash
set -u

export LC_ALL=C

WIFI_IFACE="${WIFI_IFACE:-wlan0}"
PHONE_SSID="${PHONE_SSID:-GhostChessboard-Hotspot}"

log() {
  echo "ghost-prefer-phone-hotspot: $*"
}

active_connection="$(nmcli -g GENERAL.CONNECTION device show "$WIFI_IFACE" 2>/dev/null | head -n 1 | tr -d '\r')"

if [[ "$active_connection" == "$PHONE_SSID" ]]; then
  log "already connected to '$PHONE_SSID' on $WIFI_IFACE"
  exit 0
fi

if ! nmcli -t -f SSID device wifi list ifname "$WIFI_IFACE" --rescan yes 2>/dev/null | grep -Fxq "$PHONE_SSID"; then
  log "'$PHONE_SSID' is not visible on $WIFI_IFACE; staying on '${active_connection:-none}'"
  exit 0
fi

log "switching $WIFI_IFACE from '${active_connection:-none}' to '$PHONE_SSID'"
nmcli --wait 20 connection up id "$PHONE_SSID" ifname "$WIFI_IFACE"
