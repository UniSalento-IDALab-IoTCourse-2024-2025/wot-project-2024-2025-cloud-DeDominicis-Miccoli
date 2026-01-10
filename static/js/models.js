// ========================================
// MODELS VIEW - TRAINING MANAGEMENT
// ========================================

var modelsAvailableSessions = [];
var modelsSelectedSessions = [];
var modelsAllTrainings = [];
var modelsCurrentTrainingId = null;
var modelsTrainingProgressInterval = null;

// Helper function to get auth headers
function getAuthHeaders() {
    const token = localStorage.getItem('auth_token');
    return {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
    };
}

// ========================================
// TAB MANAGEMENT
// ========================================

function showModelsTab(tabName) {
    // Update tab buttons
    document.querySelectorAll('.models-tab').forEach(tab => {
        tab.classList.remove('active');
    });
    
    if (tabName === 'new') {
        document.getElementById('tabNew').classList.add('active');
        document.getElementById('newTrainingTab').classList.add('active');
        document.getElementById('historyTrainingTab').classList.remove('active');
    } else {
        document.getElementById('tabHistory').classList.add('active');
        document.getElementById('newTrainingTab').classList.remove('active');
        document.getElementById('historyTrainingTab').classList.add('active');
        loadTrainingHistory();
    }
}

// ========================================
// LOAD TRAINING SESSIONS
// ========================================

