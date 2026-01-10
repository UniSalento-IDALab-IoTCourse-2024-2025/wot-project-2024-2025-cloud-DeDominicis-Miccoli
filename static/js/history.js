// History JavaScript - Gestione Storico Dati (Versione Ottimizzata)

// ========== VARIABILI GLOBALI STORICO ==========
let availableSessions = [];
let selectedSession = null;
let currentWindowSize = 1000;
let currentPosition = 0;
let totalDataCount = 0;
let maxSliderPosition = 0;

// ========== FUNZIONI TIMESTAMP (da locale) ==========
function formatTimestamp(milliseconds, format = 'full') {
    const date = new Date(milliseconds);
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    const seconds = String(date.getSeconds()).padStart(2, '0');
    
    if (format === 'minutes') {
        return `${hours}:${minutes}`;
    }
    return `${hours}:${minutes}:${seconds}`;
}

function calculateTimestampsForSamples(startSampleIndex, numSamples, sampleRate, sessionStartTime) {
    const timestamps = [];
    const sessionStartMs = new Date(sessionStartTime).getTime();
    
    for (let i = 0; i < numSamples; i++) {
        const sampleIndex = startSampleIndex + i;
        const sampleTimeMs = sessionStartMs + (sampleIndex / sampleRate) * 1000;
        timestamps.push(formatTimestamp(sampleTimeMs));
    }
    
    return timestamps;
}

// ========== NAVIGAZIONE VISTA STORICO ==========
function showHistoryView() {
    // Cloud version - hide ALL views including expert mode
    document.querySelectorAll('.realtime-view, .history-view, .anomalies-view, .debug-view, .models-view, .user-management-view').forEach(view => {
        view.classList.remove('active');
    });
    document.getElementById('historyView').classList.add('active');
    
    loadAvailableDates();
}

// ========== CARICAMENTO DATE DISPONIBILI ==========
async function loadAvailableDates() {
    console.log('[History] loadAvailableDates called');
    const dateSelect = document.getElementById('dateSelect');
    
    if (!dateSelect) {
        console.error('[History] dateSelect element not found!');
        return;
    }
    
    console.log('[History] dateSelect found:', dateSelect);
    dateSelect.innerHTML = '<option value="">Caricamento...</option>';
    
    try {
        const response = await fetch('/api/history/dates');
        const data = await response.json();
        
        console.log('[History] Dates loaded:', data);
        
        if (data.dates && data.dates.length > 0) {
            dateSelect.innerHTML = '<option value="">Seleziona una data</option>';
            data.dates.forEach(date => {
                const option = document.createElement('option');
                option.value = date.value;
                option.textContent = date.label;
                dateSelect.appendChild(option);
            });
        } else {
            dateSelect.innerHTML = '<option value="">Nessuna data disponibile</option>';
        }
    } catch (error) {
        console.error('[History] Error loading dates:', error);
        dateSelect.innerHTML = '<option value="">Errore nel caricamento</option>';
    }
    
    // Remove old listener if exists
    dateSelect.onchange = null;
    
    // Add event listener
    dateSelect.addEventListener('change', function() {
        console.log('[History] Date changed to:', this.value);
        if (this.value) {
            loadSessionsForDate(this.value);
        } else {
            document.getElementById('historySessions').style.display = 'none';
            hideHistoryData();
        }
    });
    
    console.log('[History] Event listener attached to dateSelect');
}

// ========== CARICAMENTO SESSIONI PER DATA ==========
async function loadSessionsForDate(dateStr) {
    console.log('[History] loadSessionsForDate called with:', dateStr);
    const sessionsList = document.getElementById('historySessions');
    
    if (!sessionsList) {
        console.error('[History] sessionsList element not found!');
        return;
    }
    
    sessionsList.innerHTML = '<p style="text-align: center; color: var(--text-secondary);">Caricamento sessioni...</p>';
    sessionsList.style.display = 'block';
    
    try {
        const url = `/api/history/sessions/${dateStr}`;
        console.log('[History] Fetching sessions from:', url);
        
        const response = await fetch(url);
        console.log('[History] Response status:', response.status);
        
        const data = await response.json();
        console.log('[History] Sessions data:', data);
        
        if (data.sessions && data.sessions.length > 0) {
            availableSessions = data.sessions;
            console.log('[History] Rendering', data.sessions.length, 'sessions');
            renderSessionsList(data.sessions);
        } else {
            console.warn('[History] No sessions found');
            sessionsList.innerHTML = `
                <div class="empty-state">
                    <p>Nessuna sessione trovata per questa data</p>
                </div>
            `;
        }
    } catch (error) {
        console.error('[History] Error loading sessions:', error);
        sessionsList.innerHTML = `
            <div class="empty-state">
                <p style="color: var(--danger);">Errore nel caricamento delle sessioni</p>
            </div>
        `;
    }
}

