// Anomalies JavaScript - Gestione Storico Anomalie (ECG, PIEZO, TEMP)

// ========== VARIABILI GLOBALI ANOMALIE ==========
let anomaliesData = {
    ecg: [],
    piezo: [],
    temp: []
};
let currentAnomalyFilter = 'all'; // 'all', 'ecg', 'piezo', 'temp'

// ========== NAVIGAZIONE VISTA ANOMALIE ==========
function showAnomaliesView() {
    // Cloud version - hide ALL views including expert mode
    document.querySelectorAll('.realtime-view, .history-view, .anomalies-view, .debug-view, .models-view, .user-management-view').forEach(view => {
        view.classList.remove('active');
    });
    document.getElementById('anomaliesView').classList.add('active');
    
    loadAnomalyDates();
    loadAnomalySummary();
}

// ========== CARICAMENTO DATE DISPONIBILI ==========
async function loadAnomalyDates() {
    const dateSelect = document.getElementById('anomalyDateSelect');
    dateSelect.innerHTML = '<option value="">Caricamento...</option>';
    
    try {
        const response = await fetch('/api/anomalies/dates');
        const data = await response.json();
        
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
        console.error('Error loading anomaly dates:', error);
        dateSelect.innerHTML = '<option value="">Errore nel caricamento</option>';
    }
    
    dateSelect.onchange = function() {
        if (this.value) {
            loadAnomaliesForDate(this.value);
        } else {
            hideAnomaliesData();
        }
    };
}

// ========== CARICAMENTO SUMMARY ANOMALIE ==========
async function loadAnomalySummary() {
    try {
        const response = await fetch('/api/anomalies/summary');
        const data = await response.json();
        
        document.getElementById('totalEcgAnomalies').textContent = (data.total_ecg || 0).toLocaleString();
        document.getElementById('totalPiezoAnomalies').textContent = (data.total_piezo || 0).toLocaleString();
        document.getElementById('totalTempAnomalies').textContent = (data.total_temp || 0).toLocaleString();
        document.getElementById('totalAllAnomalies').textContent = (data.total || 0).toLocaleString();
    } catch (error) {
        console.error('Error loading anomaly summary:', error);
    }
}

// ========== CARICAMENTO ANOMALIE PER DATA ==========
async function loadAnomaliesForDate(dateStr) {
    const anomaliesList = document.getElementById('anomaliesList');
    anomaliesList.innerHTML = '<p style="text-align: center; color: var(--text-secondary);">Caricamento anomalie...</p>';
    
    document.getElementById('anomaliesListContainer').style.display = 'block';
    document.getElementById('emptyAnomaliesState').style.display = 'none';
    
    try {
        const response = await fetch(`/api/anomalies/data/${dateStr}`);
        const data = await response.json();
        
        anomaliesData.ecg = data.ecg_anomalies || [];
        anomaliesData.piezo = data.piezo_anomalies || [];
        anomaliesData.temp = data.temp_anomalies || [];
        
        // Aggiorna contatori per la data selezionata
        document.getElementById('dateEcgCount').textContent = data.ecg_count || 0;
        document.getElementById('datePiezoCount').textContent = data.piezo_count || 0;
        document.getElementById('dateTempCount').textContent = data.temp_count || 0;
        document.getElementById('dateTotalCount').textContent = data.total_count || 0;
        
        document.getElementById('selectedDateStats').style.display = 'grid';
        
        if (data.total_count > 0) {
            renderAnomaliesList();
        } else {
            anomaliesList.innerHTML = `
                <div class="empty-state" style="padding: 2rem;">
                    <p>Nessuna anomalia trovata per questa data</p>
                </div>
            `;
        }
    } catch (error) {
        console.error('Error loading anomalies:', error);
        anomaliesList.innerHTML = `
            <div class="empty-state" style="padding: 2rem;">
                <p style="color: var(--danger);">Errore nel caricamento delle anomalie</p>
            </div>
        `;
    }
}

// ========== FILTRO ANOMALIE ==========
function filterAnomalies(type) {
    currentAnomalyFilter = type;
    
    // Aggiorna bottoni attivi
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    event.target.classList.add('active');
    
    renderAnomaliesList();
}

