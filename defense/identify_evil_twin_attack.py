from scapy.all import *
import subprocess
import os
import time
import threading
import sys
from tabulate import tabulate

def get_default_wifi_interface():
    try:
        if os.path.exists("/proc/net/dev"):
            with open("/proc/net/dev", "r") as f:
                lines = f.readlines()
            for line in lines[2:]:
                parts = line.split(":")
                if len(parts) > 0:
                    iface = parts[0].strip()
                    # Match typical wireless interfaces (wlan, wl, etc.)
                    if iface.startswith("wl") or iface.startswith("wlan"):
                        return iface
    except Exception:
        pass
    return "wlan0" # fallback

INTERFACE = get_default_wifi_interface()
SCAN_INTERVAL = 10  # seconds
MONITOR_SCRIPT = "change_interface_mode/set_monitor.sh"
start_time = time.time()
stop_flag = False


def set_monitor_mode(interface):
    print(f"[*] Enabling monitor mode on interface {interface} using {MONITOR_SCRIPT}...")
    subprocess.run([MONITOR_SCRIPT, interface], check=True)

def scan_wifi(interface, timeout=10):
    networks = {}

    def handler(pkt):
        if pkt.haslayer(Dot11Beacon) or pkt.haslayer(Dot11ProbeResp):
            ssid = pkt[Dot11Elt].info.decode(errors='ignore') if pkt[Dot11Elt].info else "<Hidden>"
            bssid = pkt[Dot11].addr3
            rssi = pkt.dBm_AntSignal if hasattr(pkt, 'dBm_AntSignal') else "N/A"

            if ssid not in networks:
                networks[ssid] = []
            networks[ssid].append({
                "BSSID": bssid,
                "RSSI": rssi
            })

    sniff(iface=interface, prn=handler, timeout=timeout, store=0)
    return networks

def detect_evil_twin(networks):
    evil_detected = False
    for ssid, entries in networks.items():
        # ננקה כפילויות
        unique_bssids = {}
        for entry in entries:
            bssid = entry["BSSID"]
            rssi = entry["RSSI"]
            if bssid not in unique_bssids:
                unique_bssids[bssid] = rssi

        if len(unique_bssids) > 1:
            evil_detected = True
            print(f"\n⚠️  Possible Evil Twin Detected! SSID: '{ssid}'")
            table = []
            for bssid, rssi in unique_bssids.items():
                table.append([ssid, bssid, rssi])
            print(tabulate(table, headers=["SSID", "BSSID", "RSSI"], tablefmt="fancy_grid"))
    return evil_detected

def countdown_timer():
    while not stop_flag:
        elapsed = int(time.time() - start_time)
        mins, secs = divmod(elapsed, 60)
        print(f"\r⏱  Runtime: {mins:02d}:{secs:02d}", end='', flush=True)
        time.sleep(1)
    print("\n[✓] Scan stopped by user.")

def wait_for_enter():
    global stop_flag
    input("\n\n⏸️ Press Enter to stop scanning...\n")
    stop_flag = True

def main():
    global stop_flag
    set_monitor_mode(INTERFACE)
    print("📡 Starting Evil Twin detection...")

    threading.Thread(target=countdown_timer, daemon=True).start()
    threading.Thread(target=wait_for_enter, daemon=True).start()

    try:
        while not stop_flag:
            print(f"\n🔍 Scanning on interface {INTERFACE}...")
            networks = scan_wifi(INTERFACE)
            evil_found = detect_evil_twin(networks)
            if not evil_found:
                print("✅ No Evil Twin detected.")
            time.sleep(SCAN_INTERVAL)
        print("\n🛑 Scan finished.")
    except KeyboardInterrupt:
        stop_flag = True
        print("\n🛑 Scan stopped with Ctrl+C")

if __name__ == "__main__":
    main()