// ========== RENDERING LISTA SESSIONI ==========
function renderSessionsList(sessions) {
    const sessionsList = document.getElementById('historySessions');
    sessionsList.innerHTML = '';
    
    sessions.forEach(session => {
        const sessionCard = document.createElement('div');
        sessionCard.className = 'session-card';
        sessionCard.onclick = () => selectSession(session, sessionCard);
        
        const startTime = new Date(session.start_time);
        const endTime = session.end_time ? new Date(session.end_time) : null;
        const duration = endTime ? Math.round((endTime - startTime) / 60000) : 'In corso';
        
        sessionCard.innerHTML = `
            <div class="session-info">
                <div class="session-time">
                    ${startTime.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                </div>
                <div class="session-details">
                    Durata: ${typeof duration === 'number' ? duration + ' min' : duration}
                    ECG: ${session.total_samples.ECG.toLocaleString()} 
                    ADC: ${session.total_samples.ADC.toLocaleString()} 
                    TEMP: ${session.total_samples.TEMP.toLocaleString()}
                </div>
            </div>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="9 18 15 12 9 6"/>
            </svg>
        `;
        
        sessionsList.appendChild(sessionCard);
    });
}

// ========== SELEZIONE SESSIONE ==========
function selectSession(session, cardElement) {
    console.log('[History] selectSession called with:', session);
    selectedSession = session;
    
    document.querySelectorAll('.session-card').forEach(card => {
        card.classList.remove('selected');
    });
    cardElement.classList.add('selected');
    
    const btnLoad = document.getElementById('btnLoadHistory');
    if (btnLoad) {
        btnLoad.disabled = false;
        console.log('[History] Load button enabled');
    } else {
        console.error('[History] btnLoadHistory not found!');
    }
}

// ========== CARICAMENTO DATI STORICI (OTTIMIZZATO) ==========
async function loadHistoricalData() {
    console.log('[History] loadHistoricalData called');
    console.log('[History] selectedSession:', selectedSession);
    
    if (!selectedSession) {
        console.warn('[History] No session selected');
        showMessageModal('Attenzione', 'Seleziona prima una sessione dalla lista');
        return;
    }
    
    const signalSelect = document.getElementById('signalSelect');
    const signal = signalSelect ? signalSelect.value : 'ECG';
    const btnLoad = document.getElementById('btnLoadHistory');
    
    console.log('[History] Signal selected:', signal);
    console.log('[History] Button found:', btnLoad);
    
    if (btnLoad) {
        btnLoad.disabled = true;
        btnLoad.innerHTML = '<span class="loading-spinner"></span> Caricamento...';
    }
    
    try {
        // NUOVA API: Usa la paginazione backend
        const url = `/api/history/window/${selectedSession.session_id}/${signal}?position=0&window_size=${currentWindowSize}`;
        console.log('[History] Fetching:', url);
        
        const response = await fetch(url);
        console.log('[History] Response status:', response.status);
        
        const data = await response.json();
        console.log('[History] Response data:', data);
        
        if (data.total_count > 0) {
            console.log('[History] Displaying data...');
            displayHistoricalData(data, signal);
        } else {
            console.warn('[History] No data found');
            showMessageModal('Nessun Dato', 'Nessun dato trovato per questo segnale');
            hideHistoryData();
        }
    } catch (error) {
        console.error('[History] Error loading historical data:', error);
        showMessageModal('Errore', 'Errore nel caricamento dei dati');
        hideHistoryData();
    } finally {
        if (btnLoad) {
            btnLoad.disabled = false;
            btnLoad.innerHTML = `
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                    <polyline points="7 10 12 15 17 10"/>
                    <line x1="12" y1="15" x2="12" y2="3"/>
                </svg>
                Carica Dati
            `;
        }
    }
}

