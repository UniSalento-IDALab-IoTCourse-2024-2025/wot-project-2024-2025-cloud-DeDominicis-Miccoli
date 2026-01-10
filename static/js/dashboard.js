// Dashboard JavaScript - Tempo Reale

// ========== AUTH & USER ==========
let currentUser = null;

// ========== VARIABILI GLOBALI ==========
const socket = io('/data');
let isAcquiring = false;
let deviceConnected = false;
let shouldUpdateCharts = false;
let shouldUpdateCounters = false;

let frozenStats = {
    ecg: 0,
    adc: 0,
    packets: 0,
    temp: '--'
};

let temperatureHistory = {
    values: [],
    times: []
};

let lastTemperature = null;
const MAX_TEMP_DISPLAY = 1200;

// ========== FUNZIONI LAYOUT GRAFICI ==========
const getChartLayout = (title, yAxisLabel = 'Value', xAxisLabel = 'Samples') => ({
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: '#0f172a',
    font: { 
        color: '#f8fafc',
        family: 'Inter, sans-serif',
        size: 11
    },
    xaxis: { 
        gridcolor: '#1e293b',
        title: xAxisLabel,
        titlefont: { size: 11 },
        showline: true,
        linecolor: '#334155',
        zeroline: false
    },
    yaxis: { 
        gridcolor: '#1e293b',
        title: yAxisLabel,
        titlefont: { size: 11 },
        showline: true,
        linecolor: '#334155',
        zeroline: false
    },
    margin: { l: 60, r: 30, t: 20, b: 50 },
    hovermode: 'closest',
    showlegend: true,
    legend: {
        x: 1,
        xanchor: 'right',
        y: 1,
        bgcolor: 'rgba(30, 41, 59, 0.9)',
        bordercolor: '#334155',
        borderwidth: 1,
        font: { size: 10 }
    }
});

const chartConfig = { 
    responsive: true,
    displayModeBar: true,
    modeBarButtonsToRemove: ['lasso2d', 'select2d', 'toImage'],
    displaylogo: false
};

// ========== INIZIALIZZAZIONE GRAFICI ==========
function initializeCharts() {
    Plotly.newPlot('ecgChart', [{
        y: [],
        type: 'scatter',
        mode: 'lines',
        line: { color: '#10b981', width: 1.5 },
        name: 'ECG',
        hovertemplate: 'Sample: %{x}<br>Value: %{y}<extra></extra>'
    }], getChartLayout('ECG Signal', 'Amplitude', 'Samples'), chartConfig);

    Plotly.newPlot('adcChart', [], getChartLayout('ADC Channels', 'Value', 'Samples'), chartConfig);

    Plotly.newPlot('tempChart', [{
        y: [],
        x: [],
        type: 'scatter',
        mode: 'lines+markers',
        line: { color: '#f59e0b', width: 2.5 },
        marker: { size: 7, color: '#f59e0b', line: { color: '#fff', width: 1 } },
        name: 'Temperature',
        hovertemplate: 'Time: %{x}<br>Temp: %{y:.1f}°C<extra></extra>'
    }], getChartLayout('Temperature', 'Temperature (°C)', 'Time (minutes)'), chartConfig);
}

// ========== GESTIONE NAVIGAZIONE ==========
function updateSidebarActive(viewId) {
    document.querySelectorAll('.nav-item').forEach(item => item.classList.remove('active'));
    const activeItem = document.getElementById('nav' + viewId.charAt(0).toUpperCase() + viewId.slice(1));
    if (activeItem) activeItem.classList.add('active');
}

function showRealtimeView() {
    document.querySelectorAll('.realtime-view, .history-view, .anomalies-view, .debug-view, .models-view, .user-management-view').forEach(view => {
        view.classList.remove('active');
    });
    document.getElementById('realtimeView').classList.add('active');
    updateSidebarActive('realtime');
    
    setTimeout(() => {
        Plotly.Plots.resize('ecgChart');
        Plotly.Plots.resize('adcChart');
        Plotly.Plots.resize('tempChart');
    }, 100);
}

function showHistoryView() {
    document.querySelectorAll('.realtime-view, .history-view, .anomalies-view, .debug-view, .models-view, .user-management-view').forEach(view => {
        view.classList.remove('active');
    });
    document.getElementById('historyView').classList.add('active');
    updateSidebarActive('history');
}

function showAnomaliesView() {
    document.querySelectorAll('.realtime-view, .history-view, .anomalies-view, .debug-view, .models-view, .user-management-view').forEach(view => {
        view.classList.remove('active');
    });
    document.getElementById('anomaliesView').classList.add('active');
    updateSidebarActive('anomalies');
}

