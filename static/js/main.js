// Global Target variables
let selectedBssid = '';
let selectedSsid = '';
let selectedClient = 'FF:FF:FF:FF:FF:FF';

// State polling & refresh
let statePollingInterval;
let activeInterfaces = [];

document.addEventListener("DOMContentLoaded", () => {
    // Initial load of interfaces
    fetchInterfaces().then(async () => {
        // Send localStorage configurations to backend if they exist
        const storedAdapter = localStorage.getItem('adapter_interface');
        const storedMy = localStorage.getItem('my_interface');
        if (storedAdapter || storedMy) {
            const updatePayload = {};
            if (storedAdapter && activeInterfaces.includes(storedAdapter)) {
                updatePayload.adapter_interface = storedAdapter;
            }
            if (storedMy && activeInterfaces.includes(storedMy)) {
                updatePayload.my_interface = storedMy;
            }
            if (Object.keys(updatePayload).length > 0) {
                await postData('/api/update-interfaces', updatePayload);
            }
        }
        updateState();
        statePollingInterval = setInterval(updateState, 3000);
    });

    // Start Server-Sent Events (SSE) log stream
    connectSseStream();

    // Fetch credentials regularly
    fetchCredentials();
    setInterval(fetchCredentials, 5000);
});

// Fetch active interfaces from backend
async function fetchInterfaces() {
    try {
        const res = await fetch('/api/interfaces');
        const data = await res.json();
        activeInterfaces = data.interfaces || [];
        populateInterfaceSelects();
    } catch (e) {
        logToConsole(`[Error] Failed to fetch interfaces: ${e.message}`, 'error');
    }
}

function populateInterfaceSelects() {
    const adapterSelect = document.getElementById('adapter_interface');
    const mySelect = document.getElementById('my_interface');
    if (!adapterSelect || !mySelect) return;

    // Save current selections
    const currentAdapter = adapterSelect.value;
    const currentMy = mySelect.value;

    adapterSelect.innerHTML = '';
    mySelect.innerHTML = '';

    if (activeInterfaces.length === 0) {
        const opt = document.createElement('option');
        opt.value = '';
        opt.innerText = 'No Interfaces Found';
        adapterSelect.appendChild(opt.cloneNode(true));
        mySelect.appendChild(opt);
        return;
    }

    activeInterfaces.forEach(iface => {
        const opt = document.createElement('option');
        opt.value = iface.name;
        opt.innerText = `${iface.name} (${iface.ip})`;
        adapterSelect.appendChild(opt.cloneNode(true));
        mySelect.appendChild(opt);
    });

    // Extract list of names for existence check
    const interfaceNames = activeInterfaces.map(i => i.name);

    // Restore from localStorage or current fallback
    const storedAdapter = localStorage.getItem('adapter_interface');
    const storedMy = localStorage.getItem('my_interface');

    if (storedAdapter && interfaceNames.includes(storedAdapter)) {
        adapterSelect.value = storedAdapter;
    } else if (interfaceNames.includes(currentAdapter)) {
        adapterSelect.value = currentAdapter;
    }

    if (storedMy && interfaceNames.includes(storedMy)) {
        mySelect.value = storedMy;
    } else if (interfaceNames.includes(currentMy)) {
        mySelect.value = currentMy;
    }
}

// Tab Switching logic
function switchTab(tabId) {
    document.querySelectorAll('.tab-panel').forEach(panel => {
        panel.classList.remove('active');
    });
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.remove('active');
    });

    document.getElementById(tabId).classList.add('active');
    event.currentTarget.classList.add('active');
}

// REST helper
async function postData(url, data = {}) {
    try {
        const response = await fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data)
        });
        return await response.json();
    } catch (error) {
        logToConsole(`[Error] Request failed: ${error.message}`, 'error');
    }
}

// Update settings interface names
async function updateInterfaces() {
    const adapter = document.getElementById('adapter_interface').value;
    const myIface = document.getElementById('my_interface').value;

    // Save selected values to local storage
    localStorage.setItem('adapter_interface', adapter);
    localStorage.setItem('my_interface', myIface);

    const result = await postData('/api/update-interfaces', {
        adapter_interface: adapter,
        my_interface: myIface
    });
    if (result && result.success) {
        logToConsole(`[System] Interfaces config saved to system and LocalStorage.`, 'info');
    }
}