// ========== VISUALIZZAZIONE DATI STORICI ==========
function displayHistoricalData(data, signal) {
    // Salva info totali
    totalDataCount = data.total_count || 0;
    
    // FIXED: Calculate window positions from response
    const windowStart = currentPosition;
    const windowEnd = Math.min(currentPosition + data.count, totalDataCount);
    maxSliderPosition = Math.max(0, totalDataCount - currentWindowSize);
    
    document.getElementById('emptyHistoryState').style.display = 'none';
    
    const statsGrid = document.getElementById('historyStatsGrid');
    statsGrid.style.display = 'grid';
    
    document.getElementById('histSessionId').textContent = selectedSession.session_id;
    document.getElementById('histDataPoints').textContent = (totalDataCount || 0).toLocaleString();
    
    const startTime = new Date(selectedSession.start_time);
    const endTime = selectedSession.end_time ? new Date(selectedSession.end_time) : null;
    
    document.getElementById('histStartTime').textContent = 
        startTime.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' });
    document.getElementById('histEndTime').textContent = 
        endTime ? endTime.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' }) : 'In corso';
    
    document.getElementById('historyChartsContainer').style.display = 'block';
    
    const signalNames = {
        'ECG': 'ECG Signal',
        'ADC': 'ADC Channels',
        'TEMP': 'Temperature'
    };
    document.getElementById('historyChartTitle').textContent = signalNames[signal];
    
    // Configura slider
    const slider = document.getElementById('dataSlider');
    slider.max = maxSliderPosition;
    slider.value = currentPosition;
    
    // Renderizza grafico - FIXED: Pass calculated window positions
    renderHistoricalChart(data.data, signal, windowStart, windowEnd);
}

// ========== CAMBIO DIMENSIONE FINESTRA (OTTIMIZZATO) ==========
async function changeWindowSize(newSize) {
    document.querySelectorAll('.btn-control-small').forEach(btn => {
        btn.classList.remove('active');
    });
    event.target.classList.add('active');
    
    if (newSize === -1) {
        currentWindowSize = totalDataCount;
        currentPosition = 0;
    } else {
        currentWindowSize = newSize;
        if (currentPosition + currentWindowSize > totalDataCount) {
            currentPosition = Math.max(0, totalDataCount - currentWindowSize);
        }
    }
    
    // Ricarica dati con nuova dimensione finestra
    await reloadWindowedData();
}

// ========== NAVIGAZIONE DATI (OTTIMIZZATO) ==========
async function navigateData(direction) {
    const step = Math.floor(currentWindowSize / 2);
    
    switch(direction) {
        case 'start':
            currentPosition = 0;
            break;
        case 'prev':
            currentPosition = Math.max(0, currentPosition - step);
            break;
        case 'next':
            currentPosition = Math.min(maxSliderPosition, currentPosition + step);
            break;
        case 'end':
            currentPosition = maxSliderPosition;
            break;
    }
    
    document.getElementById('dataSlider').value = currentPosition;
    
    // Ricarica dati dalla nuova posizione
    await reloadWindowedData();
}

// ========== NAVIGAZIONE CON SLIDER (OTTIMIZZATO) ==========
async function sliderNavigation(value) {
    currentPosition = parseInt(value);
    await reloadWindowedData();
}

// ========== RICARICA FINESTRA DATI (NUOVA FUNZIONE) ==========
async function reloadWindowedData() {
    const signal = document.getElementById('signalSelect').value;
    
    try {
        // Richiedi solo la finestra corrente al backend
        const response = await fetch(
            `/api/history/window/${selectedSession.session_id}/${signal}?position=${currentPosition}&window_size=${currentWindowSize}`
        );
        const data = await response.json();
        
        if (data.total_count > 0) {
            // Update totalDataCount
            totalDataCount = data.total_count;
            maxSliderPosition = Math.max(0, totalDataCount - currentWindowSize);
            
            // Aggiorna slider
            const slider = document.getElementById('dataSlider');
            slider.max = maxSliderPosition;
            slider.value = currentPosition;
            
            // Calculate window positions
            const windowStart = currentPosition;
            const windowEnd = Math.min(currentPosition + data.count, totalDataCount);
            
            // Renderizza nuovo grafico
            renderHistoricalChart(data.data, signal, windowStart, windowEnd);
        }
    } catch (error) {
        console.error('Error reloading windowed data:', error);
    }
}

