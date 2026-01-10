"""
ECG Anomaly Detection Model Trainer
Adapted to use JSON data from dashboard sessions instead of CSV
"""

import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import numpy as np
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers
from tensorflow.keras.models import Model
from sklearn.model_selection import train_test_split
import json
import os
from pathlib import Path

# Custom JSON encoder for numpy types
class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer, np.int32, np.int64)):
            return int(obj)
        elif isinstance(obj, (np.floating, np.float32, np.float64)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)

# Import custom modules
from data_loader import SessionDataLoader
from training_manager import TrainingManager

class ECGModelTrainer:
    """
    Trains ECG anomaly detection model using autoencoder
    """
    
    def __init__(self, training_id, training_manager):
        self.training_id = training_id
        self.training_manager = training_manager
        self.training_dir = Path(training_manager.models_path) / training_id
        self.charts_dir = self.training_dir / 'charts'
        
        # Model parameters
        self.SEQUENCE_LENGTH = 1000  # 4 seconds at 250 Hz
        self.LATENT_DIM = 32
        self.EPOCHS = 100
        self.BATCH_SIZE = 64
        self.OVERLAP_RATIO = 0.75
        self.SIGMA_THRESHOLD = 3.0
        
        self.autoencoder = None
        self.threshold = None
    
    def segment_signal(self, signal):
        """Segment long signal into fixed-length windows with overlap"""
        segments = []
        step_size = int(self.SEQUENCE_LENGTH * (1 - self.OVERLAP_RATIO))
        
        for start in range(0, len(signal) - self.SEQUENCE_LENGTH + 1, step_size):
            segment = signal[start:start + self.SEQUENCE_LENGTH]
            segments.append(segment)
        
        return segments
    
    def normalize_signal(self, signal):
        """Normalize signal to [0, 1] range"""
        signal = np.asarray(signal, dtype=np.float32)
        min_val = np.min(signal)
        max_val = np.max(signal)
        
        if max_val - min_val == 0:
            return signal * 0
        
        return (signal - min_val) / (max_val - min_val)
    
    def prepare_data(self, raw_signal):
        """Segment and normalize data"""
        print(f"\n[ECGTrainer] Preparing data...")
        print(f"  Raw signal length: {len(raw_signal):,} samples")
        
        # Segment
        segments = self.segment_signal(raw_signal)
        print(f"  Segments created: {len(segments):,}")
        
        # Convert to array and normalize
        data = np.array(segments, dtype=np.float32)
        for i in range(len(data)):
            data[i] = self.normalize_signal(data[i])
        
        print(f"  Final data shape: {data.shape}")
        print(f"  Value range: [{np.min(data):.4f}, {np.max(data):.4f}]")
        
        return data
    
    def build_model(self):
        """Build autoencoder model"""
        print(f"\n[ECGTrainer] Building model...")
        
        # Encoder
        encoder = keras.Sequential([
            layers.Input(shape=(self.SEQUENCE_LENGTH,)),
            layers.Dense(128, activation="relu"),
            layers.Dropout(0.2),
            layers.Dense(64, activation="relu"),
            layers.Dropout(0.2),
            layers.Dense(self.LATENT_DIM, activation="relu", name="bottleneck")
        ], name="encoder")
        
        # Decoder
        decoder = keras.Sequential([
            layers.Input(shape=(self.LATENT_DIM,)),
            layers.Dense(64, activation="relu"),
            layers.Dropout(0.2),
            layers.Dense(128, activation="relu"),
            layers.Dropout(0.2),
            layers.Dense(self.SEQUENCE_LENGTH, activation="sigmoid")
        ], name="decoder")
        
        # Full autoencoder
        class Autoencoder(Model):
            def __init__(self, enc, dec):
                super().__init__()
                self.encoder = enc
                self.decoder = dec
            
            def call(self, x):
                encoded = self.encoder(x)
                decoded = self.decoder(encoded)
                return decoded
        
        self.autoencoder = Autoencoder(encoder, decoder)
        self.autoencoder.build(input_shape=(None, self.SEQUENCE_LENGTH))
        
        self.autoencoder.compile(
            optimizer=keras.optimizers.Adam(learning_rate=0.001),
            loss='mse',
            metrics=['mae']
        )
        
        print(f"  Total parameters: {self.autoencoder.count_params():,}")
        
        return self.autoencoder
    
    def train(self, train_data, val_data):
        """Train the model with progress tracking"""
        print(f"\n[ECGTrainer] Starting training...")
        print(f"  Training samples: {len(train_data):,}")
        print(f"  Validation samples: {len(val_data):,}")
        print(f"  Epochs: {self.EPOCHS}")
        
        # Custom callback for progress tracking
        class ProgressCallback(keras.callbacks.Callback):
            def __init__(self, trainer, training_manager, training_id, total_epochs):
                super().__init__()
                self.trainer = trainer
                self.training_manager = training_manager
                self.training_id = training_id
                self.total_epochs = total_epochs
            
            def on_epoch_end(self, epoch, logs=None):
                loss = logs.get('loss', 0)
                val_loss = logs.get('val_loss', 0)
                
                self.training_manager.update_progress(
                    self.training_id,
                    epoch + 1,
                    self.total_epochs,
                    loss,
                    val_loss,
                    f"Epoch {epoch+1}/{self.total_epochs}"
                )
        
        callbacks = [
            ProgressCallback(self, self.training_manager, self.training_id, self.EPOCHS),
            keras.callbacks.EarlyStopping(
                monitor='val_loss',
                patience=15,
                restore_best_weights=True
            ),
            keras.callbacks.ReduceLROnPlateau(
                monitor='val_loss',
                factor=0.5,
                patience=7,
                min_lr=1e-6,
                verbose=0
            )
        ]
        
        history = self.autoencoder.fit(
            train_data, train_data,
            epochs=self.EPOCHS,
            batch_size=self.BATCH_SIZE,
            validation_data=(val_data, val_data),
            callbacks=callbacks,
            verbose=2
        )
        
        return history
    
    def calculate_threshold(self, train_data):
        """Calculate anomaly detection threshold"""
        print(f"\n[ECGTrainer] Calculating threshold...")
        
        reconstructions = self.autoencoder.predict(train_data, batch_size=256, verbose=0)
        train_loss = tf.keras.losses.mse(train_data, reconstructions).numpy()
        
        mean_loss = np.mean(train_loss)
        std_loss = np.std(train_loss)
        threshold = mean_loss + self.SIGMA_THRESHOLD * std_loss
        
        print(f"  Mean loss: {mean_loss:.6f}")
        print(f"  Std loss: {std_loss:.6f}")
        print(f"  Threshold ({self.SIGMA_THRESHOLD}σ): {threshold:.6f}")
        
        self.threshold = threshold
        
        return threshold, {
            'mean': float(mean_loss),
            'std': float(std_loss),
            'min': float(np.min(train_loss)),
            'max': float(np.max(train_loss)),
            'median': float(np.median(train_loss)),
            'p95': float(np.percentile(train_loss, 95)),
            'p99': float(np.percentile(train_loss, 99)),
            'threshold': float(threshold),
            'sigma': self.SIGMA_THRESHOLD
        }
    
    def save_model(self, model_config):
        """Save model in TFLite format"""
        print(f"\n[ECGTrainer] Saving model...")
        
        # Convert to TFLite quantized (best for RPi)
        converter = tf.lite.TFLiteConverter.from_keras_model(self.autoencoder)
        converter.optimizations = [tf.lite.Optimize.DEFAULT]
        quantized_model = converter.convert()
        
        model_path = self.training_dir / 'model.tflite'
        with open(model_path, 'wb') as f:
            f.write(quantized_model)
        
        model_size = len(quantized_model) / 1024
        print(f"  Model saved: {model_path}")
        print(f"  Size: {model_size:.1f} KB")
        
        # Save config.json (user-provided metadata)
        config_path = self.training_dir / 'config.json'
        with open(config_path, 'w') as f:
            json.dump(model_config, f, indent=2, cls=NumpyEncoder)
        
        print(f"  Config saved: {config_path}")
        
        return model_path, config_path
    
    def save_training_config(self, threshold_stats, sessions_info):
        """Save technical training configuration"""
        config = {
            'model_type': 'ECG',
            'architecture': {
                'sequence_length': self.SEQUENCE_LENGTH,
                'latent_dim': self.LATENT_DIM,
                'total_parameters': int(self.autoencoder.count_params())
            },
            'threshold': self.threshold,
            'threshold_stats': threshold_stats,
            'training_params': {
                'epochs': self.EPOCHS,
                'batch_size': self.BATCH_SIZE,
                'overlap_ratio': self.OVERLAP_RATIO,
                'sigma_threshold': self.SIGMA_THRESHOLD
            },
            'data_info': sessions_info
        }
        
        config_path = self.training_dir / 'training_config.json'
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2, cls=NumpyEncoder)
        
        print(f"  Training config saved: {config_path}")
        
        return config_path
    
    def plot_examples(self, data, n_examples=6):
        """Plot example signals"""
        fig, axes = plt.subplots(2, 3, figsize=(18, 8))
        axes = axes.flatten()
        
        for i in range(n_examples):
            idx = np.random.randint(0, len(data))
            axes[i].plot(data[idx], linewidth=1.5, color='blue')
            axes[i].set_title(f"ECG Sample {idx}", fontsize=11)
            axes[i].set_xlabel("Time (samples)", fontsize=9)
            axes[i].set_ylabel("Normalized Amplitude", fontsize=9)
            axes[i].grid(True, alpha=0.3)
        
        plt.tight_layout()
        chart_path = self.charts_dir / 'examples.png'
        plt.savefig(chart_path, dpi=150, bbox_inches='tight')
        plt.close()
        
        print(f"  Saved: examples.png")
    
    def plot_training_history(self, history):
        """Plot training curves"""
        fig, axes = plt.subplots(1, 2, figsize=(15, 5))
        
        axes[0].plot(history.history['loss'], label='Training Loss', linewidth=2)
        axes[0].plot(history.history['val_loss'], label='Validation Loss', linewidth=2)
        axes[0].set_xlabel('Epoch', fontsize=12)
        axes[0].set_ylabel('Loss (MSE)', fontsize=12)
        axes[0].set_title('Training Loss', fontsize=14)
        axes[0].legend(fontsize=11)
        axes[0].grid(True, alpha=0.3)
        
        axes[1].plot(history.history['mae'], label='Training MAE', linewidth=2)
        axes[1].plot(history.history['val_mae'], label='Validation MAE', linewidth=2)
        axes[1].set_xlabel('Epoch', fontsize=12)
        axes[1].set_ylabel('MAE', fontsize=12)
        axes[1].set_title('Mean Absolute Error', fontsize=14)
        axes[1].legend(fontsize=11)
        axes[1].grid(True, alpha=0.3)
        
        plt.tight_layout()
        chart_path = self.charts_dir / 'training_history.png'
        plt.savefig(chart_path, dpi=150, bbox_inches='tight')
        plt.close()
        
        print(f"  Saved: training_history.png")
    
    def plot_reconstruction(self, data, n_examples=4):
        """Plot reconstruction examples"""
        indices = np.random.choice(len(data), n_examples, replace=False)
        reconstructions = self.autoencoder.predict(data[indices], verbose=0)
        
        fig, axes = plt.subplots(n_examples, 1, figsize=(15, 3*n_examples))
        if n_examples == 1:
            axes = [axes]
        
        for i, idx in enumerate(indices):
            mse = np.mean((data[idx] - reconstructions[i])**2)
            
            axes[i].plot(data[idx], 'b', label='Original ECG', linewidth=1.5)
            axes[i].plot(reconstructions[i], 'r', label='Reconstructed', linewidth=1.5, alpha=0.8)
            axes[i].fill_between(
                range(self.SEQUENCE_LENGTH),
                data[idx],
                reconstructions[i],
                color='lightcoral',
                alpha=0.3,
                label='Error'
            )
            axes[i].set_title(f'ECG Sample - MSE: {mse:.6f}', fontsize=12)
            axes[i].set_xlabel('Time (samples)', fontsize=10)
            axes[i].set_ylabel('Normalized Amplitude', fontsize=10)
            axes[i].legend(fontsize=10)
            axes[i].grid(True, alpha=0.3)
        
        plt.tight_layout()
        chart_path = self.charts_dir / 'reconstruction.png'
        plt.savefig(chart_path, dpi=150, bbox_inches='tight')
        plt.close()
        
        print(f"  Saved: reconstruction.png")
    
    def plot_threshold_distribution(self, train_data):
        """Plot threshold distribution"""
        reconstructions = self.autoencoder.predict(train_data, batch_size=256, verbose=0)
        train_loss = tf.keras.losses.mse(train_data, reconstructions).numpy()
        
        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        
        # Histogram
        axes[0].hist(train_loss, bins=100, color='lightblue', edgecolor='black', alpha=0.7)
        axes[0].axvline(self.threshold, color='r', linestyle='--', linewidth=2, 
                       label=f'Threshold ({self.SIGMA_THRESHOLD}σ)')
        axes[0].axvline(np.mean(train_loss), color='g', linestyle='--', linewidth=2, label='Mean')
        axes[0].set_xlabel('Reconstruction Error (MSE)', fontsize=12)
        axes[0].set_ylabel('Frequency', fontsize=12)
        axes[0].set_title('Distribution of Reconstruction Errors', fontsize=14)
        axes[0].legend(fontsize=11)
        axes[0].grid(True, alpha=0.3)
        
        # Cumulative
        axes[1].hist(train_loss, bins=100, color='lightblue', edgecolor='black', alpha=0.7,
                    cumulative=True, density=True)
        axes[1].axhline(0.997, color='r', linestyle='--', linewidth=2, label='99.7% (3σ)')
        axes[1].axvline(self.threshold, color='r', linestyle='--', linewidth=2, alpha=0.5)
        axes[1].set_xlabel('Reconstruction Error (MSE)', fontsize=12)
        axes[1].set_ylabel('Cumulative Probability', fontsize=12)
        axes[1].set_title('Cumulative Distribution', fontsize=14)
        axes[1].legend(fontsize=11)
        axes[1].grid(True, alpha=0.3)
        
        plt.tight_layout()
        chart_path = self.charts_dir / 'threshold_distribution.png'
        plt.savefig(chart_path, dpi=150, bbox_inches='tight')
        plt.close()
        
        print(f"  Saved: threshold_distribution.png")


