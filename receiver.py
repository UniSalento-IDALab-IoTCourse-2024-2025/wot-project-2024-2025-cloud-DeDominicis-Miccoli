"""
MQTT Receiver for EC2 Server
Receives and stores all data from IIT devices:
- Real-time data
- Storage data
- Anomaly logs
- File synchronization
- Maintains identical folder structure to local

Installation on EC2:
    pip install paho-mqtt

Run as service:
    sudo systemctl enable mqtt_receiver
    sudo systemctl start mqtt_receiver
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List
import paho.mqtt.client as mqtt
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('mqtt_receiver.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('MQTTReceiver')


class MQTTReceiver:
    """
    MQTT Receiver that maintains synchronized storage with local device
    """
    
    def __init__(self, 
                 broker: str = "localhost",
                 port: int = 1883,
                 username: str = None,
                 password: str = None,
                 base_storage_dir: str = "./var/iit_data"):
        """
        Initialize MQTT Receiver
        
        Args:
            broker: MQTT broker address (usually localhost on EC2)
            port: MQTT broker port
            username: MQTT username (optional)
            password: MQTT password (optional)
            base_storage_dir: Base directory for storing all data
        """
        self.broker = broker
        self.port = port
        self.username = username
        self.password = password
        
        # Storage directories
        self.base_storage_dir = Path(base_storage_dir)
        self.data_storage_dir = self.base_storage_dir / "data_storage"
        self.anomaly_logs_dir = self.base_storage_dir / "anomaly_logs"
        self.realtime_buffer_dir = self.base_storage_dir / "realtime_buffer"
        
        # Create directories
        self._create_directories()
        
        # MQTT client
        self.client = mqtt.Client(client_id="iit_receiver_ec2")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect
        
        # Set credentials if provided
        if username and password:
            self.client.username_pw_set(username, password)
        
        # Statistics
        self.stats = {
            'messages_received': 0,
            'realtime_packets': 0,
            'storage_packets': 0,
            'anomalies_received': 0,
            'files_synced': 0,
            'files_deleted': 0,
            'errors': 0,
            'start_time': datetime.now().isoformat()
        }
        
        # Active sessions
        self.active_sessions = {}
        
        logger.info(f"Initialized MQTT Receiver - Storage: {self.base_storage_dir}")
    
    def _create_directories(self):
        """Create all necessary storage directories"""
        dirs = [
            self.base_storage_dir,
            self.data_storage_dir,
            self.anomaly_logs_dir,
            self.realtime_buffer_dir
        ]
        
        for dir_path in dirs:
            dir_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Ensured directory exists: {dir_path}")
    
    def _on_connect(self, client, userdata, flags, rc):
        """Callback when connected to MQTT broker"""
        if rc == 0:
            logger.info(f"Connected to MQTT broker {self.broker}:{self.port}")
            
            # Subscribe to all topics
            topics = [
                ('iit/device/+/realtime/+', 1),
                ('iit/device/+/storage/+', 1),
                ('iit/device/+/anomalies/+', 1),
                ('iit/device/+/session', 1),
                ('iit/device/+/status', 1),
                ('iit/device/+/metadata', 1),
                ('iit/device/+/sync/+', 1)
            ]
            
            # Subscribe with wildcard for all devices
            for topic, qos in topics:
                client.subscribe(topic, qos)
                logger.info(f"Subscribed to: {topic}")
            
            # Also subscribe without device ID for backward compatibility
            simple_topics = [
                ('iit/device/realtime/+', 1),
                ('iit/device/storage/+', 1),
                ('iit/device/anomalies/+', 1),
                ('iit/device/session', 1),
                ('iit/device/status', 1),
                ('iit/device/metadata', 1),
                ('iit/device/sync/+', 1)
            ]
            
            for topic, qos in simple_topics:
                client.subscribe(topic, qos)
            
        else:
            logger.error(f"Connection failed with code {rc}")
    
    def _on_disconnect(self, client, userdata, rc):
        """Callback when disconnected from broker"""
        if rc != 0:
            logger.warning(f"Unexpected disconnection (code: {rc})")
    
    def _on_message(self, client, userdata, msg):
        """Main message handler - routes to specific handlers"""
        try:
            self.stats['messages_received'] += 1
            
            # Parse message
            payload = json.loads(msg.payload.decode())
            topic = msg.topic
            
            # Route to appropriate handler
            if '/realtime/' in topic:
                self._handle_realtime(payload, topic)
            elif '/storage/' in topic:
                self._handle_storage(payload, topic)
            elif '/anomalies/' in topic:
                self._handle_anomaly(payload, topic)
            elif '/session' in topic:
                self._handle_session(payload)
            elif '/status' in topic:
                self._handle_status(payload)
            elif '/metadata' in topic:
                self._handle_metadata(payload)
            elif '/sync/' in topic:
                self._handle_sync(payload, topic)
            else:
                logger.warning(f"Unknown topic: {topic}")
            
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            self.stats['errors'] += 1
    
    def _handle_realtime(self, payload: Dict, topic: str):
        """Handle real-time data packets"""
        try:
            signal = payload.get('signal')
            frames = payload.get('frames', [])
            timestamp = payload.get('timestamp')
            
            self.stats['realtime_packets'] += 1
            
            # Save to real-time buffer (optional - for debugging)
            buffer_file = self.realtime_buffer_dir / f"{signal}_latest.json"
            with open(buffer_file, 'w') as f:
                json.dump({
                    'signal': signal,
                    'timestamp': timestamp,
                    'frame_count': len(frames),
                    'last_values': frames[-10:] if len(frames) > 10 else frames
                }, f, indent=2)
            
            logger.debug(f"Real-time: {signal} - {len(frames)} frames")
            
        except Exception as e:
            logger.error(f"Error handling real-time data: {e}")
    
    def _handle_storage(self, payload: Dict, topic: str):
        """Handle storage data packets - save to session files"""
        try:
            signal = payload.get('signal')
            frames = payload.get('frames', [])
            timestamp = payload.get('timestamp')
            
            self.stats['storage_packets'] += 1
            
            # Storage data should be associated with an active session
            # For now, buffer it if no session is active
            # In practice, session should be started before data arrives
            
            logger.debug(f"Storage: {signal} - {len(frames)} frames")
            
        except Exception as e:
            logger.error(f"Error handling storage data: {e}")
    
    def _handle_anomaly(self, payload: Dict, topic: str):
        """Handle anomaly detection results"""
        try:
            anomaly_type = payload.get('anomaly_type', '').upper()
            timestamp = payload.get('timestamp')
            data = payload.get('data', {})
            
            self.stats['anomalies_received'] += 1
            
            # Check if this is a full log file or single anomaly
            if 'anomalies' in payload:
                # Full log file
                self._handle_anomaly_log_file(payload)
            else:
                # Single anomaly
                self._save_single_anomaly(anomaly_type, data, timestamp)
            
        except Exception as e:
            logger.error(f"Error handling anomaly: {e}")
    
    def _save_single_anomaly(self, anomaly_type: str, data: Dict, timestamp: str):
        """Save single anomaly to daily log file"""
        try:
            # Get date from timestamp
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            date_str = dt.strftime("%Y%m%d")
            
            # Determine filename based on type
            if anomaly_type == 'ECG':
                filename = f"anomalies_{date_str}.json"
            elif anomaly_type == 'PIEZO':
                filename = f"piezo_anomalies_{date_str}.json"
            elif anomaly_type == 'TEMP':
                filename = f"temp_anomalies_{date_str}.json"
            else:
                logger.warning(f"Unknown anomaly type: {anomaly_type}")
                return
            
            log_file = self.anomaly_logs_dir / filename
            
            # Read existing data
            if log_file.exists():
                with open(log_file, 'r') as f:
                    anomalies = json.load(f)
            else:
                anomalies = []
            
            # Prepare anomaly entry
            entry = {
                'timestamp': timestamp,
                'date': dt.strftime("%Y-%m-%d"),
                'time': dt.strftime("%H:%M:%S.%f")[:-3],
                **data
            }
            
            # Append
            anomalies.append(entry)
            
            # Write back
            with open(log_file, 'w') as f:
                json.dump(anomalies, f, indent=2)
            
            logger.info(f"Anomaly saved: {anomaly_type} at {dt.strftime('%H:%M:%S')}")
            
        except Exception as e:
            logger.error(f"Error saving single anomaly: {e}")
    
    def _handle_anomaly_log_file(self, payload: Dict):
        """Handle complete anomaly log file"""
        try:
            anomaly_type = payload.get('anomaly_type', '').upper()
            file_name = payload.get('file_name')
            anomalies = payload.get('anomalies', [])
            
            # Save to anomaly logs directory
            log_file = self.anomaly_logs_dir / file_name
            
            with open(log_file, 'w') as f:
                json.dump(anomalies, f, indent=2)
            
            logger.info(f"Anomaly log file saved: {file_name} ({len(anomalies)} anomalies)")
            self.stats['files_synced'] += 1
            
        except Exception as e:
            logger.error(f"Error handling anomaly log file: {e}")
    
    def _handle_session(self, payload: Dict):
        """Handle session events (start/end)"""
        try:
            event = payload.get('event')
            session_id = payload.get('session_id')
            
            if event == 'session_start':
                metadata = payload.get('metadata', {})
                self._start_session(session_id, metadata)
            elif event == 'session_end':
                statistics = payload.get('statistics', {})
                self._end_session(session_id, statistics)
            
        except Exception as e:
            logger.error(f"Error handling session event: {e}")
    
    def _start_session(self, session_id: str, metadata: Dict):
        """Start new data collection session"""
        try:
            # Extract date from session_id (format: YYYYMMDD_HHMMSS)
            date_part = session_id.split('_')[0]
            
            # Create session directory
            date_dir = self.data_storage_dir / date_part
            date_dir.mkdir(exist_ok=True)
            
            session_dir = date_dir / session_id
            session_dir.mkdir(exist_ok=True)
            
            # Save metadata
            metadata_file = session_dir / "metadata.json"
            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)
            
            # Track active session
            self.active_sessions[session_id] = {
                'dir': session_dir,
                'metadata': metadata,
                'start_time': datetime.now()
            }
            
            logger.info(f"Session started: {session_id}")
            
        except Exception as e:
            logger.error(f"Error starting session: {e}")
    
    def _end_session(self, session_id: str, statistics: Dict):
        """End data collection session"""
        try:
            if session_id in self.active_sessions:
                session_info = self.active_sessions[session_id]
                session_dir = session_info['dir']
                
                # Update metadata with final statistics
                metadata_file = session_dir / "metadata.json"
                if metadata_file.exists():
                    with open(metadata_file, 'r') as f:
                        metadata = json.load(f)
                    
                    metadata['end_time'] = datetime.now().isoformat()
                    metadata['status'] = 'completed'
                    metadata['total_samples'] = statistics
                    
                    with open(metadata_file, 'w') as f:
                        json.dump(metadata, f, indent=2)
                
                # Remove from active sessions
                del self.active_sessions[session_id]
                
                logger.info(f"Session ended: {session_id}")
            
        except Exception as e:
            logger.error(f"Error ending session: {e}")
    
    def _handle_status(self, payload: Dict):
        """Handle device status updates"""
        try:
            status = payload.get('status')
            client_id = payload.get('client_id', 'unknown')
            
            logger.info(f"Device status: {client_id} - {status}")
            
        except Exception as e:
            logger.error(f"Error handling status: {e}")
    
    def _handle_metadata(self, payload: Dict):
        """Handle metadata updates"""
        try:
            session_id = payload.get('session_id')
            metadata = payload.get('metadata', {})
            
            if session_id and session_id in self.active_sessions:
                session_dir = self.active_sessions[session_id]['dir']
                metadata_file = session_dir / "metadata.json"
                
                # Update metadata file
                if metadata_file.exists():
                    with open(metadata_file, 'r') as f:
                        existing = json.load(f)
                    existing.update(metadata)
                    metadata = existing
                
                with open(metadata_file, 'w') as f:
                    json.dump(metadata, f, indent=2)
            
        except Exception as e:
            logger.error(f"Error handling metadata: {e}")
    
    def _handle_sync(self, payload: Dict, topic: str):
        """Handle file synchronization events"""
        try:
            action = payload.get('action')
            
            if action == 'file_update':
                self._sync_file_update(payload)
            elif action == 'file_delete':
                self._sync_file_delete(payload)
            elif action == 'structure_sync':
                self._sync_folder_structure(payload)
            elif action == 'cleanup':
                self._sync_cleanup(payload)
            else:
                logger.warning(f"Unknown sync action: {action}")
            
        except Exception as e:
            logger.error(f"Error handling sync: {e}")
    
    def _sync_file_update(self, payload: Dict):
        """Sync file update from device"""
        try:
            file_path = payload.get('file_path')
            content = payload.get('content')
            file_type = payload.get('file_type')
            
            # Reconstruct path on server
            path = Path(file_path)
            
            # Determine target directory
            if 'data_storage' in str(path):
                # Extract relative path from data_storage
                parts = path.parts
                idx = parts.index('data_storage')
                rel_path = Path(*parts[idx+1:])
                target_path = self.data_storage_dir / rel_path
            elif 'anomaly_logs' in str(path):
                parts = path.parts
                idx = parts.index('anomaly_logs')
                rel_path = Path(*parts[idx+1:])
                target_path = self.anomaly_logs_dir / rel_path
            else:
                logger.warning(f"Unknown file path structure: {file_path}")
                return
            
            # Create parent directories
            target_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write content
            with open(target_path, 'w') as f:
                f.write(content)
            
            self.stats['files_synced'] += 1
            logger.info(f"File synced: {target_path.name}")
            
        except Exception as e:
            logger.error(f"Error syncing file update: {e}")
    
    def _sync_file_delete(self, payload: Dict):
        """Sync file deletion from device"""
        try:
            file_path = payload.get('file_path')
            
            # Reconstruct path on server
            path = Path(file_path)
            
            if 'data_storage' in str(path):
                parts = path.parts
                idx = parts.index('data_storage')
                rel_path = Path(*parts[idx+1:])
                target_path = self.data_storage_dir / rel_path
            elif 'anomaly_logs' in str(path):
                parts = path.parts
                idx = parts.index('anomaly_logs')
                rel_path = Path(*parts[idx+1:])
                target_path = self.anomaly_logs_dir / rel_path
            else:
                logger.warning(f"Unknown file path structure: {file_path}")
                return
            
            # Delete file if exists
            if target_path.exists():
                target_path.unlink()
                self.stats['files_deleted'] += 1
                logger.info(f"File deleted: {target_path.name}")
            
        except Exception as e:
            logger.error(f"Error syncing file deletion: {e}")
    
    def _sync_folder_structure(self, payload: Dict):
        """Sync entire folder structure"""
        try:
            structure = payload.get('structure', {})
            
            logger.info("Syncing folder structure...")
            
            # Sync data_storage
            if 'data_storage' in structure:
                self._create_folder_structure(
                    structure['data_storage'],
                    self.data_storage_dir
                )
            
            # Sync anomaly_logs
            if 'anomaly_logs' in structure:
                self._create_folder_structure(
                    structure['anomaly_logs'],
                    self.anomaly_logs_dir
                )
            
            logger.info("Folder structure synced")
            
        except Exception as e:
            logger.error(f"Error syncing folder structure: {e}")
    
    def _create_folder_structure(self, structure: Dict, base_path: Path):
        """Recursively create folder structure"""
        if structure.get('type') == 'directory':
            base_path.mkdir(parents=True, exist_ok=True)
            
            for name, child in structure.get('children', {}).items():
                child_path = base_path / name
                if child.get('type') == 'directory':
                    self._create_folder_structure(child, child_path)
                # Files will be synced via file_update messages
    
    def _sync_cleanup(self, payload: Dict):
        """Sync cleanup event (files deleted due to retention)"""
        try:
            deleted_items = payload.get('deleted_items', [])
            
            for item in deleted_items:
                path = Path(item)
                
                # Determine target path on server
                if 'data_storage' in str(path):
                    parts = path.parts
                    idx = parts.index('data_storage')
                    rel_path = Path(*parts[idx+1:])
                    target_path = self.data_storage_dir / rel_path
                elif 'anomaly_logs' in str(path):
                    parts = path.parts
                    idx = parts.index('anomaly_logs')
                    rel_path = Path(*parts[idx+1:])
                    target_path = self.anomaly_logs_dir / rel_path
                else:
                    continue
                
                # Delete if exists
                if target_path.exists():
                    if target_path.is_dir():
                        import shutil
                        shutil.rmtree(target_path)
                    else:
                        target_path.unlink()
                    
                    logger.info(f"Cleanup deleted: {target_path}")
            
            logger.info(f"Cleanup synced: {len(deleted_items)} items")
            
        except Exception as e:
            logger.error(f"Error syncing cleanup: {e}")
    
    def start(self):
        """Start the MQTT receiver"""
        try:
            logger.info(f"Connecting to MQTT broker at {self.broker}:{self.port}...")
            self.client.connect(self.broker, self.port, keepalive=60)
            
            logger.info("Starting MQTT loop...")
            self.client.loop_forever()
            
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            self.stop()
        except Exception as e:
            logger.error(f"Error starting receiver: {e}")
    
    def stop(self):
        """Stop the MQTT receiver"""
        logger.info("Stopping MQTT receiver...")
        self.client.loop_stop()
        self.client.disconnect()
        
        # Print final statistics
        logger.info("=" * 60)
        logger.info("FINAL STATISTICS")
        logger.info("=" * 60)
        for key, value in self.stats.items():
            logger.info(f"{key}: {value}")
        logger.info("=" * 60)


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='MQTT Receiver for IIT Device Data')
    parser.add_argument('--broker', default='localhost', help='MQTT broker address')
    parser.add_argument('--port', type=int, default=1883, help='MQTT broker port')
    parser.add_argument('--username', help='MQTT username')
    parser.add_argument('--password', help='MQTT password')
    parser.add_argument('--storage-dir', default='./var/iit_data', 
                       help='Base storage directory')
    
    args = parser.parse_args()
    
    # Create receiver
    receiver = MQTTReceiver(
        broker=args.broker,
        port=args.port,
        username=args.username,
        password=args.password,
        base_storage_dir=args.storage_dir
    )
    
    # Start receiver
    receiver.start()


if __name__ == "__main__":
    main()