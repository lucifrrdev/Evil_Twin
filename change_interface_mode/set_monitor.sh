#!/bin/bash

enable_monitor_mode() {
    INTERFACE="$1"

    if [[ -z "$INTERFACE" ]]; then
        echo "❌ Usage: enable_monitor_mode <interface>"
        exit 1
    fi

    echo "[*] Setting NetworkManager to unmanage $INTERFACE..."
    nmcli device set "$INTERFACE" managed no 2>/dev/null || true

    echo "[*] Bringing down interface $INTERFACE..."
    ip link set "$INTERFACE" down

    echo "[*] Setting $INTERFACE to monitor mode..."
    iw dev "$INTERFACE" set type monitor || iwconfig "$INTERFACE" mode monitor

    echo "[*] Bringing up interface $INTERFACE..."
    ip link set "$INTERFACE" up

    echo "[*] Current interface status:"
    iwconfig "$INTERFACE"

    echo "[✓] $INTERFACE is now in monitor mode."
}

# Entry point
enable_monitor_mode "$1"
