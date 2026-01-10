"""
Training Manager
Handles model training jobs, progress tracking, and file management
"""

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
import shutil

class TrainingManager:
    """
    Manages training jobs and their lifecycle
    """
    
    def __init__(self, models_path='var/iit_data/models'):
        self.models_path = Path(models_path)
        self.models_path.mkdir(parents=True, exist_ok=True)
        
        self.index_file = self.models_path / 'models_index.json'
        self.active_trainings = {}  # training_id -> training_info
        
        # Load existing index
        self._load_index()
    
    def _load_index(self):
        """Load models index from file"""
        if self.index_file.exists():
            with open(self.index_file, 'r') as f:
                self.index = json.load(f)
        else:
            self.index = {'trainings': []}
    
    def _save_index(self):
        """Save models index to file"""
        with open(self.index_file, 'w') as f:
            json.dump(self.index, f, indent=2)
    
    def generate_training_id(self):
        """Generate unique training ID"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        return f"training_{timestamp}"
    
    def create_training(self, model_type, model_config, sessions):
        """
        Create new training job
        
        Args:
            model_type: 'ECG' or 'PIEZO'
            model_config: Dict with name, version, description
            sessions: List of session IDs to use
        
        Returns:
            training_id: Unique ID for this training
        """
        training_id = self.generate_training_id()
        training_dir = self.models_path / training_id
        training_dir.mkdir(parents=True, exist_ok=True)
        
        # Create charts directory
        charts_dir = training_dir / 'charts'
        charts_dir.mkdir(exist_ok=True)
        
        # Create metadata
        metadata = {
            'training_id': training_id,
            'model_type': model_type,
            'model_config': model_config,
            'training_info': {
                'started_at': datetime.now().isoformat(),
                'completed_at': None,
                'duration_minutes': None,
                'final_epoch': None,
                'final_loss': None,
                'final_val_loss': None,
                'threshold': None
            },
            'status': 'initializing',
            'created_by': 'admin',  # TODO: Get from session
            'sessions_selected': sessions
        }
        
        # Save metadata
        metadata_file = training_dir / 'metadata.json'
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        # Add to index
        self.index['trainings'].insert(0, {  # Insert at beginning (newest first)
            'training_id': training_id,
            'model_type': model_type,
            'name': model_config['name'],
            'version': model_config['version'],
            'created_at': metadata['training_info']['started_at'],
            'status': 'initializing',
            'sessions_count': len(sessions)
        })
        self._save_index()
        
        # Add to active trainings
        self.active_trainings[training_id] = {
            'metadata': metadata,
            'progress': {
                'status': 'initializing',
                'epoch': 0,
                'total_epochs': 100,
                'loss': None,
                'val_loss': None,
                'progress_pct': 0,
                'message': 'Initializing training...'
            }
        }
        
        print(f"[TrainingManager] Created training: {training_id}")
        return training_id
    
    def update_progress(self, training_id, epoch, total_epochs, loss, val_loss, message='Training...'):
        """Update training progress"""
        if training_id not in self.active_trainings:
            return
        
        progress_pct = int((epoch / total_epochs) * 100)
        
        self.active_trainings[training_id]['progress'] = {
            'status': 'training',
            'epoch': epoch,
            'total_epochs': total_epochs,
            'loss': float(loss) if loss is not None else None,
            'val_loss': float(val_loss) if val_loss is not None else None,
            'progress_pct': progress_pct,
            'message': message
        }
    
    def get_progress(self, training_id):
        """Get current training progress"""
        if training_id in self.active_trainings:
            return self.active_trainings[training_id]['progress']
        
        # Check if training is completed
        training_dir = self.models_path / training_id
        metadata_file = training_dir / 'metadata.json'
        
        if metadata_file.exists():
            with open(metadata_file, 'r') as f:
                metadata = json.load(f)
            
            if metadata['status'] == 'completed':
                return {
                    'status': 'completed',
                    'epoch': metadata['training_info'].get('final_epoch', 100),
                    'total_epochs': metadata['training_info'].get('final_epoch', 100),
                    'loss': metadata['training_info'].get('final_loss'),
                    'val_loss': metadata['training_info'].get('final_val_loss'),
                    'progress_pct': 100,
                    'message': 'Training completed!'
                }
            elif metadata['status'] == 'failed':
                return {
                    'status': 'failed',
                    'progress_pct': 0,
                    'message': 'Training failed'
                }
        
        return None
    
    def complete_training(self, training_id, final_epoch, final_loss, final_val_loss, threshold):
        """Mark training as completed"""
        training_dir = self.models_path / training_id
        metadata_file = training_dir / 'metadata.json'
        
        if not metadata_file.exists():
            print(f"[TrainingManager] Error: Metadata not found for {training_id}")
            return
        
        # Load and update metadata
        with open(metadata_file, 'r') as f:
            metadata = json.load(f)
        
        started_at = datetime.fromisoformat(metadata['training_info']['started_at'])
        completed_at = datetime.now()
        duration_minutes = (completed_at - started_at).total_seconds() / 60
        
        metadata['training_info']['completed_at'] = completed_at.isoformat()
        metadata['training_info']['duration_minutes'] = round(duration_minutes, 2)
        metadata['training_info']['final_epoch'] = final_epoch
        metadata['training_info']['final_loss'] = float(final_loss)
        metadata['training_info']['final_val_loss'] = float(final_val_loss)
        metadata['training_info']['threshold'] = float(threshold)
        metadata['status'] = 'completed'
        
        # Save updated metadata
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        # Update index
        for training in self.index['trainings']:
            if training['training_id'] == training_id:
                training['status'] = 'completed'
                break
        self._save_index()
        
        # Update active trainings
        if training_id in self.active_trainings:
            self.active_trainings[training_id]['progress'] = {
                'status': 'completed',
                'epoch': final_epoch,
                'total_epochs': final_epoch,
                'loss': float(final_loss),
                'val_loss': float(final_val_loss),
                'progress_pct': 100,
                'message': 'Training completed!'
            }
        
        print(f"[TrainingManager] Training {training_id} completed in {duration_minutes:.1f} minutes")
    
    def fail_training(self, training_id, error_message):
        """Mark training as failed"""
        training_dir = self.models_path / training_id
        metadata_file = training_dir / 'metadata.json'
        
        if metadata_file.exists():
            with open(metadata_file, 'r') as f:
                metadata = json.load(f)
            
            metadata['status'] = 'failed'
            metadata['training_info']['completed_at'] = datetime.now().isoformat()
            metadata['training_info']['error'] = error_message
            
            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)
        
        # Update index
        for training in self.index['trainings']:
            if training['training_id'] == training_id:
                training['status'] = 'failed'
                break
        self._save_index()
        
        # Update active trainings
        if training_id in self.active_trainings:
            self.active_trainings[training_id]['progress'] = {
                'status': 'failed',
                'progress_pct': 0,
                'message': f'Training failed: {error_message}'
            }
        
        print(f"[TrainingManager] Training {training_id} failed: {error_message}")
    
    def get_all_trainings(self):
        """Get list of all trainings"""
        return self.index['trainings']
    
    def get_training_details(self, training_id):
        """Get full details of a training"""
        training_dir = self.models_path / training_id
        
        if not training_dir.exists():
            return None
        
        # Load metadata
        metadata_file = training_dir / 'metadata.json'
        if not metadata_file.exists():
            return None
        
        with open(metadata_file, 'r') as f:
            metadata = json.load(f)
        
        # Load training_sessions.json if exists
        sessions_file = training_dir / 'training_sessions.json'
        sessions_info = None
        if sessions_file.exists():
            with open(sessions_file, 'r') as f:
                sessions_info = json.load(f)
        
        # Check available files
        available_files = {
            'model': (training_dir / 'model.tflite').exists(),
            'config': (training_dir / 'config.json').exists(),
            'training_config': (training_dir / 'training_config.json').exists(),
            'sessions': sessions_file.exists(),
            'log': (training_dir / 'training_log.txt').exists()
        }
        
        # Check available charts
        charts_dir = training_dir / 'charts'
        available_charts = []
        if charts_dir.exists():
            for chart_file in charts_dir.glob('*.png'):
                available_charts.append(chart_file.stem)
        
        return {
            'metadata': metadata,
            'sessions_info': sessions_info,
            'available_files': available_files,
            'available_charts': available_charts,
            'training_dir': str(training_dir)
        }
    
    def delete_training(self, training_id):
        """Delete a training and all its files"""
        training_dir = self.models_path / training_id
        
        if training_dir.exists():
            shutil.rmtree(training_dir)
            print(f"[TrainingManager] Deleted training directory: {training_dir}")
        
        # Remove from index
        self.index['trainings'] = [
            t for t in self.index['trainings'] 
            if t['training_id'] != training_id
        ]
        self._save_index()
        
        # Remove from active trainings
        if training_id in self.active_trainings:
            del self.active_trainings[training_id]
        
        print(f"[TrainingManager] Deleted training: {training_id}")
        return True
    
    def get_file_path(self, training_id, file_type):
        """Get path to a specific file"""
        training_dir = self.models_path / training_id
        
        file_paths = {
            'model': training_dir / 'model.tflite',
            'config': training_dir / 'config.json',
            'training_config': training_dir / 'training_config.json',
            'sessions': training_dir / 'training_sessions.json',
            'log': training_dir / 'training_log.txt',
            'metadata': training_dir / 'metadata.json'
        }
        
        return file_paths.get(file_type)
    
    def get_chart_path(self, training_id, chart_name):
        """Get path to a specific chart"""
        training_dir = self.models_path / training_id
        
        # Remove .png if already present to avoid duplication
        if chart_name.endswith('.png'):
            chart_name = chart_name[:-4]
        
        return training_dir / 'charts' / f'{chart_name}.png'


# Test
if __name__ == '__main__':
    manager = TrainingManager()
    
    # Create test training
    training_id = manager.create_training(
        model_type='ECG',
        model_config={
            'name': 'Test ECG Model',
            'version': '1.0',
            'description': 'Test model'
        },
        sessions=['20251121_181250']
    )
    
    print(f"\nCreated training: {training_id}")
    print(f"All trainings: {len(manager.get_all_trainings())}")