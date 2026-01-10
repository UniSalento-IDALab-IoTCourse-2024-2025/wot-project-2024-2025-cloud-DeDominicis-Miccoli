"""
Cloud Dashboard Server for IIT Device Data
Receives data via MQTT instead of direct board connection
Con supporto per anomalie ECG, PIEZO e TEMPERATURE + Sistema Notifiche Real-time
"""
import sys
from flask import Flask, render_template, jsonify, request, redirect, url_for
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import paho.mqtt.client as mqtt
from paho.mqtt.client import CallbackAPIVersion
import threading
import time
import secrets
import os
import json
from collections import deque
from datetime import datetime
from pathlib import Path
import sqlite3
from functools import wraps

# ====== AUTHENTICATION ======
from auth_db import AuthDB

# ====== DATABASE SYNC ======
from db_sync_module import DatabaseSyncService, SyncConfig

# ====== FILE LOG WATCHER ======
from file_log_watcher import setup_file_log_watcher

# ====== MODEL TRAINING ======
from data_loader import SessionDataLoader
from training_manager import TrainingManager
import zipfile
from io import BytesIO

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', secrets.token_hex(32))
app.config['SESSION_COOKIE_SECURE'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ====== AUTH DATABASE ======
auth_db = AuthDB('users.db')

# ====== TRAINING MANAGER ======
training_manager = TrainingManager('var/iit_data/models')

# ====== MQTT CONFIGURATION ======
MQTT_BROKER = "localhost"  # Mosquitto runs on same EC2 instance
MQTT_PORT = 1883
MQTT_CLIENT_ID = "dashboard_cloud"

# ====== SYNC CONFIGURATION ======
SYNC_CONFIG = SyncConfig(
    db_path="users.db",
    is_local=False,  # This is CLOUD instance
    local_api_url="http://10.18.195.83:5001",  # Raspberry (remote)
    cloud_api_url="http://localhost:5002",  # This server
    sync_interval=60,  # Sync every 60 seconds
    sync_token="test123"  # MUST match local!
)

# Sync service global
sync_service = None

# ====== STORAGE PATHS (same as receiver) ======
BASE_STORAGE_DIR = Path("./var/iit_data")
DATA_STORAGE_DIR = BASE_STORAGE_DIR / "data_storage"
ANOMALY_LOGS_DIR = BASE_STORAGE_DIR / "anomaly_logs"

# ====== GLOBAL STATE ======
class DashboardState:
    def __init__(self):
        self.is_acquiring = False
        self.device_connected = False
        self.data_queues = {
            'ECG': deque(maxlen=2500),
            'ADC': deque(maxlen=2500),
            'TEMP': deque(maxlen=120)
        }
        self.stats = {
            'ECG': {'samples': 0, 'last_update': None},
            'ADC': {'samples': 0, 'last_update': None},
            'TEMP': {'samples': 0, 'last_update': None, 'current_temp': None}
        }
        self.start_time = None
        self.packet_count = 0
        self.current_session_id = None
        
        # Notification tracking - initialize with existing anomaly counts
        # to prevent notification spam on server restart
        self.last_notification_counts = self._get_initial_anomaly_counts()
        
        # MQTT state
        self.mqtt_connected = False
    
    def _get_initial_anomaly_counts(self):
        """Count existing anomalies on startup to avoid re-notifying them"""
        counts = {'ecg': 0, 'piezo': 0, 'temp': 0}
        
        if not ANOMALY_LOGS_DIR.exists():
            return counts
        
        today = datetime.now().strftime("%Y%m%d")
        files = {
            'ecg': ANOMALY_LOGS_DIR / f"anomalies_{today}.json",
            'piezo': ANOMALY_LOGS_DIR / f"piezo_anomalies_{today}.json",
            'temp': ANOMALY_LOGS_DIR / f"temp_anomalies_{today}.json"
        }
        
        for anomaly_type, file_path in files.items():
            if file_path.exists():
                try:
                    with open(file_path, 'r') as f:
                        anomalies = json.load(f)
                    counts[anomaly_type] = len(anomalies) if isinstance(anomalies, list) else 0
                except:
                    counts[anomaly_type] = 0
        
        print(f"[Startup] Existing anomalies: ECG={counts['ecg']}, PIEZO={counts['piezo']}, TEMP={counts['temp']}")
        return counts
        
state = DashboardState()

# ====== SYSTEM LOGGING ======
system_logs = deque(maxlen=1000)  # Keep last 1000 log entries in memory

def add_system_log(category, message, level='INFO'):
    """
    Add a system log entry and emit it to connected clients
    
    Args:
        category: Log category (MQTT, Dashboard, Serial, etc.)
        message: Log message
        level: Log level (INFO, WARNING, ERROR, DEBUG)
    """
    log_entry = {
        'timestamp': datetime.now().isoformat(),
        'category': category,
        'level': level,
        'message': message
    }
    
    system_logs.append(log_entry)
    
    # Emit to all connected clients
    try:
        socketio.emit('system_log', log_entry, namespace='/data')
    except Exception as e:
        print(f"[Logging] Error emitting log: {e}")

# ====== MQTT CLIENT ======
mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=MQTT_CLIENT_ID)

def on_mqtt_connect(client, userdata, flags, reason_code, properties):
    """Callback quando MQTT si connette - VERSION 2"""
    if reason_code == 0:
        print(f"[MQTT] Connected to broker at {MQTT_BROKER}:{MQTT_PORT}")
        add_system_log('MQTT', f'Connected to broker at {MQTT_BROKER}:{MQTT_PORT}', 'INFO')
        state.mqtt_connected = True
        
        # Subscribe to all relevant topics
        topics = [
            ('iit/device/+/realtime/+', 1),
            ('iit/device/+/anomalies/+', 1),
            ('iit/device/+/session', 1),
            ('iit/device/+/status', 1),
            ('iit/device/realtime/+', 1),
            ('iit/device/anomalies/+', 1),
            ('iit/device/session', 1),
            ('iit/device/status', 1),
        ]
        
        for topic, qos in topics:
            client.subscribe(topic, qos)
            print(f"[MQTT] Subscribed to: {topic}")
        
        add_system_log('MQTT', f'Subscribed to {len(topics)} topics', 'INFO')
    else:
        print(f"[MQTT] Connection failed with code {reason_code}")
        add_system_log('MQTT', f'Connection failed with code {reason_code}', 'ERROR')
        state.mqtt_connected = False

def on_mqtt_disconnect(client, userdata, flags, reason_code, properties):
    """Callback quando MQTT si disconnette - VERSION 2"""
    state.mqtt_connected = False
    if reason_code != 0:
        print(f"[MQTT] Unexpected disconnection (code: {reason_code})")
        add_system_log('MQTT', f'Unexpected disconnection (code: {reason_code})', 'WARNING')

