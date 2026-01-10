"""
Fix All Metadata Script
Recalculates total_samples and end_time for all existing sessions
"""
import json
from pathlib import Path
from datetime import datetime, timedelta

def fix_all_metadata(base_dir="./vat/iit_data/data_storage"):
    """
    FIX ALL EXISTING METADATA FILES
    Recalculates total_samples and end_time for all sessions
    """
    base_path = Path(base_dir)
    
    print("=" * 70)
    print("FIXING ALL METADATA FILES")
    print("=" * 70)
    
    fixed_count = 0
    error_count = 0
    
    # Scandisci tutte le date
    for date_folder in sorted(base_path.iterdir()):
        if not date_folder.is_dir() or date_folder.name.startswith('.'):
            continue
        
        print(f"\n Scanning date folder: {date_folder.name}")
        
        # Scandisci tutte le sessioni
        for session_dir in sorted(date_folder.iterdir()):
            if not session_dir.is_dir() or session_dir.name.startswith('.'):
                continue
            
            metadata_file = session_dir / "metadata.json"
            if not metadata_file.exists():
                print(f"    No metadata.json in {session_dir.name}")
                continue
            
            try:
                # Leggi metadata corrente
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
                
                session_id = metadata.get('session_id', session_dir.name)
                print(f"\n  🔧 Fixing session: {session_id}")
                
                # CONTA RIGHE EFFETTIVE nei file
                actual_samples = {}
                for signal in ['ECG', 'ADC', 'TEMP']:
                    data_file = session_dir / f"{signal}_data.jsonl"
                    if data_file.exists():
                        with open(data_file, 'r') as f:
                            actual_samples[signal] = sum(1 for _ in f)
                    else:
                        actual_samples[signal] = 0
                
                old_samples = metadata.get('total_samples', {})
                print(f"     Old samples: ECG={old_samples.get('ECG', 0):,} ADC={old_samples.get('ADC', 0):,} TEMP={old_samples.get('TEMP', 0):,}")
                print(f"     New samples: ECG={actual_samples['ECG']:,} ADC={actual_samples['ADC']:,} TEMP={actual_samples['TEMP']:,}")
                
                # RICALCOLA end_time basandosi sui samples
                # USA SOLO ECG/ADC (250 Hz) - IGNORA TEMP (1 Hz)
                duration_ecg = None
                duration_adc = None
                
                # ECG: 250 Hz
                if actual_samples.get('ECG', 0) > 0:
                    duration_ecg = actual_samples['ECG'] / 250.0
                    print(f"     ECG duration: {duration_ecg:.1f} sec ({duration_ecg/60:.1f} min)")
                
                # ADC: 250 Hz
                if actual_samples.get('ADC', 0) > 0:
                    duration_adc = actual_samples['ADC'] / 250.0
                    print(f"     ADC duration: {duration_adc:.1f} sec ({duration_adc/60:.1f} min)")
                
                # TEMP: 1 Hz (SOLO PER INFO, NON USATO PER DURATA)
                if actual_samples.get('TEMP', 0) > 0:
                    duration_temp = actual_samples['TEMP'] / 1.0
                    print(f"     TEMP duration: {duration_temp:.1f} sec ({duration_temp/60:.1f} min) [INFO ONLY]")
                
                # VERIFICA DISCREPANZA ECG vs ADC
                if duration_ecg is not None and duration_adc is not None:
                    diff = abs(duration_ecg - duration_adc)
                    if diff > 1.0:  # Tolleranza 1 secondo
                        print(f"       WARNING: ECG/ADC discrepancy: {diff:.1f} seconds!")
                
                # USA ECG come riferimento (o ADC se ECG manca)
                if duration_ecg is not None:
                    final_duration = duration_ecg
                elif duration_adc is not None:
                    final_duration = duration_adc
                else:
                    print(f"     ❌ ERROR: No ECG or ADC data!")
                    error_count += 1
                    continue
                
                # Calcola end_time corretto
                start_time = datetime.fromisoformat(metadata["start_time"])
                end_time = start_time + timedelta(seconds=final_duration)
                
                old_end = metadata.get('end_time', 'N/A')
                
                # Calcola durata OLD (se esiste)
                if old_end != 'N/A':
                    try:
                        old_end_dt = datetime.fromisoformat(old_end)
                        old_duration = (old_end_dt - start_time).total_seconds()
                        print(f"     Old end_time: {old_end} (duration: {old_duration:.1f} sec / {old_duration/60:.1f} min)")
                    except:
                        print(f"     Old end_time: {old_end} (invalid)")
                else:
                    print(f"     Old end_time: N/A")
                
                print(f"     New end_time: {end_time.isoformat()} (duration: {final_duration:.1f} sec / {final_duration/60:.1f} min)")
                
                # Aggiorna metadata
                metadata["total_samples"] = actual_samples
                metadata["end_time"] = end_time.isoformat()
                metadata["status"] = "completed"
                
                # Scrivi metadata fixato
                with open(metadata_file, 'w') as f:
                    json.dump(metadata, f, indent=2)
                
                print(f"     ✅ FIXED!")
                fixed_count += 1
                
            except Exception as e:
                print(f"     ❌ ERROR: {e}")
                error_count += 1
    
    print("\n" + "=" * 70)
    print(f"✅ Fixed: {fixed_count} sessions")
    print(f"❌ Errors: {error_count} sessions")
    print("=" * 70)


if __name__ == "__main__":
    import sys
    
    # Permetti di specificare directory custom
    base_dir = sys.argv[1] if len(sys.argv) > 1 else "./var/iit_data/data_storage"
    
    print(f"\nBase directory: {base_dir}\n")
    fix_all_metadata(base_dir)