// Handle State response
function updateState() {
    fetch('/api/state')
        .then(res => res.json())
        .then(state => {
            // Update inputs if they are in options list
            const interfaceNames = activeInterfaces.map(i => i.name);
            if (interfaceNames.includes(state.adapter_interface)) {
                document.getElementById('adapter_interface').value = state.adapter_interface;
            }
            if (interfaceNames.includes(state.my_interface)) {
                document.getElementById('my_interface').value = state.my_interface;
            }

            // Update Target displays
            document.getElementById('sidebar-target-ssid').innerText = state.selected_ssid || "None Selected";
            document.getElementById('sidebar-target-bssid').innerText = state.selected_bssid || "None Selected";
            document.getElementById('sidebar-target-client').innerText = state.selected_client || "Broadcast (FF:FF:FF:FF:FF:FF)";


            selectedBssid = state.selected_bssid;
            selectedSsid = state.selected_ssid;
            selectedClient = state.selected_client;

            // Global Status indicator
            const statusPill = document.getElementById('global-status');
            const statusText = document.getElementById('status-text');
            
            if (state.ap_active || state.portal_active || state.deauth_active) {
                statusPill.className = "status-pill status-active";
                let text = "ATTACK ACTIVE: ";
                let parts = [];
                if (state.ap_active) parts.push("AP");
                if (state.portal_active) parts.push("Portal");
                if (state.deauth_active) parts.push("Deauth");
                statusText.innerText = text + parts.join(" + ");
            } else if (state.defense_active) {
                statusPill.className = "status-pill status-active";
                statusText.innerText = "DEFENSE ACTIVE";
            } else if (state.is_scanning) {
                statusPill.className = "status-pill status-active";
                statusText.innerText = "SCANNING WI-FI...";
            } else {
                statusPill.className = "status-pill status-inactive";
                statusText.innerText = "SYSTEM IDLE";
            }

            // Buttons visual toggles
            updateButtonState('btn-toggle-ap', state.ap_active, '🚀 Launch AP', '🛑 Stop AP');
            updateButtonState('btn-toggle-portal', state.portal_active, '🌐 Start Captive Portal', '🛑 Stop Captive Portal');
            updateButtonState('btn-toggle-deauth', state.deauth_active, '🎯 Start Deauth', '🛑 Stop Deauth');
            updateButtonState('btn-toggle-defense', state.defense_active, '🛡️ Activate Defense Monitor', '🛑 Deactivate Defense Monitor');
        });
}

function updateButtonState(btnId, isActive, activeText, inactiveText) {
    const btn = document.getElementById(btnId);
    if (!btn) return;
    if (isActive) {
        btn.innerText = inactiveText;
        btn.className = "btn btn-danger";
    } else {
        btn.innerText = activeText;
        if (btnId === 'btn-toggle-defense') {
            btn.className = "btn btn-success";
        } else if (btnId === 'btn-toggle-deauth') {
            btn.className = "btn btn-danger";
        } else {
            btn.className = "btn btn-secondary";
        }
    }
}

// Wi-Fi Scan triggering and result rendering
async function startWifiScan() {
    const btn = document.getElementById('btn-scan');
    btn.disabled = true;
    btn.innerText = "Scanning networks (15s)...";
    logToConsole("[System] Scanning started. Please wait...", "info");

    const result = await postData('/api/scan');
    if (result && result.success) {
        // Wait 16s then pull results
        setTimeout(async () => {
            await fetchScanResults();
            btn.disabled = false;
            btn.innerText = "🔍 Scan Nearby Networks (15s)";
        }, 16000);
    } else {
        btn.disabled = false;
        btn.innerText = "🔍 Scan Nearby Networks (15s)";
        const errMsg = result ? result.error : "Unknown error";
        logToConsole(`[Error] Scan failed: ${errMsg}`, 'error');
        alert(`Scan failed: ${errMsg}`);
    }
}

let globalScanResults = {};

async function fetchScanResults() {
    try {
        const response = await fetch('/api/scan-results');
        const data = await response.json();
        globalScanResults = data;
        renderNetworksTable(data.access_points);
    } catch (e) {
        logToConsole(`[Error] Failed to fetch scan results: ${e.message}`, 'error');
    }
}