function showDebugView() {
    document.querySelectorAll('.realtime-view, .history-view, .anomalies-view, .debug-view, .models-view, .user-management-view').forEach(view => {
        view.classList.remove('active');
    });
    document.getElementById('debugView').classList.add('active');
    updateSidebarActive('debug');
    
    // Initialize debug mode - load logs and setup SocketIO listener
    if (typeof loadDebugLogs === 'function') {
        loadDebugLogs();
        
        // Setup SocketIO listener for real-time logs (only once)
        if (!socket._debugListenerAdded) {
            socket.on('system_log', function(logEntry) {
                if (typeof addDebugLogToConsole === 'function') {
                    addDebugLogToConsole(logEntry);
                }
            });
            socket._debugListenerAdded = true;
        }
    }
}

function showModelsView() {
    document.querySelectorAll('.realtime-view, .history-view, .anomalies-view, .debug-view, .models-view, .user-management-view').forEach(view => {
        view.classList.remove('active');
    });
    document.getElementById('modelsView').classList.add('active');
    updateSidebarActive('models');
}

function toggleExpertMode() {
    const toggle = document.getElementById('expertModeToggle');
    const expertMenu = document.getElementById('expertMenu');
    
    if (toggle.checked) {
        expertMenu.style.display = 'block';
    } else {
        expertMenu.style.display = 'none';
    }
}

// ========== AGGIORNAMENTO GRAFICI ==========
function updateChart(signal, data) {
    const chartId = signal.toLowerCase() + 'Chart';
    
    if (!data || !data.y || data.y.length === 0) {
        return;
    }
    
    if (signal === 'ECG') {
        const yData = data.y[0] || [];
        Plotly.update(chartId, {
            y: [yData],
            x: [data.x || Array.from({length: yData.length}, (_, i) => i)]
        }, {}, [0]);
        
        document.getElementById('ecgDataPoints').textContent = `${yData.length} points`;
        
    } else if (signal === 'ADC') {
        const colors = ['#3b82f6', '#10b981', '#f59e0b', '#ec4899'];
        
        const traces = data.y.map((channelData, i) => ({
            y: channelData,
            x: data.x || Array.from({length: channelData.length}, (_, i) => i),
            type: 'scatter',
            mode: 'lines',
            name: `Channel ${i + 1}`,
            line: { 
                color: colors[i % colors.length], 
                width: 1.5 
            },
            hovertemplate: `CH${i+1}: %{y}<extra></extra>`
        }));
        
        Plotly.react(chartId, traces, getChartLayout('ADC Channels', 'Value', 'Samples'), chartConfig);
        
        const totalPoints = data.y[0] ? data.y[0].length : 0;
        document.getElementById('adcDataPoints').textContent = `${totalPoints} points`;
        
    } else if (signal === 'TEMP') {
        const tempData = data.y[0] || [];
        
        if (tempData.length > 0) {
            let rawValue = tempData[0];
            if (Array.isArray(rawValue)) {
                rawValue = rawValue[0];
            }
            
            const tempInCelsius = rawValue / 100;
            
            temperatureHistory.values.push(tempInCelsius);
            const elapsedMinutes = (temperatureHistory.values.length - 1) * 2;
            temperatureHistory.times.push(elapsedMinutes);
            
            document.getElementById('tempValue').textContent = tempInCelsius.toFixed(1);
            document.getElementById('tempDataPoints').textContent = `${temperatureHistory.values.length} points`;
            
            Plotly.react(chartId, [{
                y: [...temperatureHistory.values],
                x: [...temperatureHistory.times],
                type: 'scatter',
                mode: 'lines+markers',
                line: { color: '#f59e0b', width: 2.5 },
                marker: { 
                    size: 7, 
                    color: '#f59e0b', 
                    line: { color: '#fff', width: 1 } 
                },
                name: 'Temperature',
                hovertemplate: 'Time: %{x:.0f} min<br>Temp: %{y:.1f}°C<extra></extra>'
            }], getChartLayout('Temperature', 'Temperature (°C)', 'Time (minutes)'), chartConfig);
        }
    }
}