def train_ecg_model(training_id, session_ids, model_config, training_manager):
    """
    Main training function for ECG model
    
    Args:
        training_id: Unique training ID
        session_ids: List of session IDs to use for training
        model_config: Dict with name, version, description
        training_manager: TrainingManager instance
    
    Returns:
        bool: Success status
    """
    try:
        print(f"\n{'='*60}")
        print(f"STARTING ECG MODEL TRAINING")
        print(f"Training ID: {training_id}")
        print(f"{'='*60}\n")
        
        trainer = ECGModelTrainer(training_id, training_manager)
        
        # STEP 1: Load data
        print("STEP 1: Loading ECG data from sessions...")
        loader = SessionDataLoader()
        raw_signal, sessions_metadata = loader.load_ecg_data(session_ids)
        
        if len(raw_signal) == 0:
            raise ValueError("No data loaded from sessions")
        
        # Save sessions info
        sessions_info = loader.save_sessions_info(
            sessions_metadata, 
            trainer.training_dir / 'training_sessions.json'
        )
        
        # STEP 2: Prepare data
        data = trainer.prepare_data(raw_signal)
        
        # STEP 3: Plot examples
        print("\nSTEP 3: Plotting example signals...")
        trainer.plot_examples(data, n_examples=6)
        
        # STEP 4: Split data
        print("\nSTEP 4: Splitting data...")
        train_data, temp_data = train_test_split(data, test_size=0.3, random_state=42, shuffle=True)
        val_data, test_data = train_test_split(temp_data, test_size=0.5, random_state=42)
        
        print(f"  Training:   {len(train_data):,} samples")
        print(f"  Validation: {len(val_data):,} samples")
        print(f"  Test:       {len(test_data):,} samples")
        
        # STEP 5: Build model
        trainer.build_model()
        
        # STEP 6: Train
        print("\nSTEP 6: Training model...")
        history = trainer.train(train_data, val_data)
        
        # STEP 7: Plot training history
        print("\nSTEP 7: Plotting training history...")
        trainer.plot_training_history(history)
        
        # STEP 8: Calculate threshold
        print("\nSTEP 8: Calculating threshold...")
        threshold, threshold_stats = trainer.calculate_threshold(train_data)
        
        # STEP 9: Plot reconstruction
        print("\nSTEP 9: Plotting reconstructions...")
        trainer.plot_reconstruction(test_data, n_examples=4)
        
        # STEP 10: Plot threshold distribution
        print("\nSTEP 10: Plotting threshold distribution...")
        trainer.plot_threshold_distribution(train_data)
        
        # STEP 11: Save model
        print("\nSTEP 11: Saving model...")
        trainer.save_model(model_config)
        trainer.save_training_config(threshold_stats, sessions_info)
        
        # STEP 12: Mark as completed
        final_epoch = len(history.history['loss'])
        final_loss = history.history['loss'][-1]
        final_val_loss = history.history['val_loss'][-1]
        
        training_manager.complete_training(
            training_id, final_epoch, final_loss, final_val_loss, threshold
        )
        
        print(f"\n{'='*60}")
        print(f"✅ ECG MODEL TRAINING COMPLETED!")
        print(f"{'='*60}\n")
        
        # STEP 13: Auto-deploy to Raspberry Pi (if configured)
        try:
            model_folder = trainer.training_dir  # Correct attribute name
            package_and_upload_to_raspberry(model_folder, model_type='ecg')
        except Exception as e:
            print(f"\n⚠️  Auto-deploy failed (training still successful): {e}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Training failed: {e}")
        import traceback
        traceback.print_exc()
        training_manager.fail_training(training_id, str(e))
        return False