def on_mqtt_message(client, userdata, msg):
    """Main MQTT message handler"""
    try:
        payload = json.loads(msg.payload.decode())
        topic = msg.topic
        
        # Route messages
        if '/realtime/' in topic:
            handle_realtime_data(payload, topic)
        elif '/anomalies/' in topic:
            handle_anomaly_data(payload, topic)
        elif '/session' in topic:
            handle_session_event(payload)
        elif '/status' in topic:
            handle_device_status(payload)
            
    except Exception as e:
        print(f"[MQTT] Error processing message: {e}")

def handle_realtime_data(payload, topic):
    """Handle real-time data from MQTT"""
    try:
        signal = payload.get('signal')
        frames = payload.get('frames', [])
        timestamp = payload.get('timestamp')
        
        if not signal or signal not in ['ECG', 'ADC', 'TEMP']:
            return
        
        # Push data to queues (same as local dashboard)
        push_data(signal, frames, timestamp)
        
    except Exception as e:
        print(f"[MQTT] Error handling realtime data: {e}")

def handle_anomaly_data(payload, topic):
    """Handle anomaly detection results from MQTT"""
    try:
        # Determine anomaly type from topic or payload
        if '/ecg' in topic.lower() or payload.get('anomaly_type', '').upper() == 'ECG':
            anomaly_type = 'ecg'
        elif '/piezo' in topic.lower() or payload.get('anomaly_type', '').upper() == 'PIEZO':
            anomaly_type = 'piezo'
        elif '/temp' in topic.lower() or payload.get('anomaly_type', '').upper() == 'TEMP':
            anomaly_type = 'temp'
        else:
            print(f"[MQTT] Unknown anomaly type in topic: {topic}")
            return
        
        # Send notification immediately
        send_anomaly_notification(anomaly_type, payload)
        
    except Exception as e:
        print(f"[MQTT] Error handling anomaly: {e}")

def handle_session_event(payload):
    """Handle session start/end events"""
    try:
        event = payload.get('event')
        session_id = payload.get('session_id')
        
        if event == 'session_start':
            state.current_session_id = session_id
            state.is_acquiring = True
            state.start_time = time.time()
            socketio.emit('acquisition_status', {'acquiring': True}, namespace='/data')
            print(f"[Session] Started: {session_id}")
            
        elif event == 'session_end':
            state.is_acquiring = False
            socketio.emit('acquisition_status', {'acquiring': False}, namespace='/data')
            print(f"[Session] Ended: {session_id}")
            
    except Exception as e:
        print(f"[MQTT] Error handling session event: {e}")

def handle_device_status(payload):
    """Handle device status updates"""
    try:
        status = payload.get('status')
        
        if status == 'connected':
            state.device_connected = True
        elif status == 'disconnected':
            state.device_connected = False
        
        socketio.emit('device_status', {'connected': state.device_connected}, namespace='/data')
        
    except Exception as e:
        print(f"[MQTT] Error handling device status: {e}")

# Setup MQTT callbacks
mqtt_client.on_connect = on_mqtt_connect
mqtt_client.on_disconnect = on_mqtt_disconnect
mqtt_client.on_message = on_mqtt_message

# ====== NOTIFICATION SYSTEM ======

def send_anomaly_notification(anomaly_type: str, anomaly_data: dict):
    """
    Invia notifica real-time quando viene rilevata una nuova anomalia
    
    Args:
        anomaly_type: 'ecg', 'piezo', o 'temp'
        anomaly_data: Dati dell'anomalia
    """
    # VALIDATION: Filter out invalid anomalies
    if anomaly_type == 'temp':
        temperature = anomaly_data.get('temperature', 0)
        threshold = anomaly_data.get('threshold', 0)
        
        # Reject if temperature is 0, None, or missing
        if not temperature or temperature == 0:
            print(f"[Notification] REJECTED invalid TEMP anomaly - temperature: {temperature}")
            return
        
        # Reject if threshold is 0, None, or missing
        if not threshold or threshold == 0:
            print(f"[Notification] REJECTED invalid TEMP anomaly - threshold: {threshold}")
            return
        
        print(f"[Notification] VALIDATED TEMP anomaly - temp: {temperature}°C, threshold: {threshold}°C")
    
    elif anomaly_type in ['ecg', 'piezo']:
        reconstruction_error = anomaly_data.get('reconstruction_error', 0)
        threshold = anomaly_data.get('threshold', 0)
        
        # Reject if reconstruction_error is 0, None, or missing
        if reconstruction_error is None or reconstruction_error == 0:
            print(f"[Notification] REJECTED invalid {anomaly_type.upper()} anomaly - reconstruction_error: {reconstruction_error}")
            return
        
        # Reject if threshold is 0, None, or missing
        if not threshold or threshold == 0:
            print(f"[Notification] REJECTED invalid {anomaly_type.upper()} anomaly - threshold: {threshold}")
            return
        
        print(f"[Notification] VALIDATED {anomaly_type.upper()} anomaly - error: {reconstruction_error}, threshold: {threshold}")
    
    notification = {
        'type': anomaly_type,
        'timestamp': datetime.now().isoformat(),
        'data': anomaly_data
    }
    
    print(f"[Notification] Sending {anomaly_type.upper()} notification to /data namespace")
    print(f"[Notification] Data: {notification}")
    
    # Invia via SocketIO a tutti i client connessi
    socketio.emit('new_anomaly', notification, namespace='/data')
    socketio.emit('new_anomaly', notification)
    
    print(f"[Notification] Notification sent successfully")


def check_for_new_anomalies():
    """
    Controlla periodicamente i file di log per nuove anomalie
    e invia notifiche quando ne trova
    """
    if not ANOMALY_LOGS_DIR.exists():
        return
    
    today = datetime.now().strftime("%Y%m%d")
    
    # File da monitorare
    files_to_check = {
        'ecg': ANOMALY_LOGS_DIR / f"anomalies_{today}.json",
        'piezo': ANOMALY_LOGS_DIR / f"piezo_anomalies_{today}.json",
        'temp': ANOMALY_LOGS_DIR / f"temp_anomalies_{today}.json"
    }
    
    for anomaly_type, file_path in files_to_check.items():
        if not file_path.exists():
            continue
        
        try:
            with open(file_path, 'r') as f:
                anomalies = json.load(f)
            
            current_count = len(anomalies) if isinstance(anomalies, list) else 0
            last_count = state.last_notification_counts[anomaly_type]
            
            # Se ci sono nuove anomalie
            if current_count > last_count:
                # Invia notifica per ogni nuova anomalia
                for i in range(last_count, current_count):
                    anomaly = anomalies[i]
                    send_anomaly_notification(anomaly_type, anomaly)
                
                # Aggiorna contatore
                state.last_notification_counts[anomaly_type] = current_count
                
        except Exception as e:
            app.logger.error(f"Error checking {anomaly_type} anomalies: {str(e)}")