// ========== AGGIORNAMENTO STATISTICHE ==========
function updateStatistics(data) {
    if (!shouldUpdateCounters) {
        console.log('Counters frozen - skipping update');
        return;
    }
    
    if (data.stats.TEMP.current_temp !== null) {
        const tempC = data.stats.TEMP.current_temp / 100;
        document.getElementById('tempValue').textContent = tempC.toFixed(1);
        frozenStats.temp = tempC.toFixed(1);
        
        if (lastTemperature === null || Math.abs(tempC - lastTemperature) > 0.01) {
            lastTemperature = tempC;
            
            temperatureHistory.values.push(tempC);
            const elapsedMinutes = (temperatureHistory.values.length - 1) * 2;
            temperatureHistory.times.push(elapsedMinutes);
            
            const displayValues = temperatureHistory.values.slice(-MAX_TEMP_DISPLAY);
            const displayTimes = temperatureHistory.times.slice(-MAX_TEMP_DISPLAY);
            
            document.getElementById('tempDataPoints').textContent = `${temperatureHistory.values.length} points`;
            
            Plotly.react('tempChart', [{
                y: [...displayValues],
                x: [...displayTimes],
                type: 'scatter',
                mode: 'lines+markers',
                line: { color: '#f59e0b', width: 2.5 },
                marker: { 
                    size: 7, 
                    color: '#f59e0b', 
                    line: { color: '#fff', width: 1 } 
                },
                name: 'Temperature',
                hovertemplate: 'Time: %{x:.0f} min<br>Temp: %{y:.1f}°C<extra></extra>'
            }], getChartLayout('Temperature', 'Temperature (°C)', 'Time (minutes)'), chartConfig);
        }
    }
    
    // Counters removed from cloud version
    frozenStats.ecg = data.stats.ECG.samples;
    frozenStats.adc = data.stats.ADC.samples;
    frozenStats.packets = data.packet_count;
}

// ========== AGGIORNAMENTO STATUS ==========
function updateMqttStatus(connected) {
    const badge = document.getElementById('mqttStatus');
    
    if (connected) {
        badge.className = 'status-indicator status-connected';
        badge.innerHTML = '<span class="status-dot"></span><span>MQTT Connected</span>';
    } else {
        badge.className = 'status-indicator status-disconnected';
        badge.innerHTML = '<span class="status-dot"></span><span>MQTT Disconnected</span>';
    }
}

function updateDeviceStatus(connected) {
    const badge = document.getElementById('deviceStatus');
    
    if (connected) {
        badge.className = 'status-indicator status-connected';
        badge.innerHTML = '<span class="status-dot"></span><span>Connected</span>';
    } else {
        badge.className = 'status-indicator status-disconnected';
        badge.innerHTML = '<span class="status-dot"></span><span>Disconnected</span>';
    }
}

function updateAcquisitionStatus(acquiring) {
    const badge = document.getElementById('acquisitionStatus');
    
    if (acquiring) {
        badge.className = 'status-indicator status-acquiring';
        badge.innerHTML = '<span class="status-dot"></span><span>Acquiring</span>';
    } else {
        badge.className = 'status-indicator status-idle';
        badge.innerHTML = '<span class="status-dot"></span><span>Idle</span>';
    }
}

// ========== MODAL RESET ==========
function showResetModal() {
    document.getElementById('resetModal').classList.add('show');
}

function closeResetModal() {
    document.getElementById('resetModal').classList.remove('show');
}

function confirmReset() {
    closeResetModal();
    performReset();
}

function performReset() {
    console.log('Resetting dashboard...');
    
    temperatureHistory = {
        values: [],
        times: []
    };
    lastTemperature = null;
    
    frozenStats = {
        ecg: 0,
        adc: 0,
        packets: 0,
        temp: '--'
    };
    
    document.getElementById('tempValue').textContent = '--';
    // Counters removed from cloud version
    document.getElementById('ecgDataPoints').textContent = '0 points';
    document.getElementById('adcDataPoints').textContent = '0 points';
    document.getElementById('tempDataPoints').textContent = '0 points';
    
    Plotly.react('ecgChart', [{
        y: [],
        type: 'scatter',
        mode: 'lines',
        line: { color: '#10b981', width: 1.5 },
        name: 'ECG',
        hovertemplate: 'Sample: %{x}<br>Value: %{y}<extra></extra>'
    }], getChartLayout('ECG Signal', 'Amplitude', 'Samples'), chartConfig);
    
    Plotly.react('adcChart', [], getChartLayout('ADC Channels', 'Value', 'Samples'), chartConfig);
    
    Plotly.react('tempChart', [{
        y: [],
        x: [],
        type: 'scatter',
        mode: 'lines+markers',
        line: { color: '#f59e0b', width: 2.5 },
        marker: { size: 7, color: '#f59e0b', line: { color: '#fff', width: 1 } },
        name: 'Temperature',
        hovertemplate: 'Time: %{x:.0f} min<br>Temp: %{y:.1f}°C<extra></extra>'
    }], getChartLayout('Temperature', 'Temperature (°C)', 'Time (minutes)'), chartConfig);
    
    console.log('Dashboard reset complete');
}

// ========== EVENTI SOCKETIO ==========
socket.on('connect', () => {
    console.log('Connected to server');
});

socket.on('disconnect', () => {
    console.log('Disconnected from server');
});

socket.on('data_update', (data) => {
    if (data.signal === 'TEMP') {
        updateChart(data.signal, data.data);
    } else {
        if (shouldUpdateCharts) {
            updateChart(data.signal, data.data);
        }
    }
});

socket.on('status_update', (data) => {
    updateStatistics(data);
});

socket.on('device_status', (data) => {
    deviceConnected = data.connected;
    updateDeviceStatus(data.connected);
});

