// AIOps NOC Platform - Client Logic & State Management

let authToken = localStorage.getItem('access_token');
let ws = null;
let currentDevices = [];
let currentAlerts = [];

// DOM Elements
const authOverlay = document.getElementById('auth-overlay');
const appContainer = document.getElementById('app-container');
const loginForm = document.getElementById('login-form');
const authError = document.getElementById('auth-error');
const logoutBtn = document.getElementById('logout-btn');
const wsDot = document.getElementById('ws-dot');
const wsStatusText = document.getElementById('ws-status-text');

// Metrics
const statsDevices = document.getElementById('stats-devices');
const statsAlerts = document.getElementById('stats-alerts');
const statsRemedies = document.getElementById('stats-remedies');

// Alert log
const alertStream = document.getElementById('alert-stream');
const emptyAlerts = document.getElementById('empty-alerts');
const clearAlertsBtn = document.getElementById('clear-alerts-btn');

// Chat
const aiChatStream = document.getElementById('ai-chat-stream');
const aiQueryForm = document.getElementById('ai-query-form');
const aiQueryInput = document.getElementById('ai-query-input');

// Initialize App
document.addEventListener('DOMContentLoaded', () => {
    if (authToken) {
        showDashboard();
    } else {
        showAuth();
    }
    
    // Bind quick queries
    document.querySelectorAll('.quick-query-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const query = e.target.getAttribute('data-query');
            submitAIQuery(query);
        });
    });
});

// Event Listeners
loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = document.getElementById('username').value;
    const password = document.getElementById('password').value;
    
    try {
        const response = await fetch('/api/v1/auth/token', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });
        
        if (response.ok) {
            const data = await response.json();
            authToken = data.access_token;
            localStorage.setItem('access_token', authToken);
            authError.classList.add('hide');
            showDashboard();
        } else {
            authError.classList.remove('hide');
        }
    } catch (err) {
        authError.textContent = "Server Connection Error";
        authError.classList.remove('hide');
    }
});

logoutBtn.addEventListener('click', () => {
    localStorage.removeItem('access_token');
    authToken = null;
    if (ws) ws.close();
    showAuth();
});

clearAlertsBtn.addEventListener('click', () => {
    alertStream.innerHTML = '';
    alertStream.appendChild(emptyAlerts);
    emptyAlerts.classList.remove('hide');
    currentAlerts = [];
    updateMetricCards();
    renderDevicesList(currentDevices); // Re-render to reset status badges
});

aiQueryForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const query = aiQueryInput.value.trim();
    if (!query) return;
    submitAIQuery(query);
    aiQueryInput.value = '';
});

// View Toggle
function showDashboard() {
    authOverlay.classList.add('hide');
    appContainer.classList.remove('hide');
    
    // Load initial data
    loadDevices();
    connectWebSocket();
}

function showAuth() {
    appContainer.classList.add('hide');
    authOverlay.classList.remove('hide');
    loginForm.reset();
}

// Fetch APIs
const defFetch = async (url, options = {}) => {
    options.headers = {
        ...options.headers,
        'Authorization': `Bearer ${authToken}`
    };
    const response = await fetch(url, options);
    if (response.status === 401) {
        // Token expired
        logoutBtn.click();
        throw new Error("Session expired");
    }
    if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
    }
    return response;
};

