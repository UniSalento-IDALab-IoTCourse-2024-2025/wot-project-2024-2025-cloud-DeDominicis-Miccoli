"""
File-based Debug Logger
Scrive TUTTI i log in un file e li streama alla dashboard
"""

import os
import sys
import time
import threading
from datetime import datetime
from pathlib import Path

class FileLogWatcher:
    """
    Monitora un file di log e invia le nuove righe alla dashboard
    """
    
    def __init__(self, log_file_path, emit_callback):
        """
        Args:
            log_file_path: Path al file di log da monitorare
            emit_callback: Funzione per inviare log alla dashboard
        """
        self.log_file = Path(log_file_path)
        self.emit_callback = emit_callback
        self.stop_event = threading.Event()
        self.watcher_thread = None
        self.last_position = 0
        
        # Mapping prefissi → categorie
        self.category_map = {
            '[ECG Anomaly]': 'ECG Anomaly',
            '[PIEZO Anomaly]': 'PIEZO Anomaly',
            '[TEMP Anomaly]': 'TEMP Anomaly',
            '[MQTT]': 'MQTT',
            '[Dashboard]': 'Dashboard',
            '[Sync]': 'Dashboard',  # AGGIUNTO
            '[FileLogWatcher]': 'Dashboard',  # AGGIUNTO (era [FileWatcher])
            '[Serial]': 'Serial',
            '[SHELL]': 'Serial',
            '[DEBUG]': 'Dashboard',
            '[ACK]': 'Serial',
            '[WRN]': 'Serial',
            '[Storage]': 'Dashboard',
            '[Config]': 'Config',
            '[FileWatcher]': 'Dashboard',
            '[Startup]': 'Dashboard',
            '[Anomaly]': 'Dashboard',
            '[System]': 'Dashboard',
            '[INFO   ]': 'Dashboard',
            '[ERROR  ]': 'Dashboard',
            '[WARNING]': 'Dashboard',
            '127.0.0.1': 'Dashboard',  # AGGIUNTO - Log HTTP
            ' * ': 'Dashboard',  # AGGIUNTO - Log debugger Flask
        }
        
        # Mapping prefissi → livelli
        self.level_map = {
            '[ERROR]': 'ERROR',
            '[ERROR  ]': 'ERROR',
            '[WRN]': 'WARNING',
            '[WARN]': 'WARNING',
            '[WARNING]': 'WARNING',
            '[INFO]': 'INFO',
            '[INFO   ]': 'INFO',
            '[DEBUG]': 'DEBUG',
            '✓': 'INFO',
            '✗': 'ERROR',
            '⚠': 'WARNING',
            'FAIL': 'ERROR',
            'Exception': 'ERROR',
            'Traceback': 'ERROR',
        }
    
    def start(self):
        """Avvia il watcher"""
        # Crea directory se non esiste
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        
        # RESET: Svuota il file ad ogni avvio
        sys.__stdout__.write(f"[FileLogWatcher] Resetting log file: {self.log_file}\n")
        sys.__stdout__.flush()
        with open(self.log_file, 'w') as f:
            f.write(f"[FileLogWatcher] Log file reset at server startup\n")
        
        # Imposta posizione all'inizio (file appena resettato)
        self.last_position = 0
        
        # Avvia thread watcher per nuovi log
        self.stop_event.clear()
        self.watcher_thread = threading.Thread(target=self._watch_loop, daemon=True)
        self.watcher_thread.start()
        
        sys.__stdout__.write(f"[FileLogWatcher] Monitoring for new logs: {self.log_file}\n")
        sys.__stdout__.flush()
    
    def stop(self):
        """Ferma il watcher"""
        self.stop_event.set()
        if self.watcher_thread:
            self.watcher_thread.join(timeout=2.0)
    
    def _watch_loop(self):
        """Loop principale che monitora il file"""
        while not self.stop_event.is_set():
            try:
                if not self.log_file.exists():
                    time.sleep(0.5)
                    continue
                
                current_size = self.log_file.stat().st_size
                
                # Se il file è cresciuto, leggi le nuove righe
                if current_size > self.last_position:
                    with open(self.log_file, 'r', encoding='utf-8', errors='ignore') as f:
                        f.seek(self.last_position)
                        new_lines = f.readlines()
                        self.last_position = f.tell()
                    
                    # Invia ogni riga alla dashboard
                    for line in new_lines:
                        line = line.rstrip('\n')
                        if line.strip():  # Ignora righe vuote
                            self._send_to_dashboard(line)
                
                time.sleep(0.1)  # Check ogni 100ms
                
            except Exception as e:
                sys.__stdout__.write(f"[FileLogWatcher] Error: {e}\n")
                sys.__stdout__.flush()
                time.sleep(1)
    
    def _send_to_dashboard(self, line):
        """Invia una riga di log alla dashboard"""
        # Determina categoria
        category = 'Dashboard'
        for prefix, cat in self.category_map.items():
            if line.startswith(prefix):
                category = cat
                break
        
        # Determina livello
        level = 'INFO'
        for prefix, lvl in self.level_map.items():
            if prefix in line:
                level = lvl
                break
        
        # Timestamp
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        
        # Invia
        try:
            self.emit_callback(category, level, line, timestamp)
        except Exception as e:
            # Use sys.__stdout__ to avoid infinite loop
            sys.__stdout__.write(f"[FileLogWatcher] Emit error: {e}\n")
            sys.__stdout__.flush()




# ===== SETUP PER IITdata_acq.py =====

def setup_file_log_watcher(log_file_path="system.log", log_callback=None):
    """
    Setup del watcher che legge da file e invia alla dashboard
    
    Args:
        log_file_path: Path del file di log (default: system.log)
        log_callback: Funzione add_system_log da chiamare (opzionale, tenta import se None)
    
    Returns:
        FileLogWatcher instance
    """
    # Se callback non passato, prova import (backward compatibility)
    if log_callback is None:
        try:
            from dashboard_server_cloud import add_system_log
            log_callback = add_system_log
        except ImportError:
            from dashboard_server import add_system_log
            log_callback = add_system_log
    
    def emit_callback(category, level, message, timestamp):
        # IMPORTANTE: add_system_log vuole (category, message, level)
        try:
            log_callback(category, message, level)
        except Exception as e:
            sys.__stdout__.write(f"[FileLogWatcher] Callback error: {e}\n")
            sys.__stdout__.flush()
    
    watcher = FileLogWatcher(log_file_path, emit_callback)
    return watcher


# ===== ESEMPIO DI USO =====

if __name__ == "__main__":
    # Test
    import subprocess
    
    log_file = "test.log"
    
    # Setup watcher
    from dashboard_server import add_system_log
    def emit(cat, lvl, msg, ts):
        print(f"[DASHBOARD] [{cat}] {msg}")
    
    watcher = FileLogWatcher(log_file, emit)
    watcher.start()
    
    # Scrivi alcuni log nel file
    with open(log_file, 'a') as f:
        f.write("[MQTT] Test message 1\n")
        f.flush()
    
    time.sleep(0.5)
    
    with open(log_file, 'a') as f:
        f.write("[Serial] Test message 2\n")
        f.write("[ECG Anomaly] ✓ Initialized\n")
        f.flush()
    
    time.sleep(1)
    watcher.stop()
    
    # Cleanup
    os.remove(log_file)