// ========== RENDERING LISTA ANOMALIE ==========
function renderAnomaliesList() {
    const anomaliesList = document.getElementById('anomaliesList');
    anomaliesList.innerHTML = '';
    
    let allAnomalies = [];
    
    // Combina anomalie in base al filtro
    if (currentAnomalyFilter === 'all' || currentAnomalyFilter === 'ecg') {
        anomaliesData.ecg.forEach(a => {
            allAnomalies.push({...a, type: 'ECG'});
        });
    }
    
    if (currentAnomalyFilter === 'all' || currentAnomalyFilter === 'piezo') {
        anomaliesData.piezo.forEach(a => {
            allAnomalies.push({...a, type: 'PIEZO'});
        });
    }
    
    if (currentAnomalyFilter === 'all' || currentAnomalyFilter === 'temp') {
        anomaliesData.temp.forEach(a => {
            allAnomalies.push({...a, type: 'TEMP'});
        });
    }
    
    // Ordina per timestamp (più recenti prima)
    allAnomalies.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
    
    if (allAnomalies.length === 0) {
        anomaliesList.innerHTML = `
            <div class="empty-state" style="padding: 2rem;">
                <p>Nessuna anomalia per questo filtro</p>
            </div>
        `;
        return;
    }
    
    allAnomalies.forEach((anomaly, index) => {
        const card = createAnomalyCard(anomaly, index);
        anomaliesList.appendChild(card);
    });
}

// ========== CREAZIONE CARD ANOMALIA ==========
function createAnomalyCard(anomaly, index) {
    const card = document.createElement('div');
    
    // Configurazione per tipo di anomalia
    let typeColor, typeIcon, cardClass;
    
    if (anomaly.type === 'ECG') {
        typeColor = '#10b981';
        typeIcon = `<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>`;
        cardClass = 'ecg';
    } else if (anomaly.type === 'PIEZO') {
        typeColor = '#3b82f6';
        typeIcon = `<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>`;
        cardClass = 'piezo';
    } else { // TEMP
        typeColor = '#f59e0b';
        typeIcon = `<path d="M14 14.76V3.5a2.5 2.5 0 0 0-5 0v11.26a4.5 4.5 0 1 0 5 0z"/>`;
        cardClass = 'temp';
    }
    
    card.className = `anomaly-card ${cardClass}`;
    
    // Costruisci HTML della card
    let cardHTML = `
        <div class="anomaly-header">
            <div class="anomaly-type" style="background: ${typeColor}20; color: ${typeColor};">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    ${typeIcon}
                </svg>
                ${anomaly.type}
            </div>
            <div class="anomaly-time">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"/>
                    <polyline points="12 6 12 12 16 14"/>
                </svg>
                ${anomaly.time || (anomaly.timestamp ? new Date(anomaly.timestamp).toLocaleTimeString('it-IT') : '--')}
            </div>
        </div>
    `;
    
    // Metriche diverse per TEMP
    if (anomaly.type === 'TEMP') {
        // DEBUG: Log anomaly object to see what we receive
        console.log('[TEMP Anomaly Debug]', JSON.stringify(anomaly, null, 2));
        
        // FIX: Gestisci valori undefined con fallback
        const temperature = anomaly.temperature ?? 0;
        const threshold = anomaly.threshold ?? 0;
        const severity = anomaly.severity || 'unknown';
        const anomalyTypeVal = anomaly.anomaly_type || 'unknown';
        const durationReadings = anomaly.duration_readings ?? 0;
        
        const anomalyTypeLabel = anomalyTypeVal === 'hypothermia' ? 'Ipotermia' : 
                                  anomalyTypeVal === 'hyperthermia' ? 'Ipertermia' : anomalyTypeVal;
        const anomalyIcon = anomalyTypeVal === 'hypothermia' ? '🥶' : '🥵';
        
        cardHTML += `
            <div class="anomaly-metrics">
                <div class="metric">
                    <span class="metric-label">Tipo</span>
                    <span class="metric-value">${anomalyIcon} ${anomalyTypeLabel}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Temperatura</span>
                    <span class="metric-value" style="color: ${typeColor};">${typeof temperature === 'number' ? temperature.toFixed(1) : temperature}°C</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Soglia</span>
                    <span class="metric-value">${typeof threshold === 'number' ? threshold.toFixed(1) : threshold}°C</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Durata</span>
                    <span class="metric-value">${durationReadings * 2} minuti</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Severità</span>
                    <span class="metric-value severity-${severity}">${severity.toUpperCase()}</span>
                </div>
            </div>
        `;
    } else {
        // Metriche per ECG e PIEZO
        // FIX: Gestisci valori undefined con fallback
        const reconstructionError = anomaly.reconstruction_error ?? 0;
        const threshold = anomaly.threshold ?? 1; // Evita divisione per 0
        
        const errorPercent = threshold > 0 ? (reconstructionError / threshold * 100).toFixed(1) : '0';
        
        cardHTML += `
            <div class="anomaly-metrics">
                <div class="metric">
                    <span class="metric-label">Errore Ricostruzione</span>
                    <span class="metric-value">${typeof reconstructionError === 'number' ? reconstructionError.toFixed(4) : reconstructionError}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Soglia</span>
                    <span class="metric-value">${typeof threshold === 'number' ? threshold.toFixed(4) : threshold}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Superamento</span>
                    <span class="metric-value" style="color: #ef4444;">${errorPercent}%</span>
                </div>
            </div>
            <div class="anomaly-chart-container">
                <div class="anomaly-chart" id="anomalyChart_${index}"></div>
            </div>
        `;
    }
    
    card.innerHTML = cardHTML;
    
    // Renderizza mini grafico se non è TEMP (TEMP non ha sample_data da visualizzare)
    if (anomaly.type !== 'TEMP' && anomaly.sample_data && anomaly.sample_data.length > 0) {
        setTimeout(() => {
            renderAnomalyMiniChart(anomaly, index, typeColor);
        }, 50);
    }
    
    return card;
}

