// ========== DEBUG MODE JAVASCRIPT ==========

let debugLogs = [];
let debugFilters = { category: '', level: '' };


async function loadDebugLogs() {
    try {
        const category = debugFilters.category;
        const level = debugFilters.level;
        const params = new URLSearchParams();
        
        if (category) params.append('category', category);
        if (level) params.append('level', level);
        params.append('limit', 500);
        
        const response = await fetch(`/api/system/logs?${params}`);
        const data = await response.json();
        
        if (data.success) {
            debugLogs = data.logs;
            renderDebugLogs();
        }
    } catch (error) {
        console.error('[Debug] Error loading logs:', error);
    }
}

function applyDebugFilters() {
    debugFilters.category = document.getElementById('debugCategoryFilter').value;
    debugFilters.level = document.getElementById('debugLevelFilter').value;
    loadDebugLogs();
}

function renderDebugLogs() {
    const console = document.getElementById('debugConsole');
    if (!console) {
        console.error('[Debug] debugConsole element not found');
        return;
    }
    
    console.innerHTML = '';
    
    debugLogs.forEach(log => {
        addDebugLogToConsole(log, false);
    });
    
    updateDebugLogCount();
    console.scrollTop = console.scrollHeight;
}

function addDebugLogToConsole(logEntry, scroll = true) {
    // Apply filters
    if (debugFilters.category && logEntry.category !== debugFilters.category) return;
    if (debugFilters.level && logEntry.level !== debugFilters.level) return;
    
    const console = document.getElementById('debugConsole');
    if (!console) return;
    
    const line = document.createElement('div');
    line.className = `console-line ${logEntry.level.toLowerCase()}`;
    
    const timestamp = new Date(logEntry.timestamp).toLocaleTimeString('it-IT');
    const categoryClass = logEntry.category.toLowerCase().replace(' ', '-');
    
    line.innerHTML = `
        <span class="console-timestamp">[${timestamp}]</span>
        <span class="console-category ${categoryClass}">${logEntry.category}</span>
        ${logEntry.message}
    `;
    
    console.appendChild(line);
    debugLogs.push(logEntry);
    
    if (scroll) {
        console.scrollTop = console.scrollHeight;
    }
    
    updateDebugLogCount();
}

function updateDebugLogCount() {
    const countElement = document.getElementById('debugLogCount');
    if (countElement) {
        countElement.textContent = `(${debugLogs.length} entries)`;
    }
}

function clearDebugConsole() {
    showConfirmModal(
        'Cancella Log Console',
        'Vuoi cancellare tutti i log dalla console?',
        () => {
            // On confirm
            debugLogs = [];
            const console = document.getElementById('debugConsole');
            if (console) {
                console.innerHTML = '<div class="console-line info">[INFO] Console cleared</div>';
            }
            updateDebugLogCount();
        }
    );
}

// Confirm Modal Helper
function showConfirmModal(title, message, onConfirm) {
    // Remove existing modal if any
    const existing = document.getElementById('debugConfirmModal');
    if (existing) existing.remove();
    
    const modal = document.createElement('div');
    modal.id = 'debugConfirmModal';
    modal.className = 'debug-modal-overlay';
    
    modal.innerHTML = `
        <div class="debug-modal">
            <div class="debug-modal-header">
                <h3>${title}</h3>
            </div>
            <div class="debug-modal-body">
                <p>${message}</p>
            </div>
            <div class="debug-modal-footer">
                <button class="debug-modal-btn debug-modal-btn-cancel" onclick="closeDebugConfirmModal()">
                    Annulla
                </button>
                <button class="debug-modal-btn debug-modal-btn-confirm" onclick="confirmDebugAction()">
                    Ok
                </button>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
    
    // Store callback
    window.debugConfirmCallback = onConfirm;
    
    // Fade in
    setTimeout(() => modal.classList.add('active'), 10);
}

function closeDebugConfirmModal() {
    const modal = document.getElementById('debugConfirmModal');
    if (modal) {
        modal.classList.remove('active');
        setTimeout(() => modal.remove(), 300);
    }
    window.debugConfirmCallback = null;
}

function confirmDebugAction() {
    if (window.debugConfirmCallback) {
        window.debugConfirmCallback();
    }
    closeDebugConfirmModal();
}

async function exportDebugLogs() {
    try {
        const category = debugFilters.category;
        const level = debugFilters.level;
        const params = new URLSearchParams();
        
        if (category) params.append('category', category);
        if (level) params.append('level', level);
        
        const response = await fetch(`/api/system/logs/export?${params}`);
        const data = await response.json();
        
        // Create download
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `system_logs_${new Date().toISOString().split('T')[0]}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        
        addDebugLogToConsole({
            timestamp: new Date().toISOString(),
            category: 'Dashboard',
            level: 'INFO',
            message: `Exported ${data.total_logs} log entries to JSON`
        });
    } catch (error) {
        console.error('[Debug] Error exporting logs:', error);
        addDebugLogToConsole({
            timestamp: new Date().toISOString(),
            category: 'Dashboard',
            level: 'ERROR',
            message: 'Failed to export logs: ' + error.message
        });
    }
}