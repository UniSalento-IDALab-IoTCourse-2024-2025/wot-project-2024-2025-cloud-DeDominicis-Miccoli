// ========== NOTIFICATION SYSTEM - PERSISTENT ==========

class NotificationManager {
    constructor() {
        this.notifications = [];
        this.maxNotifications = 10; // Aumentato per notifiche persistenti
        this.soundEnabled = true;
        this.totalCount = 0;
        
        this.init();
    }
    
    init() {
        if (!document.getElementById('notificationsContainer')) {
            const container = document.createElement('div');
            container.id = 'notificationsContainer';
            container.className = 'notifications-container';
            document.body.appendChild(container);
        }
        
        const savedSoundPref = localStorage.getItem('notificationSound');
        if (savedSoundPref !== null) {
            this.soundEnabled = savedSoundPref === 'true';
        }
        
        console.log('[Notifications] Waiting for socket connection...');
        
        socket.on('connect', () => {
            console.log('[Notifications] Socket connected to /data namespace');
        });
        
        socket.on('new_anomaly', (data) => {
            console.log('[Notifications] Received anomaly:', data);
            this.showNotification(data);
        });
        
        console.log('[Notifications] Anomaly listener registered');
    }
    
    showNotification(anomalyData) {
        const { type, timestamp, data } = anomalyData;
        
        this.totalCount++;
        
        let title, message, details;
        
        if (type === 'ecg') {
            title = 'Anomalia ECG Rilevata';
            message = 'È stata rilevata un\'anomalia nel segnale ECG';
            details = [
                { label: 'Errore', value: (data.reconstruction_error ?? 0).toFixed(4) },
                { label: 'Soglia', value: (data.threshold ?? 0).toFixed(4) },
                { label: 'Ora', value: new Date(data.timestamp || timestamp).toLocaleTimeString('it-IT') }
            ];
        } else if (type === 'piezo') {
            title = 'Anomalia PIEZO Rilevata';
            message = 'È stata rilevata un\'anomalia nel sensore piezoelettrico';
            details = [
                { label: 'Errore', value: (data.reconstruction_error ?? 0).toFixed(4) },
                { label: 'Soglia', value: (data.threshold ?? 0).toFixed(4) },
                { label: 'Ora', value: new Date(data.timestamp || timestamp).toLocaleTimeString('it-IT') }
            ];
        } else if (type === 'temp') {
            const isCritical = data.severity === 'severe';
            const temp = data.temperature ?? 0;
            title = `Anomalia Temperatura: ${data.anomaly_type === 'hypothermia' ? 'Ipotermia' : 'Ipertermia'}`;
            message = `Temperatura ${isCritical ? 'critica' : 'anomala'}: ${temp.toFixed(1)}°C`;
            details = [
                { label: 'Temperatura', value: `${temp.toFixed(1)}°C`, critical: isCritical },
                { label: 'Soglia', value: `${(data.threshold ?? 0).toFixed(1)}°C` },
                { label: 'Severità', value: (data.severity || 'unknown').toUpperCase() }
            ];
        }
        
        const notification = this.createNotificationElement(type, title, message, details, timestamp);
        
        const container = document.getElementById('notificationsContainer');
        container.appendChild(notification);
        
        this.notifications.push(notification);
        
        // Rimuovi notifiche vecchie solo se superano il max
        if (this.notifications.length > this.maxNotifications) {
            const oldNotification = this.notifications.shift();
            this.removeNotification(oldNotification);
        }
        
        if (this.soundEnabled) {
            this.playNotificationSound(type);
        }
        
        // RIMOSSO: Auto-remove - ora le notifiche sono persistenti!
        
        this.updateCounter();
    }
    
    createNotificationElement(type, title, message, details, timestamp) {
        const notification = document.createElement('div');
        notification.className = `notification ${type}`;
        
        let iconSvg;
        if (type === 'ecg') {
            iconSvg = '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>';
        } else if (type === 'piezo') {
            iconSvg = '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>';
        } else {
            iconSvg = '<path d="M14 14.76V3.5a2.5 2.5 0 0 0-5 0v11.26a4.5 4.5 0 1 0 5 0z"/>';
        }
        
        notification.innerHTML = `
            <div class="notification-icon">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    ${iconSvg}
                </svg>
            </div>
            <div class="notification-content">
                <div class="notification-header">
                    <div class="notification-title">
                        ${title}
                        <span class="notification-badge">${type.toUpperCase()}</span>
                    </div>
                    <button class="notification-close" title="Chiudi notifica">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <line x1="18" y1="6" x2="6" y2="18"/>
                            <line x1="6" y1="6" x2="18" y2="18"/>
                        </svg>
                    </button>
                </div>
                <div class="notification-message">${message}</div>
                <div class="notification-details">
                    ${details.map(detail => `
                        <div class="notification-detail">
                            <div class="notification-detail-label">${detail.label}</div>
                            <div class="notification-detail-value ${detail.critical ? 'critical' : ''}">${detail.value}</div>
                        </div>
                    `).join('')}
                </div>
                <div class="notification-time">
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <circle cx="12" cy="12" r="10"/>
                        <polyline points="12 6 12 12 16 14"/>
                    </svg>
                    ${new Date(timestamp).toLocaleTimeString('it-IT')}
                </div>
            </div>
        `;
        
        // SOLO il bottone X chiude la notifica
        const closeBtn = notification.querySelector('.notification-close');
        closeBtn.onclick = (e) => {
            e.stopPropagation();
            this.removeNotification(notification);
        };
        
       
        notification.onclick = (e) => {
            // showAnomaliesView(); // Decommenta se vuoi navigare
        };
        
        return notification;
    }
    