# ====== VALIDAZIONE INPUT ======

def validate_signal_name(signal):
    """Valida il nome del segnale"""
    allowed_signals = ['ECG', 'ADC', 'TEMP']
    return signal in allowed_signals

def validate_session_id(session_id):
    """Valida il formato del session ID"""
    if not session_id or len(session_id) != 15:
        return False
    try:
        datetime.strptime(session_id, '%Y%m%d_%H%M%S')
        return True
    except:
        return False

def validate_date_string(date_str):
    """Valida il formato della data"""
    if not date_str or len(date_str) != 8:
        return False
    try:
        datetime.strptime(date_str, '%Y%m%d')
        return True
    except:
        return False

# ====== FUNZIONI DATI ======

def push_data(signal_name, frames, timestamp=None):
    """Push new data frames to the dashboard"""
    if not validate_signal_name(signal_name):
        return
    
    for frame in frames:
        state.data_queues[signal_name].append({
            'values': frame,
            'timestamp': timestamp or time.time()
        })
    
    state.stats[signal_name]['samples'] += len(frames)
    state.stats[signal_name]['last_update'] = datetime.now().isoformat()
    
    if signal_name == 'TEMP' and frames:
        state.stats[signal_name]['current_temp'] = frames[-1][0]
    
    state.packet_count += 1
    
    # Send updates to clients every 5 packets
    if state.packet_count % 5 == 0:
        socketio.emit('data_update', {
            'signal': signal_name,
            'data': prepare_chart_data(signal_name)
        }, namespace='/data')

def prepare_chart_data(signal_name, max_points=1000):
    """Prepara i dati per il grafico con downsampling intelligente"""
    if not validate_signal_name(signal_name):
        return {'x': [], 'y': []}
    
    data = list(state.data_queues[signal_name])
    
    if len(data) == 0:
        return {'x': [], 'y': []}
    
    # Downsampling se necessario
    if len(data) > max_points:
        step = len(data) // max_points
        data = data[::step]
    
    if signal_name == 'TEMP':
        return {
            'x': list(range(len(data))),
            'y': [[d['values'][0]] for d in data]
        }
    else:
        num_channels = len(data[0]['values']) if data else 0
        y_data = [[] for _ in range(num_channels)]
        
        for point in data:
            for ch in range(num_channels):
                y_data[ch].append(point['values'][ch])
        
        return {
            'x': list(range(len(data))),
            'y': y_data
        }

# ====== STORAGE FUNCTIONS (read from receiver's storage) ======

def load_session_data(session_id, signal, limit=None):
    """Load session data from storage"""
    try:
        date_part = session_id.split('_')[0]
        session_dir = DATA_STORAGE_DIR / date_part / session_id
        
        if not session_dir.exists():
            print(f"[Storage] Session dir not found: {session_dir}")
            return []
        
        # FIX: Nome file corretto - MAIUSCOLO e .jsonl
        data_file = session_dir / f"{signal.upper()}_data.jsonl"
        
        if not data_file.exists():
            print(f"[Storage] Data file not found: {data_file}")
            return []
        
        # Leggi JSONL (una riga = un sample)
        data = []
        with open(data_file, 'r') as f:
            for line in f:
                data.append(json.loads(line.strip()))
        
        print(f"[Storage] Loaded {len(data)} samples from {data_file}")
        
        if limit and len(data) > limit:
            return data[:limit]
        
        return data
    except Exception as e:
        print(f"[Storage] Error loading session data: {e}")
        return []
    
def get_available_sessions():
    """Get list of available sessions from storage"""
    sessions = []
    
    if not DATA_STORAGE_DIR.exists():
        return sessions
    
    # Iterate through date directories
    for date_dir in sorted(DATA_STORAGE_DIR.iterdir(), reverse=True):
        if not date_dir.is_dir():
            continue
        
        # Iterate through session directories
        for session_dir in sorted(date_dir.iterdir(), reverse=True):
            if not session_dir.is_dir():
                continue
            
            session_id = session_dir.name
            metadata_file = session_dir / "metadata.json"
            
            if metadata_file.exists():
                try:
                    with open(metadata_file, 'r') as f:
                        metadata = json.load(f)
                    
                    sessions.append({
                        'session_id': session_id,
                        'date': date_dir.name,
                        'metadata': metadata
                    })
                except:
                    pass
    
    return sessions

# ====== AUTHENTICATION DECORATORS ======

def require_auth(f):
    """Decorator to require authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        
        if not token:
            return jsonify({'success': False, 'error': 'Non autenticato'}), 401
        
        result = auth_db.verify_session(token)
        
        if not result['success']:
            return jsonify({'success': False, 'error': 'Sessione scaduta'}), 401
        
        request.user = result['user']
        return f(*args, **kwargs)
    
    return decorated_function

def require_role(required_role):
    """Decorator to require specific role (admin only or medico+)"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not hasattr(request, 'user'):
                return jsonify({'success': False, 'error': 'Non autenticato'}), 401
            
            user_role = request.user['ruolo']
            
            # Admin can access everything
            if user_role == 'admin':
                return f(*args, **kwargs)
            
            # Check specific role
            if user_role != required_role:
                return jsonify({'success': False, 'error': 'Permessi insufficienti'}), 403
            
            return f(*args, **kwargs)
        
        return decorated_function
    return decorator

# ====== REST API ROUTES ======

@app.route('/login')
def login_page():
    """Login page"""
    return render_template('login.html')

@app.route('/register')
def register_page():
    """Register page"""
    return render_template('register.html')

@app.route('/dashboard')
@app.route('/')
def index():
    """Serve the main dashboard page"""
    return render_template('dashboard_cloud.html')

@app.route('/api/status')
def get_status():
    """Get current system status"""
    return jsonify({
        'device_connected': state.device_connected,
        'mqtt_connected': state.mqtt_connected,
        'is_acquiring': state.is_acquiring,
        'stats': state.stats,
        'packet_count': state.packet_count,
        'uptime': int(time.time() - state.start_time) if state.start_time else 0,
        'current_session': state.current_session_id
    })

# ====== AUTH API ROUTES ======

@app.route('/api/auth/login', methods=['POST'])
def api_login():
    """Login API"""
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({'success': False, 'error': 'Username e password richiesti'}), 400
    
    result = auth_db.login(username, password)
    
    if result['success']:
        return jsonify(result), 200
    else:
        return jsonify(result), 401