function renderNetworksTable(aps) {
    const tbody = document.querySelector('#networks-table tbody');
    tbody.innerHTML = '';

    const keys = Object.keys(aps);
    if (keys.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-secondary);">No networks found.</td></tr>';
        return;
    }

    keys.forEach(bssid => {
        const ap = aps[bssid];
        const tr = document.createElement('tr');
        
        // Signal class mapping
        let signalClass = 'signal-badge signal-weak';
        if (ap.PWR > -60) signalClass = 'signal-badge signal-strong';
        else if (ap.PWR > -80) signalClass = 'signal-badge signal-medium';

        tr.innerHTML = `
            <td>
                <strong>${ap.SSID || '&lt;Hidden&gt;'}</strong>
                <br>
                <small style="color: var(--text-secondary); font-family: var(--font-mono); font-size: 0.8rem;">${bssid}</small>
            </td>
            <td style="font-family: var(--font-mono);">${bssid}</td>
            <td><span class="${signalClass}">${ap.PWR} dBm</span></td>
            <td>${ap.CH}</td>
            <td>${ap.ENC} (${ap.AUTH})</td>
        `;

        if (bssid === selectedBssid) {
            tr.classList.add('selected');
        }

        tr.addEventListener('click', () => {
            document.querySelectorAll('#networks-table tbody tr').forEach(r => r.classList.remove('selected'));
            tr.classList.add('selected');
            selectTargetNetwork(bssid, ap.SSID);
        });

        tbody.appendChild(tr);
    });
}