// ========== RENDERING GRAFICO STORICO (SEMPLIFICATO) ==========
function renderHistoricalChart(chartData, signal, windowStart, windowEnd) {
    const colors = ['#10b981', '#3b82f6', '#f59e0b', '#ec4899'];
    
    // FIXED: Handle undefined values safely
    const safeWindowStart = windowStart ?? 0;
    const safeWindowEnd = windowEnd ?? 0;
    const safeTotalCount = totalDataCount ?? 0;
    
    // Aggiorna indicatore navigazione
    document.getElementById('navIndicator').textContent = 
        `${safeWindowStart.toLocaleString()} - ${safeWindowEnd.toLocaleString()} di ${safeTotalCount.toLocaleString()}`;
    
    // ========== CALCOLO TIMESTAMP (logica da locale) ==========
    // Determina sample rate
    let sampleRate;
    if (signal === 'ECG' || signal === 'ADC') {
        sampleRate = 250; // Hz
    } else if (signal === 'TEMP') {
        sampleRate = 1; // Hz (1 sample/secondo)
    }
    
    // Calcola timestamp per display (solo per il range label)
    const numSamples = chartData.x ? chartData.x.length : (chartData.y[0] ? chartData.y[0].length : 0);
    const sessionStartMs = selectedSession && selectedSession.start_time ? new Date(selectedSession.start_time).getTime() : Date.now();
    
    let firstSampleMs, lastSampleMs;
    
    if (signal === 'TEMP') {
        // TEMP: usa durata reale sessione (da ECG/ADC), non i sample TEMP
        // I sample TEMP sono campionati lentamente (1 Hz) ma la sessione ha durata ECG/ADC
        const sessionEndMs = selectedSession && selectedSession.end_time ? new Date(selectedSession.end_time).getTime() : sessionStartMs;
        const sessionDurationMs = sessionEndMs - sessionStartMs;
        
        // Calcola posizione proporzionale nella sessione
        const progressRatio = currentPosition / safeTotalCount;
        const windowRatio = numSamples / safeTotalCount;
        
        firstSampleMs = sessionStartMs + (sessionDurationMs * progressRatio);
        lastSampleMs = sessionStartMs + (sessionDurationMs * (progressRatio + windowRatio));
    } else {
        // ECG/ADC: usa sample rate normale
        firstSampleMs = sessionStartMs + (currentPosition / sampleRate) * 1000;
        lastSampleMs = sessionStartMs + ((currentPosition + numSamples - 1) / sampleRate) * 1000;
    }
    
    const startLabel = formatTimestamp(firstSampleMs);
    const endLabel = formatTimestamp(lastSampleMs);
    
    // USA INDICI NUMERICI per l'asse X (mantiene la forma del grafico)
    const xIndices = Array.from({length: numSamples}, (_, i) => i);
    
    // ========== FINE CALCOLO TIMESTAMP ==========
    
    let traces = [];
    
    if (signal === 'TEMP') {
        const yData = chartData.y[0] || [];
        if (yData.length === 0) {
            console.warn('[History] No TEMP data to display');
            return;
        }
        traces.push({
            y: yData,
            x: xIndices,
            type: 'scatter',
            mode: 'lines+markers',
            line: { color: '#f59e0b', width: 2 },
            marker: { size: 4, color: '#f59e0b' },
            name: 'Temperature',
            hovertemplate: 'Sample: %{x}<br>Temp: %{y:.1f}°C<extra></extra>'
        });
    } else if (signal === 'ECG') {
        const yData = chartData.y[0] || [];
        if (yData.length === 0) {
            console.warn('[History] No ECG data to display');
            return;
        }
        traces.push({
            y: yData,
            x: xIndices,
            type: 'scatter',
            mode: 'lines',
            line: { color: '#10b981', width: 1 },
            name: 'ECG',
            hovertemplate: 'Sample: %{x}<br>Value: %{y}<extra></extra>'
        });
    } else if (signal === 'ADC') {
        if (!chartData.y || chartData.y.length === 0) {
            console.warn('[History] No ADC data to display');
            return;
        }
        chartData.y.forEach((channelData, i) => {
            traces.push({
                y: channelData,
                x: xIndices,
                type: 'scatter',
                mode: 'lines',
                line: { color: colors[i % colors.length], width: 1 },
                name: `Channel ${i + 1}`,
                hovertemplate: `CH${i+1}: %{y}<extra></extra>`
            });
        });
    }
    
    const layout = {
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: '#0f172a',
        font: { 
            color: '#f8fafc',
            family: 'Inter, sans-serif',
            size: 11
        },
        xaxis: { 
            gridcolor: '#1e293b',
            title: `Time (${startLabel} - ${endLabel})`,
            showline: true,
            linecolor: '#334155',
            zeroline: false
        },
        yaxis: { 
            gridcolor: '#1e293b',
            title: signal === 'TEMP' ? 'Temperature (°C)' : 'Value',
            showline: true,
            linecolor: '#334155',
            zeroline: false
        },
        margin: { l: 60, r: 30, t: 20, b: 50 },
        hovermode: 'closest',
        showlegend: signal === 'ADC' || signal === 'TEMP',
        legend: {
            x: 1,
            xanchor: 'right',
            y: 1,
            bgcolor: 'rgba(30, 41, 59, 0.9)',
            bordercolor: '#334155',
            borderwidth: 1,
            font: { size: 10 }
        }
    };
    
    const config = { 
        responsive: true,
        displayModeBar: true,
        modeBarButtonsToRemove: ['lasso2d', 'select2d'],
        displaylogo: false
    };
    
    Plotly.newPlot('historyChart', traces, layout, config);
}