// ========== RENDERING MINI GRAFICO ANOMALIA ==========
function renderAnomalyMiniChart(anomaly, index, color) {
    const chartId = `anomalyChart_${index}`;
    const chartEl = document.getElementById(chartId);
    
    if (!chartEl || !anomaly.sample_data || anomaly.sample_data.length === 0) {
        return;
    }
    
    const trace = {
        y: anomaly.sample_data,
        x: Array.from({length: anomaly.sample_data.length}, (_, i) => i),
        type: 'scatter',
        mode: 'lines',
        line: { color: color, width: 1.5 },
        hovertemplate: 'Sample: %{x}<br>Value: %{y}<extra></extra>'
    };
    
    const layout = {
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: '#0f172a',
        font: { color: '#94a3b8', size: 9 },
        xaxis: { 
            showgrid: false,
            showticklabels: false,
            zeroline: false
        },
        yaxis: { 
            showgrid: true,
            gridcolor: '#1e293b',
            showticklabels: false,
            zeroline: false
        },
        margin: { l: 5, r: 5, t: 5, b: 5 },
        hovermode: 'closest'
    };
    
    const config = { 
        responsive: true,
        displayModeBar: false
    };
    
    Plotly.newPlot(chartId, [trace], layout, config);
}

// ========== NASCONDI DATI ANOMALIE ==========
function hideAnomaliesData() {
    document.getElementById('anomaliesListContainer').style.display = 'none';
    document.getElementById('selectedDateStats').style.display = 'none';
    document.getElementById('emptyAnomaliesState').style.display = 'block';
    
    anomaliesData = { ecg: [], piezo: [], temp: [] };
}

// ========== ESPORTA ANOMALIE ==========
async function exportAnomalies() {
    const dateSelect = document.getElementById('anomalyDateSelect');
    const selectedDate = dateSelect.value;
    
    if (!selectedDate) {
        alert('Seleziona prima una data');
        return;
    }
    
    try {
        const response = await fetch(`/api/anomalies/data/${selectedDate}`);
        const data = await response.json();
        
        const exportData = {
            date: selectedDate,
            exported_at: new Date().toISOString(),
            ecg_anomalies: data.ecg_anomalies,
            piezo_anomalies: data.piezo_anomalies,
            temp_anomalies: data.temp_anomalies,
            summary: {
                ecg_count: data.ecg_count,
                piezo_count: data.piezo_count,
                temp_count: data.temp_count,
                total: data.total_count
            }
        };
        
        const blob = new Blob([JSON.stringify(exportData, null, 2)], {type: 'application/json'});
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `anomalies_export_${selectedDate}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        
    } catch (error) {
        console.error('Error exporting anomalies:', error);
        alert('Errore durante l\'esportazione');
    }
}