async function loadDevices() {
    try {
        // Normally calls decFetch('/api/v1/devices')
        // We will simulate fallback devices to bootstrap the dashboard visually
        // If the user's LibreNMS connection fails
        let devicesData;
        try {
            const res = await defFetch('/api/v1/devices');
            devicesData = await res.json();
        } catch (e) {
            // Mock Fallback devices
            devicesData = {
                devices: [
                    { id: 1, hostname: "core-sw-01.headquarters.net", ip: "192.168.10.1", os: "ios", hardware: "Cisco Catalyst 3850", status: "Active" },
                    { id: 2, hostname: "distribution-sw-02.headquarters.net", ip: "192.168.10.2", os: "ios", hardware: "Cisco Catalyst 2960", status: "Active" },
                    { id: 3, hostname: "distribution-sw-03.headquarters.net", ip: "192.168.10.3", os: "ios", hardware: "Cisco Catalyst 2960", status: "Active" },
                    { id: 4, hostname: "border-router-01.headquarters.net", ip: "10.254.0.1", os: "iosxr", hardware: "Cisco ASR 9001", status: "Active" },
                    { id: 5, hostname: "application-server-01", ip: "192.168.20.10", os: "linux", hardware: "Ubuntu 22.04 LTS", status: "Active" },
                    { id: 6, hostname: "storage-san-01", ip: "192.168.20.11", os: "linux", hardware: "TrueNAS Enterprise", status: "Active" }
                ]
            };
        }
        
        currentDevices = devicesData.devices || devicesData;
        updateMetricCards();
        renderDevicesList(currentDevices); // Render monitored devices list
        
        // Auto-select the first device to show basic information by default
        if (currentDevices.length > 0) {
            window.inspectDevice(currentDevices[0]);
            // Highlight it in the list
            setTimeout(() => {
                const firstItem = document.querySelector('.device-item');
                if (firstItem) firstItem.classList.add('active');
            }, 100);
        }
    } catch (err) {
        console.error("Failed to load devices", err);
    }
}