// ========== NASCONDI DATI STORICI ==========
function hideHistoryData() {
    document.getElementById('historyStatsGrid').style.display = 'none';
    document.getElementById('historyChartsContainer').style.display = 'none';
    document.getElementById('emptyHistoryState').style.display = 'block';
    
    // Reset variabili
    totalDataCount = 0;
    maxSliderPosition = 0;
    currentPosition = 0;
}

// ========== MODAL MESSAGGI (RIUTILIZZA MODAL ESISTENTE) ==========
function showMessageModal(title, message, isWarning = true) {
    const modal = document.getElementById('messageModal');
    if (!modal) return;
    console.log("[History] showMessageModal called:", title, message);
    if (!modal) { console.error("[History] messageModal not found!"); return; }
    
    // Salva contenuto originale se necessario
    const modalTitle = modal.querySelector('.modal-title');
    const modalBody = modal.querySelector('.modal-body');
    const modalIcon = modal.querySelector('.modal-icon svg');
    const modalFooter = modal.querySelector('.modal-footer');
    
    // Modifica contenuto
    modalTitle.textContent = title;
    modalBody.textContent = message;
    
    // Cambia icona
    if (isWarning) {
        modalIcon.innerHTML = `
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
            <line x1="12" y1="9" x2="12" y2="13"/>
            <line x1="12" y1="17" x2="12.01" y2="17"/>
        `;
    } else {
        modalIcon.innerHTML = `
            <circle cx="12" cy="12" r="10"/>
            <line x1="12" y1="8" x2="12" y2="12"/>
            <line x1="12" y1="16" x2="12.01" y2="16"/>
        `;
    }
    
    // Mostra solo pulsante OK
    modalFooter.innerHTML = `
        <button class="btn-modal btn-modal-confirm" onclick="closeMessageModal()">OK</button>
    `;
    
    // Mostra modal
    modal.classList.add('show');
}

function closeMessageModal() {
    const modal = document.getElementById('messageModal');
    if (!modal) return;
    
    modal.classList.remove('show');

}
// ========================================
// EXPORT FUNCTIONS TO WINDOW (for onclick)
// ========================================
window.showHistoryView = showHistoryView;
window.loadAvailableDates = loadAvailableDates;
window.loadSessionsForDate = loadSessionsForDate;
window.selectSession = selectSession;
window.loadHistoricalData = loadHistoricalData;
window.hideHistoryData = hideHistoryData;
window.closeMessageModal = closeMessageModal;

console.log('[History] Functions exported to window');