    removeNotification(notification) {
        if (!notification || !notification.parentElement) return;
        
        notification.classList.add('closing');
        
        setTimeout(() => {
            if (notification.parentElement) {
                notification.parentElement.removeChild(notification);
            }
            
            const index = this.notifications.indexOf(notification);
            if (index > -1) {
                this.notifications.splice(index, 1);
            }
        }, 300);
    }
    
    playNotificationSound(type) {
        try {
            const audioContext = new (window.AudioContext || window.webkitAudioContext)();
            const oscillator = audioContext.createOscillator();
            const gainNode = audioContext.createGain();
            
            oscillator.connect(gainNode);
            gainNode.connect(audioContext.destination);
            
            if (type === 'ecg') {
                oscillator.frequency.value = 800;
            } else if (type === 'piezo') {
                oscillator.frequency.value = 600;
            } else {
                oscillator.frequency.value = 1000;
            }
            
            oscillator.type = 'sine';
            gainNode.gain.value = 0.3;
            
            oscillator.start();
            gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.3);
            
            setTimeout(() => {
                oscillator.stop();
            }, 300);
        } catch (e) {
            console.log('[Notifications] Audio not available');
        }
    }
    
    toggleSound() {
        this.soundEnabled = !this.soundEnabled;
        localStorage.setItem('notificationSound', this.soundEnabled);
        
        const soundToggle = document.getElementById('soundToggle');
        if (soundToggle) {
            soundToggle.classList.toggle('muted', !this.soundEnabled);
        }
        
        return this.soundEnabled;
    }
    
    updateCounter() {
        let counter = document.getElementById('notificationCounter');
        
        if (!counter && this.totalCount > 0) {
            counter = document.createElement('div');
            counter.id = 'notificationCounter';
            counter.className = 'notification-counter';
            document.body.appendChild(counter);
            
            counter.onclick = () => {
                this.clearAll(); // Click sul counter chiude tutte
            };
            counter.title = 'Click per chiudere tutte le notifiche';
        }
        
        if (counter) {
            counter.textContent = this.notifications.length > 99 ? '99+' : this.notifications.length;
            counter.title = `${this.notifications.length} notifiche attive - Click per chiudere tutte`;
            
            // Nascondi se non ci sono notifiche
            if (this.notifications.length === 0) {
                counter.style.display = 'none';
            } else {
                counter.style.display = 'block';
            }
        }
    }
    
    clearAll() {
        // Copia array per evitare problemi durante iterazione
        const toRemove = [...this.notifications];
        toRemove.forEach(notification => {
            this.removeNotification(notification);
        });
        this.notifications = [];
        this.updateCounter();
    }
}

// ========== INIZIALIZZAZIONE ==========

let notificationManager;

document.addEventListener('DOMContentLoaded', function() {
    notificationManager = new NotificationManager();
    createSoundToggle();
    createClearAllButton(); // Nuovo bottone per chiudere tutte
});

function createSoundToggle() {
    const soundToggle = document.createElement('button');
    soundToggle.id = 'soundToggle';
    soundToggle.className = 'sound-toggle';
    soundToggle.title = 'Toggle notification sound';
    
    soundToggle.innerHTML = `
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
            <path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"/>
        </svg>
    `;
    
    soundToggle.onclick = () => {
        const enabled = notificationManager.toggleSound();
        
        if (enabled) {
            soundToggle.innerHTML = `
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
                    <path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"/>
                </svg>
            `;
            soundToggle.classList.remove('muted');
        } else {
            soundToggle.innerHTML = `
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
                    <line x1="23" y1="9" x2="17" y2="15"/>
                    <line x1="17" y1="9" x2="23" y2="15"/>
                </svg>
            `;
            soundToggle.classList.add('muted');
        }
    };
    
    document.body.appendChild(soundToggle);
    
    if (!notificationManager.soundEnabled) {
        soundToggle.classList.add('muted');
    }
}

// Bottone per chiudere tutte le notifiche
function createClearAllButton() {
    const clearBtn = document.createElement('button');
    clearBtn.id = 'clearAllNotifications';
    clearBtn.className = 'clear-all-btn';
    clearBtn.title = 'Chiudi tutte le notifiche';
    clearBtn.style.cssText = `
        position: fixed;
        bottom: 80px;
        right: 20px;
        width: 48px;
        height: 48px;
        background: var(--card-bg, #1e293b);
        border: 1px solid var(--card-border, #334155);
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        z-index: 9999;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        transition: all 0.2s ease;
    `;
    
    clearBtn.innerHTML = `
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: #ef4444;">
            <line x1="18" y1="6" x2="6" y2="18"/>
            <line x1="6" y1="6" x2="18" y2="18"/>
        </svg>
    `;
    
    clearBtn.onmouseenter = () => {
        clearBtn.style.background = '#ef4444';
        clearBtn.querySelector('svg').style.color = 'white';
    };
    
    clearBtn.onmouseleave = () => {
        clearBtn.style.background = 'var(--card-bg, #1e293b)';
        clearBtn.querySelector('svg').style.color = '#ef4444';
    };
    
    clearBtn.onclick = () => {
        notificationManager.clearAll();
    };
    
    document.body.appendChild(clearBtn);
}