@app.route('/api/auth/register', methods=['POST'])
def api_register():
    """Register API"""
    data = request.get_json()
    
    username = data.get('username')
    password = data.get('password')
    nome = data.get('nome')
    cognome = data.get('cognome')
    ruolo = data.get('ruolo')
    
    if not all([username, password, nome, cognome, ruolo]):
        return jsonify({'success': False, 'error': 'Tutti i campi sono richiesti'}), 400
    
    result = auth_db.register_user(username, password, nome, cognome, ruolo)
    
    if result['success']:
        return jsonify(result), 200
    else:
        return jsonify(result), 400

@app.route('/api/auth/logout', methods=['POST'])
@require_auth
def api_logout():
    """Logout API"""
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    result = auth_db.logout(token)
    return jsonify(result), 200

@app.route('/api/auth/verify', methods=['GET'])
@require_auth
def api_verify():
    """Verify session"""
    return jsonify({
        'success': True,
        'user': request.user
    }), 200

# ====== USER MANAGEMENT API (ADMIN ONLY) ======

@app.route('/api/users/list', methods=['GET'])
@require_auth
@require_role('admin')
def api_list_users():
    """Get all users (admin only)"""
    result = auth_db.get_all_users()
    return jsonify(result), 200

@app.route('/api/users/<int:user_id>', methods=['GET'])
@require_auth
@require_role('admin')
def api_get_user(user_id):
    """Get user by ID (admin only)"""
    result = auth_db.get_user_by_id(user_id)
    
    if result['success']:
        return jsonify(result), 200
    else:
        return jsonify(result), 404

@app.route('/api/users/<int:user_id>', methods=['PUT'])
@require_auth
@require_role('admin')
def api_update_user(user_id):
    """Update user (admin only)"""
    data = request.get_json()
    
    nome = data.get('nome')
    cognome = data.get('cognome')
    ruolo = data.get('ruolo')
    new_password = data.get('new_password')
    
    result = auth_db.update_user(user_id, nome, cognome, ruolo, new_password)
    
    if result['success']:
        return jsonify(result), 200
    else:
        return jsonify(result), 400

@app.route('/api/users/<int:user_id>', methods=['DELETE'])
@require_auth
@require_role('admin')
def api_delete_user(user_id):
    """Delete user (admin only)"""
    result = auth_db.delete_user(user_id)
    
    if result['success']:
        return jsonify(result), 200
    else:
        return jsonify(result), 400

# ====== CONTROL ROUTES ======

@app.route('/api/control/start', methods=['POST'])
def start_acquisition():
    """Start data acquisition - NOTE: This is informational only on cloud"""
    return jsonify({
        'status': 'info',
        'message': 'Acquisition is controlled from Raspberry Pi device',
        'current_state': state.is_acquiring
    })

@app.route('/api/control/stop', methods=['POST'])
def stop_acquisition():
    """Stop data acquisition - NOTE: This is informational only on cloud"""
    return jsonify({
        'status': 'info',
        'message': 'Acquisition is controlled from Raspberry Pi device',
        'current_state': state.is_acquiring
    })

# ====== HISTORY API ROUTES ======

@app.route('/api/history/sessions')
def get_sessions():
    """Get list of available sessions"""
    try:
        sessions = get_available_sessions()
        
        formatted_sessions = []
        for session in sessions:
            session_id = session['session_id']
            metadata = session.get('metadata', {})
            
            formatted_sessions.append({
                'session_id': session_id,
                'date': session['date'],
                'start_time': metadata.get('start_time', ''),
                'end_time': metadata.get('end_time', ''),
                'status': metadata.get('status', 'unknown'),
                'duration': metadata.get('duration', 0),
                'total_samples': metadata.get('total_samples', {})
            })
        
        return jsonify({'sessions': formatted_sessions})
    
    except Exception as e:
        app.logger.error(f"Error getting sessions: {str(e)}")
        return jsonify({'error': 'Server error'}), 500

@app.route('/api/history/session/<session_id>/data/<signal>')
def get_session_data(session_id, signal):
    """Get data for a specific session and signal"""
    if not validate_session_id(session_id) or not validate_signal_name(signal):
        return jsonify({'error': 'Invalid parameters'}), 400
    
    try:
        data = load_session_data(session_id, signal)
        
        if not data:
            return jsonify({
                'data': {'x': [], 'y': []},
                'count': 0
            })
        
        # Format data for frontend
        if signal == 'TEMP':
            chart_data = {
                'x': list(range(len(data))),
                'y': [[d] for d in data]
            }
        else:
            num_channels = len(data[0]) if data else 0
            y_data = [[] for _ in range(num_channels)]
            
            for point in data:
                for ch in range(num_channels):
                    y_data[ch].append(point[ch])
            
            chart_data = {
                'x': list(range(len(data))),
                'y': y_data
            }
        
        return jsonify({
            'data': chart_data,
            'count': len(data)
        })
    
    except Exception as e:
        app.logger.error(f"Error getting session data: {str(e)}")
        return jsonify({'error': 'Server error'}), 500

# ====== ANOMALIES API ROUTES ======

@app.route('/api/anomalies/dates')
def get_anomaly_dates():
    """Get dates with available anomaly data"""
    try:
        if not ANOMALY_LOGS_DIR.exists():
            return jsonify({'dates': []})
        
        dates = set()
        
        for log_file in ANOMALY_LOGS_DIR.glob("*.json"):
            filename = log_file.stem
            date_str = None
            
            if filename.startswith("anomalies_"):
                date_str = filename.replace("anomalies_", "")
            elif filename.startswith("piezo_anomalies_"):
                date_str = filename.replace("piezo_anomalies_", "")
            elif filename.startswith("temp_anomalies_"):
                date_str = filename.replace("temp_anomalies_", "")
            
            if date_str and len(date_str) == 8 and date_str.isdigit():
                dates.add(date_str)
        
        formatted_dates = []
        for date in sorted(dates, reverse=True):
            try:
                dt = datetime.strptime(date, '%Y%m%d')
                formatted_dates.append({
                    'value': date,
                    'label': dt.strftime('%d %B %Y')
                })
            except:
                pass
        
        return jsonify({'dates': formatted_dates})
    
    except Exception as e:
        app.logger.error(f"Error getting anomaly dates: {str(e)}")
        return jsonify({'error': 'Server error'}), 500