# ============================================================================
# AUTO-DEPLOY TO RASPBERRY PI
# ============================================================================

def package_and_upload_to_raspberry(model_folder, model_type='ecg'):
    """
    Package trained model and automatically upload to Raspberry Pi
    
    Args:
        model_folder: Path to model folder (e.g., models/ecg/ecg_model_v1_20250116)
        model_type: 'ecg' or 'piezo'
    
    Returns:
        bool: True if upload successful, False otherwise
    """
    import zipfile
    import requests
    from pathlib import Path
    
    print(f"\n{'='*60}")
    print(f"📦 PACKAGING MODEL FOR DEPLOYMENT")
    print(f"{'='*60}")
    
    # Load Raspberry Pi configuration
    config_file = Path('raspberry_config.json')
    if not config_file.exists():
        print(f"⚠️  raspberry_config.json not found!")
        print(f"💡 Create raspberry_config.json with:")
        print(f'''{{
  "raspberry_ip": "10.18.195.83",
  "port": 5001,
  "api_key": "your-secret-key",
  "auto_upload": true
}}''')
        return False
    
    try:
        import json
        with open(config_file, 'r') as f:
            config = json.load(f)
    except Exception as e:
        print(f"❌ Error reading config: {e}")
        return False
    
    # Check if auto_upload is enabled
    if not config.get('auto_upload', False):
        print(f"ℹ️  Auto-upload disabled in config")
        return False
    
    raspberry_ip = config.get('raspberry_ip')
    print(raspberry_ip)
    port = config.get('port', 5001)
    api_key = config.get('api_key')
    
    if not raspberry_ip or not api_key:
        print(f"❌ Missing raspberry_ip or api_key in config")
        return False
    
    # Get model folder path
    model_path = Path(model_folder)
    if not model_path.exists():
        print(f"❌ Model folder not found: {model_path}")
        return False
    
    # Files to package - map source file to target name in ZIP
    files_to_package = {
        'model.tflite': 'model.tflite',
        'config.json': 'config.json',
        'charts/examples.png': 'examples.png',
        'charts/training_history.png': 'training.png',  # ← Rinomina
        'charts/reconstruction.png': 'reconstruction.png',
        'charts/threshold_distribution.png': 'threshold.png'  # ← Rinomina
    }
    
    # Create ZIP package
    zip_filename = f"{model_path.name}_package.zip"
    zip_path = model_path.parent / zip_filename
    
    print(f"\n📦 Creating package: {zip_filename}")
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for source_file, target_name in files_to_package.items():
            file_path = model_path / source_file
            if file_path.exists():
                zipf.write(file_path, target_name)
                file_size = file_path.stat().st_size / 1024
                print(f"  ✓ {target_name} ({file_size:.1f} KB)")
            else:
                print(f"  ⚠️  {source_file} not found (skipping)")
    
    zip_size = zip_path.stat().st_size / 1024
    print(f"\n✓ Package created: {zip_size:.1f} KB")
    
    # Upload to Raspberry Pi
    print(f"\n📤 Uploading to Raspberry Pi ({raspberry_ip}:{port})...")
    
    url = f"http://{raspberry_ip}:{port}/api/models/upload"
    
    try:
        # Generate proper model name: ecg_model_v1_20251216
        from datetime import datetime
        date_str = datetime.now().strftime("%Y%m%d")
        proper_model_name = f"{model_type}_model_v1_{date_str}"
        
        with open(zip_path, 'rb') as f:
            files = {'model_package': (zip_filename, f, 'application/zip')}
            data = {
                'model_type': model_type,
                'model_name': proper_model_name  # Use proper name, not training folder name
            }
            headers = {'X-API-Key': api_key}
            
            response = requests.post(
                url, 
                files=files, 
                data=data, 
                headers=headers,
                timeout=120  # 2 minutes timeout
            )
        
        if response.status_code == 200:
            result = response.json()
            print(f"\n{'='*60}")
            print(f"✅ MODEL DEPLOYED TO RASPBERRY PI!")
            print(f"{'='*60}")
            print(f"📍 Location: {result.get('model_path', 'N/A')}")
            print(f"🎯 Model ready for use in dashboard")
            return True
        else:
            print(f"\n❌ Upload failed!")
            print(f"Status code: {response.status_code}")
            print(f"Response: {response.text}")
            return False
            
    except requests.exceptions.ConnectionError:
        print(f"\n❌ Cannot connect to Raspberry Pi at {raspberry_ip}:{port}")
        print(f"💡 Make sure:")
        print(f"  1. Raspberry Pi is powered on")
        print(f"  2. Dashboard server is running")
        print(f"  3. IP address is correct")
        return False
        
    except Exception as e:
        print(f"\n❌ Upload error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        # Clean up ZIP file
        if zip_path.exists():
            zip_path.unlink()
            print(f"\n🗑️  Cleaned up temporary package")