socket.on('acquisition_status', (data) => {
    isAcquiring = data.acquiring;
    shouldUpdateCharts = data.acquiring;
    shouldUpdateCounters = data.acquiring;
    updateAcquisitionStatus(data.acquiring);
});

// ========== AUTH & LOGOUT FUNCTIONS ==========
async function checkAuth() {
    const token = localStorage.getItem('auth_token');
    
    if (!token) {
        window.location.href = '/login';
        return null;
    }
    
    try {
        const response = await fetch('/api/auth/verify', {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        
        const data = await response.json();
        
        if (!data.success) {
            localStorage.removeItem('auth_token');
            localStorage.removeItem('user');
            window.location.href = '/login';
            return null;
        }
        
        return data.user;
    } catch (error) {
        console.error('Auth check error:', error);
        window.location.href = '/login';
        return null;
    }
}

function handleLogout() {
    const token = localStorage.getItem('auth_token');
    
    if (token) {
        fetch('/api/auth/logout', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`
            }
        }).then(() => {
            localStorage.removeItem('auth_token');
            localStorage.removeItem('user');
            window.location.href = '/login';
        }).catch(() => {
            localStorage.removeItem('auth_token');
            localStorage.removeItem('user');
            window.location.href = '/login';
        });
    } else {
        window.location.href = '/login';
    }
}

function updateUIForUser(user) {
    currentUser = user;
    
    // Update user display
    document.getElementById('userDisplayName').textContent = `${user.nome} ${user.cognome}`;
    document.getElementById('userRole').textContent = user.ruolo;
    
    // Show/hide expert mode based on role (ONLY ADMIN)
    const expertModeSection = document.getElementById('expertModeSection');
    if (user.ruolo === 'admin') {
        expertModeSection.style.display = 'block';
    } else {
        expertModeSection.style.display = 'none';
    }
}

// ========== GESTIONE PULSANTI ==========
document.addEventListener('DOMContentLoaded', async function() {
    // Check authentication FIRST
    const user = await checkAuth();
    if (!user) return; // Redirect already handled
    
    // Update UI for logged in user
    updateUIForUser(user);
    
    // Inizializza grafici
    initializeCharts();
    
    // Start button - DISABLED on cloud (controlled from Raspberry)
    document.getElementById('btnStart').addEventListener('click', () => {
        alert('Acquisition control is managed from the Raspberry Pi device.');
    });

    // Stop button - DISABLED on cloud (controlled from Raspberry)
    document.getElementById('btnStop').addEventListener('click', () => {
        alert('Acquisition control is managed from the Raspberry Pi device.');
    });

    // Reset button - Only resets cloud view

    // Richieste dati iniziali
    socket.emit('request_data', { signal: 'ECG' });
    socket.emit('request_data', { signal: 'ADC' });
    socket.emit('request_data', { signal: 'TEMP' });

    // Polling status periodico
    setInterval(() => {
        fetch('/api/status')
            .then(r => r.json())
            .then(data => {
                // updateMqttStatus removed - not in cloud HTML
                updateDeviceStatus(data.device_connected);
                updateAcquisitionStatus(data.is_acquiring);
                updateStatistics(data);
                shouldUpdateCharts = data.is_acquiring;
                shouldUpdateCounters = true;      
                  })
            .catch(err => console.error('Status update error:', err));
    }, 5000);
});
// ========================================
// UNIVERSAL MODAL FUNCTIONS
// ========================================

// Replace alert() with custom modal
window.showAlert = function(message, title = 'Attenzione') {
    const modal = document.getElementById('messageModal');
    if (!modal) {
        alert(message);
        return;
    }
    
    const modalTitle = modal.querySelector('.modal-title');
    const modalBody = modal.querySelector('.modal-body');
    
    if (modalTitle) modalTitle.textContent = title;
    if (modalBody) modalBody.textContent = message;
    
    modal.classList.add('show');
};

// Replace confirm() with custom modal
window.showConfirm = function(message, title = 'Conferma') {
    return new Promise((resolve) => {
        const modal = document.getElementById('confirmModal');
        if (!modal) {
            resolve(confirm(message));
            return;
        }
        
        const modalTitle = modal.querySelector('.modal-title');
        const modalBody = modal.querySelector('.modal-body');
        
        if (modalTitle) modalTitle.textContent = title;
        if (modalBody) modalBody.textContent = message;
        
        // Store resolve function globally
        window._confirmResolve = resolve;
        
        modal.classList.add('show');
    });
};

window.closeConfirmModal = function(result) {
    const modal = document.getElementById('confirmModal');
    if (modal) modal.classList.remove('show');
    
    if (window._confirmResolve) {
        window._confirmResolve(result);
        window._confirmResolve = null;
    }
};

console.log('[Dashboard] Universal modal functions loaded');