@app.route('/api/anomalies/data/<date>')
def get_anomalies_for_date(date):
    """Get all anomalies for a specific date"""
    if not validate_date_string(date):
        return jsonify({'error': 'Invalid date format'}), 400
    
    try:
        ecg_anomalies = []
        piezo_anomalies = []
        temp_anomalies = []
        
        # Load ECG anomalies
        ecg_file = ANOMALY_LOGS_DIR / f"anomalies_{date}.json"
        if ecg_file.exists():
            with open(ecg_file, 'r') as f:
                ecg_anomalies = json.load(f)
        
        # Load PIEZO anomalies
        piezo_file = ANOMALY_LOGS_DIR / f"piezo_anomalies_{date}.json"
        if piezo_file.exists():
            with open(piezo_file, 'r') as f:
                piezo_anomalies = json.load(f)
        
        # Load TEMP anomalies
        temp_file = ANOMALY_LOGS_DIR / f"temp_anomalies_{date}.json"
        if temp_file.exists():
            with open(temp_file, 'r') as f:
                temp_anomalies = json.load(f)
        
        return jsonify({
            'ecg_anomalies': ecg_anomalies,
            'piezo_anomalies': piezo_anomalies,
            'temp_anomalies': temp_anomalies,
            'ecg_count': len(ecg_anomalies),
            'piezo_count': len(piezo_anomalies),
            'temp_count': len(temp_anomalies),
            'total_count': len(ecg_anomalies) + len(piezo_anomalies) + len(temp_anomalies)
        })
    
    except Exception as e:
        app.logger.error(f"Error getting anomalies for date: {str(e)}")
        return jsonify({'error': 'Server error'}), 500

@app.route('/api/anomalies/summary')
def get_anomaly_summary():
    """Get summary of all anomalies"""
    try:
        if not ANOMALY_LOGS_DIR.exists():
            return jsonify({
                'summary': [],
                'total_ecg': 0,
                'total_piezo': 0,
                'total_temp': 0,
                'total': 0
            })
        
        summary = []
        total_ecg = 0
        total_piezo = 0
        total_temp = 0
        
        # Get all unique dates
        dates = set()
        for log_file in ANOMALY_LOGS_DIR.glob("*.json"):
            filename = log_file.stem
            date_str = None
            
            if filename.startswith("anomalies_"):
                date_str = filename.replace("anomalies_", "")
            elif filename.startswith("piezo_anomalies_"):
                date_str = filename.replace("piezo_anomalies_", "")
            elif filename.startswith("temp_anomalies_"):
                date_str = filename.replace("temp_anomalies_", "")
            
            if date_str and len(date_str) == 8 and date_str.isdigit():
                dates.add(date_str)
        
        # Count anomalies per date
        for date in sorted(dates, reverse=True):
            ecg_count = 0
            piezo_count = 0
            temp_count = 0
            
            ecg_file = ANOMALY_LOGS_DIR / f"anomalies_{date}.json"
            if ecg_file.exists():
                try:
                    with open(ecg_file, 'r') as f:
                        ecg_data = json.load(f)
                        ecg_count = len(ecg_data) if isinstance(ecg_data, list) else 0
                except:
                    pass
            
            piezo_file = ANOMALY_LOGS_DIR / f"piezo_anomalies_{date}.json"
            if piezo_file.exists():
                try:
                    with open(piezo_file, 'r') as f:
                        piezo_data = json.load(f)
                        piezo_count = len(piezo_data) if isinstance(piezo_data, list) else 0
                except:
                    pass
            
            temp_file = ANOMALY_LOGS_DIR / f"temp_anomalies_{date}.json"
            if temp_file.exists():
                try:
                    with open(temp_file, 'r') as f:
                        temp_data = json.load(f)
                        temp_count = len(temp_data) if isinstance(temp_data, list) else 0
                except:
                    pass
            
            total_ecg += ecg_count
            total_piezo += piezo_count
            total_temp += temp_count
        
        return jsonify({
            'total_ecg': total_ecg,
            'total_piezo': total_piezo,
            'total_temp': total_temp,
            'total': total_ecg + total_piezo + total_temp
        })
    
    except Exception as e:
        app.logger.error(f"Error getting anomaly summary: {str(e)}")
        return jsonify({'error': 'Server error'}), 500

    
@app.route('/api/history/dates')
def get_history_dates():
    """Get available dates"""
    try:
        if not DATA_STORAGE_DIR.exists():
            return jsonify({'dates': []})
        
        dates = []
        for date_dir in sorted(DATA_STORAGE_DIR.iterdir(), reverse=True):
            if date_dir.is_dir() and len(date_dir.name) == 8:
                dates.append({
                    'value': date_dir.name,
                    'label': datetime.strptime(date_dir.name, '%Y%m%d').strftime('%d %B %Y')
                })
        
        return jsonify({'dates': dates})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/history/window/<session_id>/<signal>')