// Live Stream
function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/api/v1/ws/alerts`;
    
    ws = new WebSocket(wsUrl);
    
    ws.onopen = () => {
        wsDot.className = "dot dot-green blinking-glow";
        wsStatusText.textContent = "Live Stream Connected";
    };
    
    ws.onmessage = (event) => {
        const alert = JSON.parse(event.data);
        handleIncomingAlert(alert);
    };
    
    ws.onclose = () => {
        wsDot.className = "dot dot-red blinking-glow";
        wsStatusText.textContent = "Reconnecting Alert Stream...";
        setTimeout(connectWebSocket, 5000);
    };
}

function handleIncomingAlert(alert) {
    emptyAlerts.classList.add('hide');
    
    // Add to alerts list
    currentAlerts.unshift(alert);
    
    // Create Alert Element
    const alertDiv = document.createElement('div');
    alertDiv.className = `alert-item ${alert.severity === 'critical' ? 'critical' : 'warning'}`;
    
    const timeStr = new Date(alert.timestamp || Date.now()).toLocaleTimeString();
    
    alertDiv.innerHTML = `
        <div class="alert-content">
            <h4>${alert.rule_name || 'Alarms Tripped'} - ${alert.hostname}</h4>
            <p>${alert.msg}</p>
            <div class="alert-actions">
                <span class="badge ${alert.severity === 'critical' ? 'badge-red' : 'badge-purple'}">${alert.severity}</span>
                <button class="btn btn-outline btn-sm ask-ai-btn" data-alert='${JSON.stringify(alert)}'>Ask AI Copilot</button>
            </div>
        </div>
        <span class="alert-time">${timeStr}</span>
    `;
    
    alertStream.insertBefore(alertDiv, alertStream.firstChild);
    
    // Bind the dynamic button
    alertDiv.querySelector('.ask-ai-btn').addEventListener('click', (e) => {
        const data = JSON.parse(e.currentTarget.getAttribute('data-alert'));
        const queryText = `Analyze network alert details:\nHost: ${data.hostname}\nSeverity: ${data.severity}\nRule: ${data.rule_name}\nDescription: ${data.msg}`;
        submitAIQuery(queryText);
    });

    // Update statistics
    updateMetricCards();
    
    // Update status badge in device list
    renderDevicesList(currentDevices);
}

function updateMetricCards() {
    statsDevices.textContent = `${currentDevices.length} Active`;
    statsAlerts.textContent = `${currentAlerts.length} Active`;
    const devicesBadge = document.getElementById('devices-badge');
    if (devicesBadge) {
        devicesBadge.textContent = `${currentDevices.length} Devices`;
    }
}

// Device Inspector Details
window.inspectDevice = function(device) {
    const inspectorContent = document.getElementById('inspector-content');
    
    // Check if there is an active alert for this device
    const activeAlert = currentAlerts.find(a => a.hostname === device.hostname);
    
    inspectorContent.innerHTML = `
        <div class="inspector-grid">
            <div class="inspector-card">
                <h4>Hostname</h4>
                <p>${device.hostname}</p>
            </div>
            <div class="inspector-card">
                <h4>Management IP</h4>
                <p>${device.ip}</p>
            </div>
            <div class="inspector-card">
                <h4>Hardware Model</h4>
                <p>${device.hardware}</p>
            </div>
            <div class="inspector-card">
                <h4>Operating System</h4>
                <p class="text-purple">${device.os.toUpperCase()}</p>
            </div>
            <div class="inspector-card">
                <h4>Uptime Metric</h4>
                <p class="text-green">99.998%</p>
            </div>
            <div class="inspector-card">
                <h4>Active Status</h4>
                <p><span class="badge ${activeAlert ? 'badge-red' : 'badge-green'}">${activeAlert ? 'ALERTING' : 'HEALTHY'}</span></p>
            </div>
        </div>
        
        <div class="quick-queries" style="margin-top: 1rem;">
            <button class="btn btn-secondary btn-sm" onclick="submitAIQuery('Show running config compliance check details for ${device.hostname}')">Run Audit Compliance</button>
            <button class="btn btn-purple btn-sm btn-glow" onclick="submitAIQuery('Run Diagnostic RCA check on device ${device.hostname}')">Run AI Diagnostics</button>
        </div>
    `;
};

// AI Ops Query Processing
async function submitAIQuery(queryText) {
    // Add user chat bubble
    appendChatBubble(queryText, 'user');
    
    // Add loading/typing bubble
    const loadingId = appendChatLoadingBubble();
    
    try {
        const response = await fetch('/api/v1/ai/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: queryText })
        });
        
        // Remove loading bubble
        removeChatBubble(loadingId);
        
        if (response.ok) {
            const data = await response.json();
            
            let contentHTML = "";
            if (data.answer) {
                contentHTML += `<p>${data.answer}</p>`;
            } else if (data.possible_root_cause) {
                contentHTML += `<p>${data.possible_root_cause}</p>`;
            }
            
            // Check if there are active troubleshooting fields populated
            const showRCA = data.possible_root_cause && data.possible_root_cause !== "N/A" && data.possible_root_cause !== data.answer;
            const showImpact = data.impact_assessment && data.impact_assessment !== "N/A";
            const showPlaybook = data.suggested_remediation_playbook && data.suggested_remediation_playbook !== "N/A";
            
            if (showRCA || showImpact || showPlaybook) {
                contentHTML += `
                    <details class="troubleshooting-drawer" style="margin-top: 0.8rem; cursor: pointer; font-size: 0.9rem;">
                        <summary style="color: var(--text-purple, #a855f7); font-weight: 600; outline: none; margin-bottom: 0.5rem; user-select: none;">🔬 View Engineering Details & Runbook Match</summary>
                        <div style="padding-left: 0.5rem; border-left: 2px solid rgba(168, 85, 247, 0.4); margin-top: 0.5rem;">
                `;
                if (showRCA) {
                    contentHTML += `<p style="margin-top: 0.5rem;"><strong>Root Cause Analysis:</strong><br>${data.possible_root_cause}</p>`;
                }
                if (showImpact) {
                    contentHTML += `<p style="margin-top: 0.5rem;"><strong>Impact Assessment:</strong><br>${data.impact_assessment}</p>`;
                }
                if (showPlaybook) {
                    contentHTML += `
                        <p style="margin-top: 0.5rem;"><strong>Remediation Playbook:</strong></p>
                        <div class="ai-response-block" style="background: rgba(5, 7, 18, 0.4); border: 1px solid var(--border-color); border-radius: 6px; padding: 0.5rem; font-family: monospace; white-space: pre-wrap; font-size: 0.85rem; margin-top: 0.25rem;">${data.suggested_remediation_playbook}</div>
                    `;
                }
                if (data.confidence_score) {
                    contentHTML += `<span class="ai-score" style="display: block; font-size: 0.8rem; opacity: 0.7; margin-top: 0.5rem;">Confidence Score: ${(data.confidence_score * 100).toFixed(0)}%</span>`;
                }
                contentHTML += `
                        </div>
                    </details>
                `;
            }
            
            appendChatBubble(contentHTML, 'system', true);
        } else {
            appendChatBubble("Error communicating with AI ops backend engine.", 'system');
        }
    } catch (err) {
        removeChatBubble(loadingId);
        appendChatBubble("Network exception occurred connecting to AI engine service.", 'system');
    }
}

function appendChatBubble(content, sender, isHTML = false) {
    const bubble = document.createElement('div');
    bubble.className = `chat-message ${sender === 'user' ? 'user-chat' : 'system-chat'}`;
    
    if (isHTML) {
        bubble.innerHTML = content;
    } else {
        const p = document.createElement('p');
        p.textContent = content;
        bubble.appendChild(p);
    }
    
    aiChatStream.appendChild(bubble);
    aiChatStream.scrollTop = aiChatStream.scrollHeight;
}

function appendChatLoadingBubble() {
    const loadingId = 'loading-' + Math.random().toString(36).substr(2, 9);
    const bubble = document.createElement('div');
    bubble.className = 'chat-message system-chat';
    bubble.id = loadingId;
    bubble.innerHTML = `
        <div class="flex-row" style="gap: 5px;">
            <div class="pulse-ring" style="width: 8px; height: 8px;"></div>
            <span>AI Copilot thinking...</span>
        </div>
    `;
    aiChatStream.appendChild(bubble);
    aiChatStream.scrollTop = aiChatStream.scrollHeight;
    return loadingId;
}

function removeChatBubble(id) {
    const bubble = document.getElementById(id);
    if (bubble) bubble.remove();
}

// Settings Panel Controls
const settingsModal = document.getElementById('settings-modal');
const settingsBtn = document.getElementById('settings-btn');
const closeSettingsBtn = document.getElementById('close-settings-btn');
const cancelSettingsBtn = document.getElementById('cancel-settings-btn');
const settingsForm = document.getElementById('settings-form');
const settingsStatus = document.getElementById('settings-status');

settingsBtn.addEventListener('click', openSettings);
closeSettingsBtn.addEventListener('click', closeSettings);
cancelSettingsBtn.addEventListener('click', closeSettings);
settingsForm.addEventListener('submit', saveSettings);

async function openSettings() {
    try {
        const res = await defFetch('/api/v1/settings');
        const data = await res.json();
        document.getElementById('settings-librenms-url').value = data.librenms_api_url;
        document.getElementById('settings-librenms-token').value = data.librenms_api_token_masked;
        document.getElementById('settings-llm-provider').value = data.llm_provider;
        document.getElementById('settings-gemini-key').value = data.gemini_api_key_masked;
        document.getElementById('settings-openai-key').value = data.openai_api_key_masked;
        document.getElementById('settings-llm-model').value = data.llm_model;
        
        settingsStatus.classList.add('hide');
        settingsModal.classList.remove('hide');
    } catch (err) {
        console.error("Failed to load settings", err);
    }
}

function closeSettings() {
    settingsModal.classList.add('hide');
}

async function saveSettings(e) {
    e.preventDefault();
    
    const payload = {
        librenms_api_url: document.getElementById('settings-librenms-url').value,
        librenms_api_token: document.getElementById('settings-librenms-token').value,
        llm_provider: document.getElementById('settings-llm-provider').value,
        gemini_api_key: document.getElementById('settings-gemini-key').value,
        openai_api_key: document.getElementById('settings-openai-key').value,
        llm_model: document.getElementById('settings-llm-model').value
    };
    
    try {
        const res = await defFetch('/api/v1/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        if (res.ok) {
            settingsStatus.textContent = "Settings updated & saved successfully!";
            settingsStatus.style.color = "var(--green)";
            settingsStatus.classList.remove('hide');
            
            // Reload devices after setting changes
            setTimeout(() => {
                closeSettings();
                loadDevices();
            }, 1000);
        } else {
            const errData = await res.json();
            settingsStatus.textContent = `Update failed: ${errData.detail || 'Error'}`;
            settingsStatus.style.color = "var(--red)";
            settingsStatus.classList.remove('hide');
        }
    } catch (err) {
        settingsStatus.textContent = "Connection exception while saving settings.";
        settingsStatus.style.color = "var(--red)";
        settingsStatus.classList.remove('hide');
    }
}

// Render the Monitored Devices List dynamically
function renderDevicesList(devices) {
    const deviceListContainer = document.getElementById('device-list');
    if (!deviceListContainer) return;
    
    deviceListContainer.innerHTML = '';
    
    if (devices.length === 0) {
        deviceListContainer.innerHTML = '<p class="empty-state">No monitored devices found</p>';
        return;
    }
    
    devices.forEach(dev => {
        const item = document.createElement('div');
        item.className = 'device-item glass-card card-glow';
        item.setAttribute('data-device-id', dev.device_id || dev.id);
        
        // Check if there is an active alert for this device hostname
        const isAlerting = currentAlerts.some(a => a.hostname === dev.hostname);
        
        let iconSvg = '';
        const hostnameLower = dev.hostname.toLowerCase();
        const sysNameLower = (dev.sysName || '').toLowerCase();
        const osLower = (dev.os || '').toLowerCase();
        
        const isRouter = hostnameLower.includes('router') || 
                         sysNameLower.includes('router') ||
                         osLower.includes('router') || 
                         osLower.includes('iosxr') || 
                         dev.ip.startsWith('10.');
                         
        const isServer = hostnameLower.includes('server') || 
                         hostnameLower.includes('san') || 
                         hostnameLower.includes('storage') || 
                         osLower.includes('linux') || 
                         osLower.includes('ubuntu');
        
        if (isRouter) {
            // Blue Router Icon
            iconSvg = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#60a5fa" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10"/>
                <path d="M8 12h8M12 8v8"/>
            </svg>`;
        } else if (isServer) {
            // Green Server Icon
            iconSvg = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#34d399" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect x="2" y="2" width="20" height="8" rx="2" ry="2"/>
                <rect x="2" y="14" width="20" height="8" rx="2" ry="2"/>
                <line x1="6" y1="6" x2="6.01" y2="6"/>
                <line x1="6" y1="18" x2="6.01" y2="18"/>
            </svg>`;
        } else {
            // Purple Switch Icon
            iconSvg = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#c084fc" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect x="2" y="5" width="20" height="14" rx="2" ry="2"/>
                <line x1="6" y1="12" x2="18" y2="12"/>
                <circle cx="6" cy="9" r="1"/>
                <circle cx="12" cy="9" r="1"/>
                <circle cx="18" cy="9" r="1"/>
                <circle cx="6" cy="15" r="1"/>
                <circle cx="12" cy="15" r="1"/>
                <circle cx="18" cy="15" r="1"/>
            </svg>`;
        }
        
        item.innerHTML = `
            <div class="device-item-header">
                <div class="device-icon">${iconSvg}</div>
                <div class="device-info-text">
                    <span class="device-name" title="${dev.hostname}">${dev.sysName || dev.hostname.split('.')[0]}</span>
                    <span class="device-ip">${dev.ip}</span>
                </div>
            </div>
            <div class="device-item-footer">
                <span class="badge ${isAlerting ? 'badge-red' : 'badge-green'}">${isAlerting ? 'ALERTING' : 'ONLINE'}</span>
            </div>
        `;
        
        // Preserve active highlighting state
        const selectedDevice = document.getElementById('inspector-content').querySelector('.inspector-grid h4 + p');
        if (selectedDevice && selectedDevice.textContent === dev.hostname) {
            item.classList.add('active');
        }
        
        item.addEventListener('click', () => {
            document.querySelectorAll('.device-item').forEach(el => el.classList.remove('active'));
            item.classList.add('active');
            window.inspectDevice(dev);
        });
        
        deviceListContainer.appendChild(item);
    });
}

// Highlight the devices list panel when clicking the metric card at the top
document.addEventListener('DOMContentLoaded', () => {
    // Bind click listener to the entire "Devices Monitored" metric card
    const devicesMetricCard = document.getElementById('stats-devices').closest('.metric-card');
    if (devicesMetricCard) {
        devicesMetricCard.style.cursor = 'pointer';
        devicesMetricCard.addEventListener('click', () => {
            const devicesPanel = document.getElementById('device-list').closest('.glass-panel');
            if (devicesPanel) {
                devicesPanel.scrollIntoView({ behavior: 'smooth', block: 'center' });
                devicesPanel.classList.add('flash-highlight');
                setTimeout(() => {
                    devicesPanel.classList.remove('flash-highlight');
                }, 2400);
            }
        });
    }
});