function renderClientsTable(bssid) {
    const tbody = document.querySelector('#clients-table tbody');
    if (!tbody) return;
    tbody.innerHTML = '';

    const clientsList = globalScanResults.clients ? globalScanResults.clients[bssid] || [] : [];
    
    if (clientsList.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-secondary);">No clients detected for this network yet.</td></tr>';
        return;
    }

    clientsList.forEach(client => {
        const tr = document.createElement('tr');
        const isClientSelected = (client.MAC === selectedClient);
        if (isClientSelected) {
            tr.classList.add('selected');
        }

        tr.innerHTML = `
            <td style="font-family: var(--font-mono);">${client.MAC}</td>
            <td>${client.Vendor || 'Unknown'}</td>
            <td>${client.RSSI ? client.RSSI + ' dBm' : 'N/A'}</td>
            <td style="color: var(--accent); font-weight: bold;">${client.IP || 'Scanning IP...'}</td>
            <td>
                <button class="btn btn-danger" style="padding: 0.25rem 0.5rem; font-size: 0.8rem;" onclick="selectClientTarget('${client.MAC}')">
                    Target Client
                </button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

function selectClientTarget(clientMac) {
    selectedClient = clientMac;
    logToConsole(`[Client Target Selected] MAC: ${clientMac}`, 'info');
    postData('/api/update-interfaces', {
        selected_client: clientMac
    }).then(() => {
        updateState();
        renderClientsTable(selectedBssid);
    });
}

async function selectTargetNetwork(bssid, ssid) {
    selectedBssid = bssid;
    selectedSsid = ssid;
    logToConsole(`[Target Selected] SSID: ${ssid} | BSSID: ${bssid}`, 'info');
    
    // Render clients table for this network
    renderClientsTable(bssid);

    // Save selections to backend state
    await postData('/api/update-interfaces', {
        selected_bssid: bssid,
        selected_ssid: ssid
    });
    updateState();
}

// Attack Toggles
async function toggleRogueAP() {
    const btn = document.getElementById('btn-toggle-ap');
    const isStopping = btn.innerText.includes('Stop');
    
    if (isStopping) {
        logToConsole("[System] Stopping Rogue AP...", "info");
        await postData('/api/stop-ap');
    } else {
        if (!selectedSsid) {
            alert("Please select a target network from the table first!");
            return;
        }
        logToConsole(`[System] Launching Rogue AP with SSID: ${selectedSsid}`, "info");
        const res = await postData('/api/start-ap', { bssid: selectedBssid, ssid: selectedSsid });
        if (res && !res.success) {
            logToConsole(`[Error] AP failed to start: ${res.error}`, 'error');
            alert(`AP failed to start: ${res.error}`);
        }
    }
    updateState();
}

async function togglePortal() {
    const btn = document.getElementById('btn-toggle-portal');
    const isStopping = btn.innerText.includes('Stop');

    if (isStopping) {
        logToConsole("[System] Stopping Captive Portal...", "info");
        await postData('/api/stop-ap'); // full reset shuts both AP and portal down
    } else {
        logToConsole("[System] Launching Captive Portal on Rogue AP interface...", "info");
        const res = await postData('/api/start-portal');
        if (res && !res.success) {
            logToConsole(`[Error] Captive Portal failed to start: ${res.error}`, 'error');
            alert(`Captive Portal failed to start: ${res.error}`);
        }
    }
    updateState();
}

async function toggleDeauth() {
    const btn = document.getElementById('btn-toggle-deauth');
    const isStopping = btn.innerText.includes('Stop');

    if (isStopping) {
        logToConsole("[System] Stopping Deauth attack...", "info");
        await postData('/api/stop-deauth');
    } else {
        if (!selectedBssid) {
            alert("Please select a target network from the table first!");
            return;
        }
        logToConsole(`[System] Launching Deauth jammer on target BSSID: ${selectedBssid}`, "info");
        const res = await postData('/api/start-deauth', { bssid: selectedBssid, client_mac: selectedClient });
        if (res && !res.success) {
            logToConsole(`[Error] Deauth failed to start: ${res.error}`, 'error');
            alert(`Deauth failed to start: ${res.error}`);
        }
    }
    updateState();
}

async function toggleDefense() {
    const btn = document.getElementById('btn-toggle-defense');
    const isStopping = btn.innerText.includes('Deactivate');

    if (isStopping) {
        logToConsole("[System] Deactivating Defense mode...", "info");
        await postData('/api/stop-defense');
    } else {
        logToConsole("[System] Activating Defense monitor...", "info");
        const res = await postData('/api/start-defense');
        if (res && !res.success) {
            logToConsole(`[Error] Defense failed to start: ${res.error}`, 'error');
            alert(`Defense failed to start: ${res.error}`);
        }
    }
    updateState();
}


async function cleanupSystem() {
    logToConsole("[System] Triggering full system cleanup & reset...", "warning");
    await postData('/api/cleanup');
    updateState();
}

// Credentials Pulling
function fetchCredentials() {
    fetch('/api/credentials')
        .then(res => res.json())
        .then(data => {
            const list = document.getElementById('credentials-list');
            if (data.credentials.length === 0) {
                list.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--text-secondary); padding: 2rem 0;">
                                    No credentials captured yet. Waiting for client log-ins...
                                  </div>`;
                return;
            }

            list.innerHTML = '';
            data.credentials.forEach(cred => {
                // Parse timestamp and fields
                // Expected format: "[2026-07-04 17:49:00] IP: 192.168.1.100, Username: admin, Password: password123"
                const matches = cred.match(/^\[(.*?)\]\s*IP:\s*(.*?),\s*Username:\s*(.*?),\s*Password:\s*(.*)$/);
                
                const card = document.createElement('div');
                card.className = "credential-card";

                if (matches) {
                    const [_, time, ip, user, pass] = matches;
                    card.innerHTML = `
                        <div class="credential-header">
                            <span>🕒 ${time}</span>
                            <span>💻 IP: ${ip}</span>
                        </div>
                        <div class="credential-data">User: <span>${user}</span></div>
                        <div class="credential-data">Pass: <span>${pass}</span></div>
                    `;
                } else {
                    card.innerHTML = `<div class="credential-data" style="color: var(--text-secondary);">${cred}</div>`;
                }
                list.appendChild(card);
            });
        });
}

// Logging Terminal Stream connection
function connectSseStream() {
    const sse = new EventSource('/api/stream');
    sse.onmessage = function (event) {
        if (event.data === ":keepalive") return;
        
        let type = 'info';
        if (event.data.includes('❌') || event.data.includes('Error') || event.data.includes('Failed')) {
            type = 'error';
        } else if (event.data.includes('⚠️') || event.data.includes('Warning') || event.data.includes('Possible Evil Twin')) {
            type = 'warning';
        } else if (event.data.includes('✅') || event.data.includes('[✓]') || event.data.includes('Saved') || event.data.includes('Login')) {
            type = 'success';
        }

        logToConsole(event.data, type);
    };
    sse.onerror = function () {
        logToConsole("[System] SSE stream disconnected. Reconnecting...", "warning");
    };
}

// Log directly to GUI console
function logToConsole(message, type = 'info') {
    const consoleBody = document.getElementById('console-body');
    if (!consoleBody) return;

    const entry = document.createElement('div');
    entry.className = `log-entry ${type}`;
    entry.innerText = message;

    consoleBody.appendChild(entry);
    consoleBody.scrollTop = consoleBody.scrollHeight;
}

function clearConsole() {
    document.getElementById('console-body').innerHTML = '';
}