def get_windowed_data(session_id, signal):
    position = int(request.args.get('position', 0))
    window_size = int(request.args.get('window_size', 1000))
    
    try:
        data = load_session_data(session_id, signal)
        
        if not data:
            return jsonify({
                'data': {'x': [], 'y': []},
                'count': 0,
                'total_count': 0
            })
        
        window_data = data[position:position + window_size]
        
        # FIX: Data format is {timestamp: X, values: [Y]} - extract only values
        if signal == 'TEMP':
            # Extract values from {timestamp, values} format
            values = []
            for item in window_data:
                if isinstance(item, dict) and 'values' in item:
                    val = item['values']
                    # values is array with 1 element for TEMP
                    values.append(val[0] if isinstance(val, list) and len(val) > 0 else val)
                else:
                    values.append(item)
            
            chart_data = {
                'x': list(range(position, position + len(values))),
                'y': [values]
            }
        elif signal == 'ADC':
            # ADC: {timestamp, values: [ch1, ch2, ch3]} - 3 channels
            y_data = [[], [], []]
            for item in window_data:
                if isinstance(item, dict) and 'values' in item:
                    vals = item['values']
                    if isinstance(vals, list) and len(vals) >= 3:
                        for ch in range(3):
                            y_data[ch].append(vals[ch])
                    else:
                        for ch in range(3):
                            y_data[ch].append(0)
                else:
                    for ch in range(3):
                        y_data[ch].append(0)
            
            chart_data = {
                'x': list(range(position, position + len(window_data))),
                'y': y_data
            }
        else:  # ECG
            # ECG: {timestamp, values: [val]}
            values = []
            for item in window_data:
                if isinstance(item, dict) and 'values' in item:
                    val = item['values']
                    # values is array with 1 element for ECG
                    values.append(val[0] if isinstance(val, list) and len(val) > 0 else val)
                else:
                    values.append(item)
            
            chart_data = {
                'x': list(range(position, position + len(values))),
                'y': [values]
            }
        
        return jsonify({
            'data': chart_data,
            'count': len(window_data),
            'total_count': len(data)
        })
    except Exception as e:
        print(f"[ERROR] get_windowed_data: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/history/sessions/<date>')
def get_sessions_for_date(date):
    try:
        date_dir = DATA_STORAGE_DIR / date
        if not date_dir.exists():
            return jsonify({'sessions': []})
        
        sessions = []
        for session_dir in sorted(date_dir.iterdir(), reverse=True):
            if not session_dir.is_dir():
                continue
            
            metadata_file = session_dir / "metadata.json"
            metadata = {}
            if metadata_file.exists():
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
            
            # Conta samples - FIX: usa .jsonl e conta righe
            ecg_count = adc_count = temp_count = 0
            
            ecg_file = session_dir / "ECG_data.jsonl"
            if ecg_file.exists():
                with open(ecg_file, 'r') as f:
                    ecg_count = sum(1 for _ in f)
            
            adc_file = session_dir / "ADC_data.jsonl"
            if adc_file.exists():
                with open(adc_file, 'r') as f:
                    adc_count = sum(1 for _ in f)
            
            temp_file = session_dir / "TEMP_data.jsonl"
            if temp_file.exists():
                with open(temp_file, 'r') as f:
                    temp_count = sum(1 for _ in f)
            
            sessions.append({
                'session_id': session_dir.name,
                'start_time': metadata.get('start_time', ''),
                'end_time': metadata.get('end_time', ''),
                'duration': metadata.get('duration', 0),
                'status': metadata.get('status', 'unknown'),
                'total_samples': {
                    'ECG': ecg_count,
                    'ADC': adc_count,
                    'TEMP': temp_count
                }
            })
        
        return jsonify({'sessions': sessions})
    except Exception as e:
        print(f"[ERROR] get_sessions_for_date: {e}")
        return jsonify({'error': str(e)}), 500

# ====== TEST ENDPOINT FOR NOTIFICATIONS ======

@app.route('/api/test/notification/<anomaly_type>', methods=['POST'])
def test_notification(anomaly_type):
    """TEST ENDPOINT: Force send notification"""
    if anomaly_type not in ['ecg', 'piezo', 'temp']:
        return jsonify({'error': 'Invalid type'}), 400
    
    # Create fake data
    if anomaly_type == 'ecg':
        test_data = {
            'reconstruction_error': 0.5,
            'threshold': 0.1,
            'timestamp': datetime.now().isoformat()
        }
    elif anomaly_type == 'piezo':
        test_data = {
            'reconstruction_error': 0.3,
            'threshold': 0.1,
            'timestamp': datetime.now().isoformat()
        }
    else:  # temp
        test_data = {
            'temperature': 34.5,
            'threshold': 35.0,
            'anomaly_type': 'hypothermia',
            'severity': 'moderate',
            'duration_readings': 5,
            'timestamp': datetime.now().isoformat()
        }
    
    print(f"\n[TEST] Forcing {anomaly_type.upper()} notification")
    send_anomaly_notification(anomaly_type, test_data)
    
    return jsonify({
        'status': 'sent',
        'type': anomaly_type,
        'message': 'Test notification sent'
    })

# ====== SYNC API ENDPOINTS ======

SYNC_TOKEN = SYNC_CONFIG.SYNC_TOKEN

def verify_sync_token():
    """Verify sync token from request header"""
    token = request.headers.get('X-Sync-Token')
    return token == SYNC_TOKEN

@app.route('/api/users/sync', methods=['GET'])
def get_users_for_sync():
    """
    GET - Return all users for synchronization
    Headers required: X-Sync-Token
    """
    if not verify_sync_token():
        return jsonify({'success': False, 'error': 'Unauthorized - Invalid sync token'}), 401
    
    try:
        conn = sqlite3.connect('users.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM users")
        users = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        
        print(f"[Sync API] Sent {len(users)} users to remote")
        
        return jsonify({
            'success': True,
            'users': users,
            'count': len(users),
            'timestamp': datetime.now().isoformat()
        })
    
    except Exception as e:
        print(f"[Sync API] Error getting users: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/users/sync', methods=['POST'])
def receive_users_for_sync():
    """
    POST - Receive users to merge into local database
    Headers required: X-Sync-Token
    Body: {"users": [...]}
    """
    if not verify_sync_token():
        return jsonify({'success': False, 'error': 'Unauthorized - Invalid sync token'}), 401
    
    try:
        data = request.get_json()
        users = data.get('users', [])
        
        if not users:
            return jsonify({'success': False, 'error': 'No users provided'}), 400
        
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        
        updated = 0
        inserted = 0
        conflicts = []
        
        for user in users:
            # Check if user exists
            cursor.execute("SELECT id, updated_at FROM users WHERE id = ?", (user['id'],))
            existing = cursor.fetchone()
            
            if existing:
                existing_id, existing_updated_at = existing
                
                # Compare timestamps
                try:
                    incoming_updated = user.get('updated_at')
                    
                    if not incoming_updated or not existing_updated_at:
                        conflicts.append({
                            'id': user['id'],
                            'username': user['username'],
                            'reason': 'missing_timestamp'
                        })
                        continue
                    
                    # Parse timestamps
                    incoming_ts = datetime.fromisoformat(incoming_updated.replace('Z', '+00:00'))
                    existing_ts = datetime.fromisoformat(existing_updated_at.replace('Z', '+00:00'))
                    
                    # Compare (with 1 second tolerance)
                    diff = abs((incoming_ts - existing_ts).total_seconds())
                    
                    if diff < 1:
                        # Same timestamp - already synced
                        continue
                    elif incoming_ts > existing_ts:
                        # Incoming is newer - update
                        cursor.execute('''
                            UPDATE users 
                            SET username=?, password_hash=?, nome=?, cognome=?, ruolo=?, 
                                created_at=?, last_login=?, updated_at=?
                            WHERE id=?
                        ''', (
                            user['username'], user['password_hash'], user['nome'],
                            user['cognome'], user['ruolo'], user.get('created_at'),
                            user.get('last_login'), user['updated_at'], user['id']
                        ))
                        updated += 1
                        print(f"[Sync API] ✓ Updated user {user['id']} ({user['username']}) - incoming newer")
                    else:
                        # Existing is newer - conflict
                        conflicts.append({
                            'id': user['id'],
                            'username': user['username'],
                            'reason': 'local_newer',
                            'local_ts': existing_updated_at,
                            'incoming_ts': incoming_updated
                        })
                        print(f"[Sync API] ⚠ Conflict: user {user['id']} ({user['username']}) - local is newer")
                
                except Exception as ts_error:
                    print(f"[Sync API] Error comparing timestamps for user {user['id']}: {ts_error}")
                    conflicts.append({
                        'id': user['id'],
                        'username': user['username'],
                        'reason': 'timestamp_parse_error'
                    })
            
            else:
                # New user - insert
                cursor.execute('''
                    INSERT INTO users (id, username, password_hash, nome, cognome, ruolo, created_at, last_login, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    user['id'], user['username'], user['password_hash'], user['nome'],
                    user['cognome'], user['ruolo'], user.get('created_at'),
                    user.get('last_login'), user.get('updated_at')
                ))
                inserted += 1
                print(f"[Sync API] ✓ Inserted new user {user['id']} ({user['username']})")
        
        conn.commit()
        conn.close()
        
        if conflicts:
            print(f"[Sync API] ⚠ {len(conflicts)} conflicts detected")
        
        return jsonify({
            'success': True,
            'updated': updated,
            'inserted': inserted,
            'conflicts': conflicts,
            'timestamp': datetime.now().isoformat()
        })
    
    except Exception as e:
        print(f"[Sync API] Error receiving users: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

# ====== SOCKETIO EVENTS ======

@socketio.on('connect', namespace='/data')
def handle_connect():
    """Client connected"""
    print(f"[Dashboard] Client connected: {request.sid}")
    emit('connection_response', {'status': 'connected'})

@socketio.on('disconnect', namespace='/data')
def handle_disconnect():
    """Client disconnected"""
    print(f"[Dashboard] Client disconnected: {request.sid}")

@socketio.on('request_data', namespace='/data')
def handle_data_request(data):
    """Client requests data"""
    signal = data.get('signal', 'ECG')
    if validate_signal_name(signal):
        emit('data_update', {
            'signal': signal,
            'data': prepare_chart_data(signal)
        })


# ====== BACKGROUND THREADS ======

def background_status_updater():
    """Thread for periodic status updates"""
    while True:
        time.sleep(2)
        if state.device_connected or state.mqtt_connected:
            socketio.emit('status_update', {
                'stats': state.stats,
                'packet_count': state.packet_count,
                'uptime': int(time.time() - state.start_time) if state.start_time else 0
            }, namespace='/data')

def background_anomaly_checker():
    """Thread for periodic anomaly checks"""
    while True:
        time.sleep(3)
        check_for_new_anomalies()

def mqtt_thread():
    """Thread MQTT con protezione restart"""
    import sys
    if sys.argv[0].endswith('dashboard_server_cloud.py') and 'WERKZEUG_RUN_MAIN' not in os.environ:
        return  # Skip nel main process di Flask debug
    
    while True:
        try:
            print(f"[MQTT] Connecting to broker at {MQTT_BROKER}:{MQTT_PORT}...")
            mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
            mqtt_client.loop_forever()
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[MQTT] Error: {e}, retrying in 5s...")
            time.sleep(5)

# ====== SYSTEM LOGS API ======

@app.route('/api/system/logs')
def get_system_logs():
    """Get system logs with optional filters"""
    try:
        category = request.args.get('category', '')
        level = request.args.get('level', '')
        limit = int(request.args.get('limit', 500))
        
        # Filter logs
        filtered_logs = list(system_logs)
        
        if category:
            filtered_logs = [log for log in filtered_logs if log['category'] == category]
        
        if level:
            filtered_logs = [log for log in filtered_logs if log['level'] == level]
        
        # Apply limit
        filtered_logs = filtered_logs[-limit:]
        
        return jsonify({
            'success': True,
            'logs': filtered_logs,
            'total': len(filtered_logs)
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/system/logs/export')
def export_system_logs():
    """Export system logs as JSON"""
    try:
        category = request.args.get('category', '')
        level = request.args.get('level', '')
        
        # Filter logs
        filtered_logs = list(system_logs)
        
        if category:
            filtered_logs = [log for log in filtered_logs if log['category'] == category]
        
        if level:
            filtered_logs = [log for log in filtered_logs if log['level'] == level]
        
        export_data = {
            'exported_at': datetime.now().isoformat(),
            'total_logs': len(filtered_logs),
            'filters': {
                'category': category if category else 'all',
                'level': level if level else 'all'
            },
            'logs': filtered_logs
        }
        
        return jsonify(export_data)
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ====== MODEL TRAINING API ======

@app.route('/api/training/sessions')
@require_auth
def get_training_sessions():
    """Get available sessions for training"""
    try:
        loader = SessionDataLoader()
        sessions = loader.get_available_sessions()
        
        return jsonify({
            'success': True,
            'sessions': sessions,
            'total': len(sessions)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/training/start', methods=['POST'])
@require_auth
def start_training():
    """Start a new training job"""
    try:
        data = request.json
        model_type = data.get('model_type')  # 'ECG' or 'PIEZO'
        model_config = data.get('model_config')  # {name, version, description}
        sessions = data.get('sessions')  # List of session IDs
        
        if not model_type or not model_config or not sessions:
            return jsonify({'success': False, 'error': 'Missing required parameters'}), 400
        
        if model_type not in ['ECG', 'PIEZO']:
            return jsonify({'success': False, 'error': 'Invalid model_type'}), 400
        
        # Create training
        training_id = training_manager.create_training(model_type, model_config, sessions)
        
        # Start training in background thread
        def train_in_background():
            try:
                if model_type == 'ECG':
                    from model_trainer_ecg import train_ecg_model
                    train_ecg_model(training_id, sessions, model_config, training_manager)
                else:  # PIEZO
                    from model_trainer_piezo import train_piezo_model
                    train_piezo_model(training_id, sessions, model_config, training_manager)
            except Exception as e:
                print(f"[Training] Error in background training: {e}")
                training_manager.fail_training(training_id, str(e))
        
        training_thread = threading.Thread(target=train_in_background, daemon=True)
        training_thread.start()
        
        add_system_log('Dashboard', f'Started training: {model_config["name"]} ({training_id})', 'INFO')
        
        return jsonify({
            'success': True,
            'training_id': training_id,
            'message': 'Training started successfully'
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/training/progress/<training_id>')
@require_auth
def get_training_progress(training_id):
    """Get training progress"""
    try:
        progress = training_manager.get_progress(training_id)
        
        if progress is None:
            return jsonify({'success': False, 'error': 'Training not found'}), 404
        
        return jsonify({
            'success': True,
            'progress': progress
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/training/list')
@require_auth
def list_trainings():
    """List all trainings"""
    try:
        trainings = training_manager.get_all_trainings()
        
        return jsonify({
            'success': True,
            'trainings': trainings,
            'total': len(trainings)
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/training/details/<training_id>')
@require_auth
def get_training_details(training_id):
    """Get full training details"""
    try:
        details = training_manager.get_training_details(training_id)
        
        if details is None:
            return jsonify({'success': False, 'error': 'Training not found'}), 404
        
        return jsonify({
            'success': True,
            'details': details
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/training/<training_id>', methods=['DELETE'])
@require_auth
def delete_training(training_id):
    """Delete a training"""
    try:
        success = training_manager.delete_training(training_id)
        
        if success:
            add_system_log('Dashboard', f'Deleted training: {training_id}', 'INFO')
            return jsonify({'success': True, 'message': 'Training deleted'})
        else:
            return jsonify({'success': False, 'error': 'Training not found'}), 404
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/training/download/<training_id>/<file_type>')
@require_auth
def download_training_file(training_id, file_type):
    """Download training files"""
    try:
        from flask import send_file
        
        if file_type == 'model':
            file_path = training_manager.get_file_path(training_id, 'model')
            if file_path and file_path.exists():
                return send_file(file_path, as_attachment=True, download_name='model.tflite')
        
        elif file_type == 'config':
            file_path = training_manager.get_file_path(training_id, 'config')
            if file_path and file_path.exists():
                return send_file(file_path, as_attachment=True, download_name='config.json')
        
        elif file_type == 'training_config':
            file_path = training_manager.get_file_path(training_id, 'training_config')
            if file_path and file_path.exists():
                return send_file(file_path, as_attachment=True, download_name='training_config.json')
        
        elif file_type == 'sessions':
            file_path = training_manager.get_file_path(training_id, 'sessions')
            if file_path and file_path.exists():
                return send_file(file_path, as_attachment=True, download_name='training_sessions.json')
        
        elif file_type == 'log':
            file_path = training_manager.get_file_path(training_id, 'log')
            if file_path and file_path.exists():
                return send_file(file_path, as_attachment=True, download_name='training_log.txt')
        
        elif file_type == 'charts':
            # Create zip with all charts
            training_dir = Path(training_manager.models_path) / training_id
            charts_dir = training_dir / 'charts'
            
            if not charts_dir.exists():
                return jsonify({'success': False, 'error': 'Charts not found'}), 404
            
            # Create in-memory zip
            memory_file = BytesIO()
            with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
                for chart_file in charts_dir.glob('*.png'):
                    zf.write(chart_file, chart_file.name)
            
            memory_file.seek(0)
            return send_file(
                memory_file,
                mimetype='application/zip',
                as_attachment=True,
                download_name=f'{training_id}_charts.zip'
            )
        
        elif file_type == 'all':
            # Create complete package zip
            training_dir = Path(training_manager.models_path) / training_id
            
            memory_file = BytesIO()
            with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
                # Add model files
                for file_name in ['model.tflite', 'config.json', 'training_config.json', 
                                  'training_sessions.json', 'training_log.txt']:
                    file_path = training_dir / file_name
                    if file_path.exists():
                        zf.write(file_path, file_name)
                
                # Add charts
                charts_dir = training_dir / 'charts'
                if charts_dir.exists():
                    for chart_file in charts_dir.glob('*.png'):
                        zf.write(chart_file, f'charts/{chart_file.name}')
            
            memory_file.seek(0)
            return send_file(
                memory_file,
                mimetype='application/zip',
                as_attachment=True,
                download_name=f'{training_id}_complete.zip'
            )
        
        return jsonify({'success': False, 'error': 'File not found'}), 404
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/training/chart/<training_id>/<chart_name>')
@require_auth
def get_training_chart(training_id, chart_name):
    """Get a specific chart image"""
    try:
        from flask import send_file
        
        print(f"[DEBUG] get_training_chart called:")
        print(f"  training_id: {training_id}")
        print(f"  chart_name: {chart_name}")
        
        chart_path = training_manager.get_chart_path(training_id, chart_name)
        print(f"  chart_path: {chart_path}")
        print(f"  exists: {chart_path.exists() if chart_path else 'None'}")
        
        if chart_path and chart_path.exists():
            return send_file(chart_path, mimetype='image/png')
        else:
            print(f"  ERROR: Chart not found at {chart_path}")
            return jsonify({'success': False, 'error': 'Chart not found'}), 404
    
    except Exception as e:
        print(f"  EXCEPTION: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ====== MAIN FUNCTION ======

def run_dashboard(host='0.0.0.0', port=5002, debug=False):
    """Start the cloud dashboard server"""
    
    # ====== SETUP LOGGING TO FILE ======
    log_file = open('system.log', 'a', buffering=1)
    sys.stdout = log_file
    sys.stderr = log_file
    
    print(f"[Dashboard] Starting cloud dashboard server on {host}:{port}")
    print(f"[Dashboard] Storage directory: {BASE_STORAGE_DIR}")
    
    # Ensure directories exist
    BASE_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    DATA_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    ANOMALY_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static/js', exist_ok=True)
    os.makedirs('static/css', exist_ok=True)
    
    # ====== START FILE LOG WATCHER ======
    # Pass add_system_log explicitly to ensure it's available
    log_watcher = setup_file_log_watcher("system.log", log_callback=add_system_log)
    log_watcher.start()
    print("[FileLogWatcher] Monitoring system.log for real-time debug logs")
    
    # Start MQTT thread
    mqtt_bg_thread = threading.Thread(target=mqtt_thread, daemon=True)
    mqtt_bg_thread.start()
    print("[MQTT] Background thread started")
    
    # Start status updater thread
    status_thread = threading.Thread(target=background_status_updater, daemon=True)
    status_thread.start()
    print("[Dashboard] Status updater thread started")
    
    # Start anomaly checker thread
    anomaly_thread = threading.Thread(target=background_anomaly_checker, daemon=True)
    anomaly_thread.start()
    print("[Dashboard] Anomaly checker thread started")
    
    # ====== START SYNC SERVICE ======
    global sync_service
    print("\n" + "=" * 60)
    print("STARTING DATABASE SYNCHRONIZATION SERVICE")
    print("=" * 60)
    print(f"[Sync] Instance: CLOUD (AWS)")
    print(f"[Sync] Local API (Raspberry): {SYNC_CONFIG.LOCAL_API_URL}")
    print(f"[Sync] Sync interval: {SYNC_CONFIG.SYNC_INTERVAL} seconds")
    print(f"[Sync] ⚠ Remember to configure:")
    print(f"       - LOCAL_API_URL with Raspberry IP")
    print(f"       - SYNC_TOKEN (must match Raspberry)")
    
    sync_service = DatabaseSyncService(SYNC_CONFIG)
    sync_service.start()
    print("[Sync] ✓ Synchronization service started")
    print("=" * 60 + "\n")
    # =================================
    
    # Run Flask-SocketIO server
    socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)

if __name__ == '__main__':
    run_dashboard(debug=True)