async function loadTrainingSessions() {
    const loadingState = document.getElementById('sessionsLoadingState');
    const sessionsList = document.getElementById('sessionsList');
    
    loadingState.style.display = 'flex';
    sessionsList.innerHTML = '';
    
    try {
        const token = localStorage.getItem('auth_token');
        const response = await fetch('/api/training/sessions', {
            credentials: 'include',
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        const data = await response.json();
        
        if (data.success) {
            modelsAvailableSessions = data.sessions;
            renderSessions();
        } else {
            sessionsList.innerHTML = `<div class="empty-state">
                <div class="empty-state-icon"></div>
                <div class="empty-state-message">Errore nel caricamento delle sessioni</div>
                <div class="empty-state-hint">${data.error}</div>
            </div>`;
        }
    } catch (error) {
        console.error('[Models] Error loading sessions:', error);
        sessionsList.innerHTML = `<div class="empty-state">
            <div class="empty-state-icon">❌</div>
            <div class="empty-state-message">Errore di connessione</div>
            <div class="empty-state-hint">${error.message}</div>
        </div>`;
    } finally {
        loadingState.style.display = 'none';
    }
}

function renderSessions() {
    const sessionsList = document.getElementById('sessionsList');
    
    if (modelsAvailableSessions.length === 0) {
        sessionsList.innerHTML = `<div class="empty-state">
            <div class="empty-state-icon"></div>
            <div class="empty-state-message">Nessuna sessione disponibile</div>
            <div class="empty-state-hint">Registra alcune sessioni per iniziare il training</div>
        </div>`;
        return;
    }
    
    sessionsList.innerHTML = modelsAvailableSessions.map(session => `
        <div class="session-item" onclick="toggleSession('${session.session_id}', event)">
            <input type="checkbox" 
                   id="session_${session.session_id}" 
                   ${modelsSelectedSessions.includes(session.session_id) ? 'checked' : ''}
                   onclick="toggleSession('${session.session_id}', event)">
            <div class="session-info">
                <div class="session-datetime">
                    ${session.date_formatted} ${session.time_formatted}
                </div>
                <div class="session-meta">
                    <span>${session.duration_formatted}</span>
                    <span>${session.samples_count.toLocaleString()} samples</span>
                    <span>${session.size_mb} MB</span>
                </div>
            </div>
        </div>
    `).join('');
    
    updateSessionsSummary();
}

function toggleSession(sessionId, event) {
    if (event) event.stopPropagation();
    
    const checkbox = document.getElementById(`session_${sessionId}`);
    const index = modelsSelectedSessions.indexOf(sessionId);
    
    if (index === -1) {
        modelsSelectedSessions.push(sessionId);
        if (checkbox) checkbox.checked = true;
    } else {
        modelsSelectedSessions.splice(index, 1);
        if (checkbox) checkbox.checked = false;
    }
    
    updateSessionsSummary();
}

function selectAllSessions(select) {
    if (select) {
        modelsSelectedSessions = modelsAvailableSessions.map(s => s.session_id);
    } else {
        modelsSelectedSessions = [];
    }
    
    // Update checkboxes
    modelsAvailableSessions.forEach(session => {
        const checkbox = document.getElementById(`session_${session.session_id}`);
        if (checkbox) checkbox.checked = select;
    });
    
    updateSessionsSummary();
}

function updateSessionsSummary() {
    const selected = modelsAvailableSessions.filter(s => modelsSelectedSessions.includes(s.session_id));
    
    const totalDuration = selected.reduce((sum, s) => sum + s.duration_seconds, 0);
    const totalSize = selected.reduce((sum, s) => sum + s.size_mb, 0);
    
    document.getElementById('selectedCount').textContent = selected.length;
    document.getElementById('totalDuration').textContent = formatDuration(totalDuration);
    document.getElementById('totalSize').textContent = totalSize.toFixed(2) + ' MB';
}

function formatDuration(seconds) {
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) {
        const mins = Math.floor(seconds / 60);
        const secs = seconds % 60;
        return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`;
    }
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    return mins > 0 ? `${hours}h ${mins}m` : `${hours}h`;
}

// ========================================
// START TRAINING
// ========================================

async function startTraining() {
    // Validate inputs
    const modelType = document.querySelector('input[name="modelType"]:checked').value;
    const modelName = document.getElementById('modelName').value.trim();
    const modelVersion = document.getElementById('modelVersion').value.trim();
    const modelDescription = document.getElementById('modelDescription').value.trim();
    
    if (!modelName) {
        showAlert('Inserisci un nome per il modello');
        return;
    }
    
    if (!modelVersion) {
        showAlert('Inserisci una versione per il modello');
        return;
    }
    
    if (modelsSelectedSessions.length === 0) {
        showAlert('Seleziona almeno una sessione per il training');
        return;
    }
    
    // Prepare request
    const requestData = {
        model_type: modelType,
        model_config: {
            name: modelName,
            version: modelVersion,
            description: modelDescription || `${modelType} anomaly detection model`
        },
        sessions: modelsSelectedSessions
    };
    
    // Disable start button
    const btnStart = document.getElementById('btnStartTraining');
    btnStart.disabled = true;
    btnStart.textContent = 'Avvio in corso...';
    
    try {
        const response = await fetch('/api/training/start', {
            method: 'POST',
            credentials: 'include',
            headers: getAuthHeaders(),
            body: JSON.stringify(requestData)
        });
        
        const data = await response.json();
        
        if (data.success) {
            modelsCurrentTrainingId = data.training_id;
            
            // Hide start button, show progress
            document.getElementById('trainingControls').style.display = 'none';
            document.getElementById('trainingProgress').style.display = 'block';
            
            // Start polling for progress
            startProgressPolling(modelsCurrentTrainingId);
            
            console.log('[Models] Training started:', modelsCurrentTrainingId);
        } else {
            showAlert('Errore nell\'avvio del training: ' + data.error);
            btnStart.disabled = false;
            btnStart.textContent = 'Avvia Training';
        }
    } catch (error) {
        console.error('[Models] Error starting training:', error);
        showAlert('Errore di connessione: ' + error.message);
        btnStart.disabled = false;
        btnStart.textContent = 'Avvia Training';
    }
}

// ========================================
// TRAINING PROGRESS POLLING
// ========================================

function startProgressPolling(trainingId) {
    // Clear any existing interval
    if (modelsTrainingProgressInterval) {
        clearInterval(modelsTrainingProgressInterval);
    }
    
    // Poll every 2 seconds
    modelsTrainingProgressInterval = setInterval(async () => {
        await updateTrainingProgress(trainingId);
    }, 2000);
    
    // Initial update
    updateTrainingProgress(trainingId);
}

async function updateTrainingProgress(trainingId) {
    try {
        const response = await fetch(`/api/training/progress/${trainingId}`, {
            credentials: 'include',
            headers: getAuthHeaders()
        });
        const data = await response.json();
        
        if (data.success) {
            const progress = data.progress;
            
            // Update progress bar
            const progressBar = document.getElementById('progressBar');
            progressBar.style.width = progress.progress_pct + '%';
            progressBar.textContent = progress.progress_pct + '%';
            
            // Update message
            document.getElementById('trainingMessage').textContent = progress.message;
            
            // Update stats
            if (progress.loss !== null && progress.val_loss !== null) {
                document.getElementById('trainingStats').textContent = 
                    `Epoch ${progress.epoch}/${progress.total_epochs} | ` +
                    `Loss: ${progress.loss.toFixed(4)} | ` +
                    `Val Loss: ${progress.val_loss.toFixed(4)}`;
            }
            
            // Check if completed
            if (progress.status === 'completed') {
                clearInterval(modelsTrainingProgressInterval);
                modelsTrainingProgressInterval = null;
                showTrainingCompleted();
            } else if (progress.status === 'failed') {
                clearInterval(modelsTrainingProgressInterval);
                modelsTrainingProgressInterval = null;
                showTrainingFailed(progress.message);
            }
        }
    } catch (error) {
        console.error('[Models] Error fetching progress:', error);
    }
}

function showTrainingCompleted() {
    document.getElementById('trainingProgress').style.display = 'none';
    document.getElementById('trainingComplete').style.display = 'block';
    
    console.log('[Models] Training completed:', modelsCurrentTrainingId);
}

function showTrainingFailed(message) {
    document.getElementById('trainingProgress').innerHTML = `
        <div class="alert alert-error">
            Training fallito: ${message}
        </div>
    `;
    
    console.error('[Models] Training failed:', message);
}

// ========================================
// TRAINING HISTORY
// ========================================

async function loadTrainingHistory() {
    const loadingState = document.getElementById('historyLoadingState');
    const historyList = document.getElementById('trainingHistoryList');
    
    loadingState.style.display = 'flex';
    historyList.innerHTML = '';
    
    try {
        const response = await fetch('/api/training/list', {
            credentials: 'include',
            headers: getAuthHeaders()
        });
        const data = await response.json();
        
        if (data.success) {
            modelsAllTrainings = data.trainings;
            renderTrainingHistory();
        } else {
            historyList.innerHTML = `<div class="empty-state">
                <div class="empty-state-icon"></div>
                <div class="empty-state-message">Errore nel caricamento dello storico</div>
                <div class="empty-state-hint">${data.error}</div>
            </div>`;
        }
    } catch (error) {
        console.error('[Models] Error loading history:', error);
        historyList.innerHTML = `<div class="empty-state">
            <div class="empty-state-icon">❌</div>
            <div class="empty-state-message">Errore di connessione</div>
            <div class="empty-state-hint">${error.message}</div>
        </div>`;
    } finally {
        loadingState.style.display = 'none';
    }
}

function renderTrainingHistory() {
    const historyList = document.getElementById('trainingHistoryList');
    let trainings = [...modelsAllTrainings];
    
    // Apply filters
    const searchTerm = document.getElementById('historySearch').value.toLowerCase();
    const filterType = document.getElementById('historyFilter').value;
    
    if (searchTerm) {
        trainings = trainings.filter(t => 
            t.name.toLowerCase().includes(searchTerm) ||
            t.version.toLowerCase().includes(searchTerm)
        );
    }
    
    if (filterType) {
        trainings = trainings.filter(t => t.model_type === filterType);
    }
    
    if (trainings.length === 0) {
        historyList.innerHTML = `<div class="empty-state">
            <div class="empty-state-icon"></div>
            <div class="empty-state-message">Nessun training trovato</div>
            <div class="empty-state-hint">Inizia un nuovo training dalla tab precedente</div>
        </div>`;
        return;
    }
    
    historyList.innerHTML = trainings.map(training => {
        const date = new Date(training.created_at);
        const dateStr = date.toLocaleDateString('it-IT');
        const timeStr = date.toLocaleTimeString('it-IT', {hour: '2-digit', minute: '2-digit'});
        
        return `
        <div class="training-history-item">
            <div class="training-history-header">
                <div class="training-history-title">${training.name}</div>
                <span class="training-status ${training.status}">
                    ${training.status === 'completed' ? '✅' : training.status === 'training' ? '⏳' : '❌'}
                    ${training.status.toUpperCase()}
                </span>
            </div>
            
            <div class="training-history-meta">
                <div class="training-meta-item">
                    <div class="training-meta-label">Tipo</div>
                    <div class="training-meta-value">${training.model_type}</div>
                </div>
                <div class="training-meta-item">
                    <div class="training-meta-label">Versione</div>
                    <div class="training-meta-value">${training.version}</div>
                </div>
                <div class="training-meta-item">
                    <div class="training-meta-label">Data</div>
                    <div class="training-meta-value">${dateStr} ${timeStr}</div>
                </div>
                <div class="training-meta-item">
                    <div class="training-meta-label">Sessioni</div>
                    <div class="training-meta-value">${training.sessions_count || 0}</div>
                </div>
            </div>
            
            <div class="training-history-actions">
                <button class="btn-primary" onclick="showTrainingDetails('${training.training_id}')">
                    Dettagli
                </button>
                <button class="btn-secondary" onclick="downloadTrainingFile('${training.training_id}', 'model')">
                    Modello
                </button>
                <button class="btn-secondary" onclick="downloadTrainingFile('${training.training_id}', 'all')">
                    Tutto
                </button>
                <button class="btn-secondary" onclick="deleteTraining('${training.training_id}')" style="color: #fca5a5;">
                    Elimina
                </button>
            </div>
        </div>
        `;
    }).join('');
}

function filterTrainingHistory() {
    renderTrainingHistory();
}

// ========================================
// TRAINING DETAILS MODAL
// ========================================

async function showTrainingDetails(trainingId) {
    const modal = document.getElementById('trainingDetailsModal');
    const content = document.getElementById('trainingDetailsContent');
    
    modal.classList.add('active');
    content.innerHTML = '<div class="loading-state"><div class="spinner"></div><p>Caricamento...</p></div>';
    
    try {
        const response = await fetch(`/api/training/details/${trainingId}`, {
            credentials: 'include',
            headers: getAuthHeaders()
        });
        const data = await response.json();
        
        if (data.success) {
            renderTrainingDetails(data.details);
        } else {
            content.innerHTML = `<div class="alert alert-error">Errore: ${data.error}</div>`;
        }
    } catch (error) {
        console.error('[Models] Error loading details:', error);
        content.innerHTML = `<div class="alert alert-error">Errore di connessione: ${error.message}</div>`;
    }
}

function renderTrainingDetails(details) {
    const content = document.getElementById('trainingDetailsContent');
    const metadata = details.metadata;
    const sessionsInfo = details.sessions_info;
    
    let html = `
        <!-- General Info -->
        <div class="training-details-section">
            <h4>Informazioni Generali</h4>
            <div class="training-details-grid">
                <div class="training-detail-item">
                    <div class="training-detail-label">Tipo</div>
                    <div class="training-detail-value">${metadata.model_type}</div>
                </div>
                <div class="training-detail-item">
                    <div class="training-detail-label">Nome</div>
                    <div class="training-detail-value">${metadata.model_config.name}</div>
                </div>
                <div class="training-detail-item">
                    <div class="training-detail-label">Versione</div>
                    <div class="training-detail-value">${metadata.model_config.version}</div>
                </div>
                <div class="training-detail-item">
                    <div class="training-detail-label">Stato</div>
                    <div class="training-detail-value">${metadata.status}</div>
                </div>
            </div>
            <p style="color: var(--text-secondary); margin-top: 0.5rem;">
                ${metadata.model_config.description}
            </p>
        </div>
    `;
    
    // Training Info (if completed)
    if (metadata.training_info.completed_at) {
        const startDate = new Date(metadata.training_info.started_at);
        const endDate = new Date(metadata.training_info.completed_at);
        
        html += `
        <div class="training-details-section">
            <h4>Performance</h4>
            <div class="training-details-grid">
                <div class="training-detail-item">
                    <div class="training-detail-label">Durata</div>
                    <div class="training-detail-value">${metadata.training_info.duration_minutes?.toFixed(1) || '-'} min</div>
                </div>
                <div class="training-detail-item">
                    <div class="training-detail-label">Epochs</div>
                    <div class="training-detail-value">${metadata.training_info.final_epoch || '-'}</div>
                </div>
                <div class="training-detail-item">
                    <div class="training-detail-label">Loss Finale</div>
                    <div class="training-detail-value">${metadata.training_info.final_loss?.toFixed(6) || '-'}</div>
                </div>
                <div class="training-detail-item">
                    <div class="training-detail-label">Val Loss</div>
                    <div class="training-detail-value">${metadata.training_info.final_val_loss?.toFixed(6) || '-'}</div>
                </div>
                <div class="training-detail-item">
                    <div class="training-detail-label">Threshold</div>
                    <div class="training-detail-value">${metadata.training_info.threshold?.toFixed(6) || '-'}</div>
                </div>
            </div>
        </div>
        `;
    }
    
    // Sessions Info
    if (sessionsInfo) {
        html += `
        <div class="training-details-section">
            <h4>Sessioni Utilizzate</h4>
            <div class="training-details-grid">
                <div class="training-detail-item">
                    <div class="training-detail-label">Numero Sessioni</div>
                    <div class="training-detail-value">${sessionsInfo.total_sessions}</div>
                </div>
                <div class="training-detail-item">
                    <div class="training-detail-label">Durata Totale</div>
                    <div class="training-detail-value">${sessionsInfo.total_duration_formatted}</div>
                </div>
                <div class="training-detail-item">
                    <div class="training-detail-label">Samples Totali</div>
                    <div class="training-detail-value">${sessionsInfo.total_samples?.toLocaleString() || '-'}</div>
                </div>
            </div>
        </div>
        `;
    }
    
    // Charts - Display full images with authenticated loading
    if (details.available_charts && details.available_charts.length > 0) {
        html += `
        <div class="training-details-section">
            <h4>Grafici di Training</h4>
            <div class="training-charts-grid">
                ${details.available_charts.map(chart => `
                    <div class="chart-image-container" data-chart="${chart}" data-training-id="${metadata.training_id}">
                        <div class="chart-image-title">${formatChartName(chart)}</div>
                        <div class="loading-state"><div class="spinner"></div></div>
                    </div>
                `).join('')}
            </div>
        </div>
        `;
    }
    
    // Download Section
    html += `
    <div class="training-details-section">
        <h4>Download</h4>
        <div class="training-actions">
            <button class="btn-secondary" onclick="downloadTrainingFile('${metadata.training_id}', 'model')">
                Modello (.tflite)
            </button>
            <button class="btn-secondary" onclick="downloadTrainingFile('${metadata.training_id}', 'config')">
                Config (.json)
            </button>
            <button class="btn-secondary" onclick="downloadTrainingFile('${metadata.training_id}', 'charts')">
                Grafici (.zip)
            </button>
            <button class="btn-primary" onclick="downloadTrainingFile('${metadata.training_id}', 'all')">
                Pacchetto Completo
            </button>
        </div>
    </div>
    `;
    
    content.innerHTML = html;
    
    // Load chart images with authentication
    if (details.available_charts && details.available_charts.length > 0) {
        loadChartImages(metadata.training_id, details.available_charts);
    }
}

async function loadChartImages(trainingId, charts) {
    for (const chart of charts) {
        try {
            const container = document.querySelector(`[data-chart="${chart}"][data-training-id="${trainingId}"]`);
            if (!container) continue;
            
            // Fetch image with authentication
            const response = await fetch(`/api/training/chart/${trainingId}/${chart}.png`, {
                credentials: 'include',
                headers: getAuthHeaders()
            });
            
            if (!response.ok) {
                container.innerHTML = `
                    <div class="chart-image-title">${formatChartName(chart)}</div>
                    <p style="color:var(--text-secondary);text-align:center;padding:2rem;">Immagine non disponibile</p>
                `;
                continue;
            }
            
            // Convert to blob URL
            const blob = await response.blob();
            const blobUrl = URL.createObjectURL(blob);
            
            // Create and insert image
            container.innerHTML = `
                <div class="chart-image-title">${formatChartName(chart)}</div>
                <img src="${blobUrl}" 
                     alt="${formatChartName(chart)}"
                     style="cursor: pointer; width: 100%; height: auto; border-radius: 4px;"
                     onclick="viewChart('${trainingId}', '${chart}.png')" />
            `;
            
        } catch (error) {
            console.error(`[Models] Error loading chart ${chart}:`, error);
            const container = document.querySelector(`[data-chart="${chart}"][data-training-id="${trainingId}"]`);
            if (container) {
                container.innerHTML = `
                    <div class="chart-image-title">${formatChartName(chart)}</div>
                    <p style="color:var(--text-secondary);text-align:center;padding:2rem;">Errore caricamento</p>
                `;
            }
        }
    }
}

function formatChartName(chartName) {
    // Remove .png extension if present
    const name = chartName.replace('.png', '');
    
    const names = {
        'examples': '📊 Esempi di Dati',
        'training_history': '📈 Storico Training',
        'reconstruction': '🔄 Ricostruzione',
        'threshold_distribution': '📉 Distribuzione Threshold',
        'training': '📈 Andamento Training',
        'loss': '📉 Loss',
        'metrics': '📊 Metriche'
    };
    
    return names[name] || name.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
}

function closeTrainingDetailsModal() {
    document.getElementById('trainingDetailsModal').classList.remove('active');
}

// ========================================
// CHART VIEWER MODAL
// ========================================

async function viewChart(trainingId, chartName) {
    const modal = document.getElementById('chartViewerModal');
    const title = document.getElementById('chartViewerTitle');
    const image = document.getElementById('chartViewerImage');
    
    // Show modal with loading
    modal.classList.add('active');
    title.textContent = formatChartName(chartName.replace('.png', ''));
    image.src = ''; // Clear previous image
    image.alt = 'Loading...';
    
    try {
        // Fetch with authentication
        const response = await fetch(`/api/training/chart/${trainingId}/${chartName}`, {
            credentials: 'include',
            headers: getAuthHeaders()
        });
        
        if (!response.ok) {
            throw new Error('Failed to load chart');
        }
        
        const blob = await response.blob();
        const blobUrl = URL.createObjectURL(blob);
        image.src = blobUrl;
        
    } catch (error) {
        console.error('[Models] Error loading chart:', error);
        image.alt = 'Errore nel caricamento';
    }
}

function closeChartViewerModal() {
    document.getElementById('chartViewerModal').classList.remove('active');
}

// ========================================
// DOWNLOAD FILES
// ========================================

async function downloadTrainingFile(trainingId, fileType) {
    const url = `/api/training/download/${trainingId}/${fileType}`;
    
    try {
        console.log(`[Models] Downloading ${fileType} for training ${trainingId}...`);
        
        const response = await fetch(url, {
            credentials: 'include',
            headers: getAuthHeaders()
        });
        
        if (!response.ok) {
            const error = await response.json();
            showAlert('Errore nel download: ' + (error.error || 'Errore sconosciuto'));
            return;
        }
        
        // Get filename from Content-Disposition header
        const contentDisposition = response.headers.get('Content-Disposition');
        let filename = `training_${trainingId}_${fileType}`;
        
        if (contentDisposition) {
            const filenameMatch = contentDisposition.match(/filename="?(.+)"?/);
            if (filenameMatch) {
                filename = filenameMatch[1];
            }
        }
        
        // Download as blob
        const blob = await response.blob();
        const downloadUrl = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = downloadUrl;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(downloadUrl);
        
        console.log(`[Models] Download completed: ${filename}`);
    } catch (error) {
        console.error('[Models] Download error:', error);
        showAlert('Errore nel download: ' + error.message);
    }
}

// ========================================
// DELETE TRAINING
// ========================================

async function deleteTraining(trainingId) {
    const confirmed = await showConfirm(
        'Sei sicuro di voler eliminare questo training? Questa azione è irreversibile.',
        'Conferma Eliminazione'
    );
    
    if (!confirmed) {
        return;
    }
    
    try {
        const response = await fetch(`/api/training/${trainingId}`, {
            method: 'DELETE',
            credentials: 'include',
            headers: getAuthHeaders()
        });
        
        const data = await response.json();
        
        if (data.success) {
            showAlert('Training eliminato con successo');
            loadTrainingHistory();
        } else {
            showAlert('Errore nell\'eliminazione: ' + data.error);
        }
    } catch (error) {
        console.error('[Models] Error deleting training:', error);
        showAlert('Errore di connessione: ' + error.message);
    }
}

// ========================================
// EXPORT FUNCTIONS TO WINDOW (for onclick)
// ========================================
window.showModelsTab = showModelsTab;
window.loadTrainingSessions = loadTrainingSessions;
window.toggleSession = toggleSession;
window.selectAllSessions = selectAllSessions;
window.startTraining = startTraining;
window.showTrainingDetails = showTrainingDetails;
window.closeTrainingDetailsModal = closeTrainingDetailsModal;
window.viewChart = viewChart;
window.closeChartViewerModal = closeChartViewerModal;
window.downloadTrainingFile = downloadTrainingFile;
window.deleteTraining = deleteTraining;
window.filterTrainingHistory = filterTrainingHistory;

console.log('[Models] Training management module loaded');
console.log('[Models] Functions exported to window:', {
    loadTrainingSessions: typeof window.loadTrainingSessions,
    showModelsTab: typeof window.showModelsTab,
    startTraining: typeof window.startTraining
});

// ========================================
// INITIALIZATION
// ========================================

// Load sessions when models view is opened
document.addEventListener('DOMContentLoaded', function() {
    // Attach event listeners to buttons
    const btnReloadSessions = document.getElementById('btnReloadSessions');
    const btnSelectAll = document.getElementById('btnSelectAll');
    const btnDeselectAll = document.getElementById('btnDeselectAll');
    const btnStartTraining = document.getElementById('btnStartTraining');
    const tabNew = document.getElementById('tabNew');
    const tabHistory = document.getElementById('tabHistory');
    
    if (btnReloadSessions) {
        btnReloadSessions.addEventListener('click', loadTrainingSessions);
    }
    
    if (btnSelectAll) {
        btnSelectAll.addEventListener('click', () => selectAllSessions(true));
    }
    
    if (btnDeselectAll) {
        btnDeselectAll.addEventListener('click', () => selectAllSessions(false));
    }
    
    if (btnStartTraining) {
        btnStartTraining.addEventListener('click', startTraining);
    }
    
    if (tabNew) {
        tabNew.addEventListener('click', () => showModelsTab('new'));
    }
    
    if (tabHistory) {
        tabHistory.addEventListener('click', () => showModelsTab('history'));
    }
    
    // Auto-load sessions when view becomes active
    const observer = new MutationObserver(function(mutations) {
        mutations.forEach(function(mutation) {
            if (mutation.target.classList.contains('models-view') && 
                mutation.target.classList.contains('active')) {
                if (modelsAvailableSessions.length === 0) {
                    loadTrainingSessions();
                }
            }
        });
    });
    
    const modelsView = document.getElementById('modelsView');
    if (modelsView) {
        observer.observe(modelsView, {
            attributes: true,
            attributeFilter: ['class']
        });
    }
});