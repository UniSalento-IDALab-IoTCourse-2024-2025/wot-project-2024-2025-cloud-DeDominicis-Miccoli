"""
Data Loader for Training Models
Loads ECG/PIEZO data from JSON sessions and converts to numpy arrays
"""

import json
import numpy as np
from pathlib import Path
from datetime import datetime
import os

class SessionDataLoader:
    """
    Loads data from stored JSON sessions for model training
    """
    
    def __init__(self, data_storage_path='var/iit_data/data_storage'):
        self.data_storage_path = Path(data_storage_path)
    
    def get_available_sessions(self):
        """
        Get list of all available sessions with metadata
        
        Returns:
            list: List of session dicts with metadata
        """
        sessions = []
        
        if not self.data_storage_path.exists():
            return sessions
        
        # Iterate through date folders (YYYYMMDD)
        for date_folder in sorted(self.data_storage_path.iterdir()):
            if not date_folder.is_dir():
                continue
            
            # Iterate through session folders (YYYYMMDD_HHMMSS)
            for session_folder in sorted(date_folder.iterdir()):
                if not session_folder.is_dir():
                    continue
                
                session_id = session_folder.name
                date_str = session_folder.parent.name
                time_str = session_id.split('_')[1] if '_' in session_id else '000000'
                
                # Calculate session metadata
                metadata_file = session_folder / 'metadata.json'
                ecg_file = session_folder / 'ECG_data.jsonl'
                adc_file = session_folder / 'ADC_data.jsonl'
                
                if not (ecg_file.exists() or adc_file.exists()):
                    continue
                
                # Get file sizes
                total_size = 0
                files_info = {}
                
                if ecg_file.exists():
                    size = ecg_file.stat().st_size
                    total_size += size
                    files_info['ecg_size_mb'] = size / (1024 * 1024)
                
                if adc_file.exists():
                    size = adc_file.stat().st_size
                    total_size += size
                    files_info['adc_size_mb'] = size / (1024 * 1024)
                
                # Estimate duration and samples (assuming 250 Hz for ECG/PIEZO)
                duration_seconds = 0
                samples_count = 0
                
                # Quick count of lines to estimate samples
                if ecg_file.exists():
                    with open(ecg_file, 'r') as f:
                        samples_count = sum(1 for _ in f)
                    duration_seconds = samples_count / 250  # 250 Hz sampling
                
                sessions.append({
                    'session_id': session_id,
                    'date': date_str,
                    'time': time_str,
                    'date_formatted': f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}",
                    'time_formatted': f"{time_str[:2]}:{time_str[2:4]}:{time_str[4:6]}",
                    'path': str(session_folder),
                    'duration_seconds': int(duration_seconds),
                    'duration_formatted': self._format_duration(duration_seconds),
                    'samples_count': samples_count,
                    'size_mb': round(total_size / (1024 * 1024), 2),
                    'has_ecg': ecg_file.exists(),
                    'has_adc': adc_file.exists(),
                    **files_info
                })
        
        return sessions
    
    def _format_duration(self, seconds):
        """Format duration in human readable format"""
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s" if secs > 0 else f"{minutes}m"
        else:
            hours = int(seconds / 3600)
            minutes = int((seconds % 3600) / 60)
            return f"{hours}h {minutes}m" if minutes > 0 else f"{hours}h"
    
    def load_ecg_data(self, session_ids):
        """
        Load ECG data from multiple sessions
        
        Args:
            session_ids: List of session IDs (e.g., ['20251121_181250'])
        
        Returns:
            tuple: (data_array, sessions_metadata)
        """
        all_data = []
        sessions_metadata = []
        
        print(f"\n[DataLoader] Loading ECG data from {len(session_ids)} sessions...")
        
        for session_id in session_ids:
            # Find session path
            date_str = session_id.split('_')[0]
            session_path = self.data_storage_path / date_str / session_id / 'ECG_data.jsonl'
            
            if not session_path.exists():
                print(f"   Session not found: {session_id}")
                continue
            
            print(f"  Loading {session_id}...")
            
            # Load ECG data from JSONL
            session_data = []
            with open(session_path, 'r') as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        # ECG_data.jsonl format: {"timestamp": 18345, "values": [4032]}
                        if 'values' in entry and len(entry['values']) > 0:
                            session_data.append(entry['values'][0])  # Extract ECG value
                    except json.JSONDecodeError:
                        continue
            
            if len(session_data) > 0:
                all_data.extend(session_data)
                
                sessions_metadata.append({
                    'session_id': session_id,
                    'samples': len(session_data),
                    'duration_seconds': len(session_data) / 250,  # 250 Hz
                    'path': str(session_path.parent)
                })
                
                print(f"     Loaded {len(session_data):,} samples")
        
        # Convert to numpy array
        data_array = np.array(all_data, dtype=np.float32)
        
        print(f"\n[DataLoader] Total ECG samples loaded: {len(data_array):,}")
        print(f"[DataLoader] Total duration: {self._format_duration(len(data_array) / 250)}")
        
        return data_array, sessions_metadata
    
    def load_piezo_data(self, session_ids, channel='all'):
        """
        Load PIEZO data from multiple sessions
        
        Args:
            session_ids: List of session IDs
            channel: 'all' (use all 3 channels), 0, 1, or 2 (specific channel)
        
        Returns:
            tuple: (data_array, sessions_metadata)
        """
        all_data = []
        sessions_metadata = []
        
        print(f"\n[DataLoader] Loading PIEZO data from {len(session_ids)} sessions...")
        print(f"[DataLoader] Channel mode: {channel}")
        
        for session_id in session_ids:
            # Find session path
            date_str = session_id.split('_')[0]
            session_path = self.data_storage_path / date_str / session_id / 'ADC_data.jsonl'
            
            if not session_path.exists():
                print(f"   Session not found: {session_id}")
                continue
            
            print(f"  Loading {session_id}...")
            
            # Load PIEZO data from JSONL
            session_data = []
            with open(session_path, 'r') as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        # ADC_data.jsonl format: {"timestamp": 18950, "values": [7817, 1257, 252]}
                        # values = [piezo_ch1, piezo_ch2, piezo_ch3]
                        if 'values' in entry and len(entry['values']) >= 3:
                            if channel == 'all':
                                # Use average of all 3 channels
                                avg_value = np.mean(entry['values'][:3])
                                session_data.append(avg_value)
                            else:
                                # Use specific channel
                                session_data.append(entry['values'][channel])
                    except (json.JSONDecodeError, IndexError):
                        continue
            
            if len(session_data) > 0:
                all_data.extend(session_data)
                
                sessions_metadata.append({
                    'session_id': session_id,
                    'samples': len(session_data),
                    'duration_seconds': len(session_data) / 250,  # 250 Hz
                    'path': str(session_path.parent)
                })
                
                print(f"    ✓ Loaded {len(session_data):,} samples")
        
        # Convert to numpy array
        data_array = np.array(all_data, dtype=np.float32)
        
        print(f"\n[DataLoader] Total PIEZO samples loaded: {len(data_array):,}")
        print(f"[DataLoader] Total duration: {self._format_duration(len(data_array) / 250)}")
        
        return data_array, sessions_metadata
    
    def save_sessions_info(self, sessions_metadata, output_path):
        """
        Save training_sessions.json file
        
        Args:
            sessions_metadata: List of session metadata dicts
            output_path: Path to save JSON file
        """
        total_duration = sum(s['duration_seconds'] for s in sessions_metadata)
        total_samples = sum(s['samples'] for s in sessions_metadata)
        
        sessions_info = {
            'sessions_used': [
                {
                    'session_id': s['session_id'],
                    'date': s['session_id'].split('_')[0],
                    'time': s['session_id'].split('_')[1] if '_' in s['session_id'] else '000000',
                    'duration_seconds': s['duration_seconds'],
                    'samples_count': s['samples'],
                    'path': s['path']
                }
                for s in sessions_metadata
            ],
            'total_sessions': len(sessions_metadata),
            'total_duration_seconds': total_duration,
            'total_duration_formatted': self._format_duration(total_duration),
            'total_samples': total_samples
        }
        
        with open(output_path, 'w') as f:
            json.dump(sessions_info, f, indent=2)
        
        print(f"[DataLoader] Saved sessions info: {output_path}")
        
        return sessions_info


# Test function
if __name__ == '__main__':
    loader = SessionDataLoader()
    sessions = loader.get_available_sessions()
    
    print(f"\nFound {len(sessions)} sessions:")
    for s in sessions[:5]:  # Show first 5
        print(f"  {s['session_id']} - {s['duration_formatted']} - {s['size_mb']} MB")