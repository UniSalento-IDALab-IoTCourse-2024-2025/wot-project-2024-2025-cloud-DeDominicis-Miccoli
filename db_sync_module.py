"""
Database Synchronization Module
Can be run standalone or imported as thread in IITdata_acq.py
"""

import sqlite3
import requests
import time
import json
from datetime import datetime
from typing import List, Dict, Any
import sys
import threading

# ========== CONFIGURATION ==========
class SyncConfig:
    """Configuration for database sync"""
    def __init__(self, 
                 db_path="users.db",
                 is_local=False,
                 local_api_url="http://10.18.195.83:5001",
                 cloud_api_url="http://localhost:5002",
                 sync_interval=60,
                 sync_token="test123"):
        
        self.LOCAL_DB_PATH = db_path
        self.IS_LOCAL = is_local
        self.LOCAL_API_URL = local_api_url
        self.CLOUD_API_URL = cloud_api_url
        self.SYNC_INTERVAL = sync_interval
        self.SYNC_TOKEN = sync_token

# ========== DATABASE FUNCTIONS ==========
def get_all_users(db_path: str) -> List[Dict[str, Any]]:
    """Get all users from local database"""
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM users")
        users = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        return users
    except Exception as e:
        print(f"[Sync] Error reading database: {e}")
        return []

def upsert_user(db_path: str, user: Dict[str, Any]) -> None:
    """Insert or update user in local database"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if user exists
        cursor.execute("SELECT id FROM users WHERE id = ?", (user['id'],))
        exists = cursor.fetchone() is not None
        
        if exists:
            # Update existing user
            cursor.execute("""
                UPDATE users 
                SET username=?, password_hash=?, nome=?, cognome=?, ruolo=?, 
                    created_at=?, last_login=?, updated_at=?
                WHERE id=?
            """, (
                user['username'], user['password_hash'], user['nome'], user['cognome'],
                user['ruolo'], user['created_at'], user['last_login'], user['updated_at'],
                user['id']
            ))
            print(f"[Sync]    Updated user: {user['username']} (ID: {user['id']})")
        else:
            # Insert new user
            cursor.execute("""
                INSERT INTO users (id, username, password_hash, nome, cognome, ruolo, created_at, last_login, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user['id'], user['username'], user['password_hash'], user['nome'],
                user['cognome'], user['ruolo'], user['created_at'], user['last_login'],
                user['updated_at']
            ))
            print(f"[Sync]    Inserted new user: {user['username']} (ID: {user['id']})")
        
        conn.commit()
    except Exception as e:
        print(f"[Sync]    Error upserting user {user.get('username')}: {e}")
    finally:
        conn.close()

# ========== API FUNCTIONS ==========
def get_remote_users(api_url: str, token: str) -> List[Dict[str, Any]]:
    """Get all users from remote API"""
    try:
        response = requests.get(
            f"{api_url}/api/users/sync",
            headers={"X-Sync-Token": token},
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        return data.get('users', [])
    except requests.exceptions.RequestException as e:
        print(f"[Sync]    Error fetching remote users: {e}")
        return []

def push_users_to_remote(api_url: str, token: str, users: List[Dict[str, Any]]) -> bool:
    """Push local users to remote API"""
    try:
        response = requests.post(
            f"{api_url}/api/users/sync",
            headers={
                "X-Sync-Token": token,
                "Content-Type": "application/json"
            },
            json={"users": users},
            timeout=10
        )
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        print(f"[Sync]   ✗ Error pushing users to remote: {e}")
        return False

# ========== SYNC LOGIC ==========
def compare_users(local: Dict, remote: Dict) -> str:
    """
    Compare two user records
    Returns: 'local_newer', 'remote_newer', 'same', or 'conflict'
    """
    local_ts = local.get('updated_at')
    remote_ts = remote.get('updated_at')
    
    if not local_ts or not remote_ts:
        return 'conflict'  # Missing timestamp
    
    # Parse timestamps
    try:
        local_dt = datetime.fromisoformat(local_ts.replace('Z', '+00:00'))
        remote_dt = datetime.fromisoformat(remote_ts.replace('Z', '+00:00'))
    except:
        return 'conflict'  # Invalid timestamp format
    
    # Compare with 1 second tolerance
    diff = abs((local_dt - remote_dt).total_seconds())
    
    if diff < 1:
        return 'same'
    elif local_dt > remote_dt:
        return 'local_newer'
    else:
        return 'remote_newer'

def sync_databases_once(config: SyncConfig, verbose=True) -> Dict[str, Any]:
    """Single sync run - returns stats"""
    if verbose:
        print(f"[Sync] [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting sync...")
    
    # Determine remote URL
    remote_url = config.CLOUD_API_URL if config.IS_LOCAL else config.LOCAL_API_URL
    instance_name = "LOCAL (Raspberry)" if config.IS_LOCAL else "CLOUD (AWS)"
    remote_name = "CLOUD" if config.IS_LOCAL else "LOCAL"
    
    if verbose:
        print(f"[Sync]   Instance: {instance_name}")
        print(f"[Sync]   Remote: {remote_name} ({remote_url})")
    
    # Get local users
    local_users = get_all_users(config.LOCAL_DB_PATH)
    if verbose:
        print(f"[Sync]   ✓ Found {len(local_users)} local users")
    
    # Get remote users
    remote_users = get_remote_users(remote_url, config.SYNC_TOKEN)
    if not remote_users:
        if verbose:
            print(f"[Sync]   ✗ Could not fetch remote users - skipping sync")
        return {'success': False, 'error': 'Could not fetch remote users'}
    
    if verbose:
        print(f"[Sync]   ✓ Found {len(remote_users)} remote users")
    
    # Create lookup dictionaries
    local_by_id = {u['id']: u for u in local_users}
    remote_by_id = {u['id']: u for u in remote_users}
    
    # Track changes
    to_update_local = []
    to_push_remote = []
    conflicts = []
    
    # Compare users
    all_ids = set(local_by_id.keys()) | set(remote_by_id.keys())
    
    for user_id in all_ids:
        local_user = local_by_id.get(user_id)
        remote_user = remote_by_id.get(user_id)
        
        if local_user and not remote_user:
            to_push_remote.append(local_user)
        elif remote_user and not local_user:
            to_update_local.append(remote_user)
        else:
            result = compare_users(local_user, remote_user)
            if result == 'local_newer':
                to_push_remote.append(local_user)
            elif result == 'remote_newer':
                to_update_local.append(remote_user)
            elif result == 'conflict':
                conflicts.append({
                    'id': user_id,
                    'username': local_user['username'],
                    'local_updated': local_user.get('updated_at'),
                    'remote_updated': remote_user.get('updated_at')
                })
    
    # Apply changes
    if to_update_local:
        if verbose:
            print(f"[Sync]   Updating {len(to_update_local)} users locally:")
        for user in to_update_local:
            upsert_user(config.LOCAL_DB_PATH, user)
    
    if to_push_remote:
        if verbose:
            print(f"[Sync]   Pushing {len(to_push_remote)} users to remote:")
        success = push_users_to_remote(remote_url, config.SYNC_TOKEN, to_push_remote)
        if success and verbose:
            print(f"[Sync]   Successfully pushed {len(to_push_remote)} users")
    
    if conflicts and verbose:
        print(f"[Sync]    WARNING: {len(conflicts)} CONFLICTS DETECTED:")
        for conflict in conflicts:
            print(f"[Sync]     - User {conflict['id']} ({conflict['username']})")
    
    if verbose:
        print(f"[Sync]    Sync complete: pulled {len(to_update_local)}, pushed {len(to_push_remote)}, {len(conflicts)} conflicts")
    
    return {
        'success': True,
        'pulled': len(to_update_local),
        'pushed': len(to_push_remote),
        'conflicts': len(conflicts)
    }

# ========== CONTINUOUS SYNC ==========
class DatabaseSyncService:
    """Service that runs sync in background thread"""
    
    def __init__(self, config: SyncConfig):
        self.config = config
        self.running = False
        self.thread = None
    
    def start(self):
        """Start sync service in background thread"""
        if self.running:
            print("[Sync] Service already running")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._sync_loop, daemon=True)
        self.thread.start()
        print(f"[Sync] Service started (interval: {self.config.SYNC_INTERVAL}s)")
    
    def stop(self):
        """Stop sync service"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        print("[Sync] Service stopped")
    
    def _sync_loop(self):
        """Main sync loop"""
        while self.running:
            try:
                sync_databases_once(self.config, verbose=True)
            except Exception as e:
                print(f"[Sync] ✗ Sync error: {e}")
            
            # Sleep in small intervals to allow quick shutdown
            for _ in range(self.config.SYNC_INTERVAL):
                if not self.running:
                    break
                time.sleep(1)

# ========== STANDALONE MODE ==========
def main():
    """Main function for standalone execution"""
    config = SyncConfig(
        is_local=True,  # CHANGE THIS: False for cloud
        local_api_url="http://10.18.195.83:5001",
        cloud_api_url="http://localhost:5002",
        sync_token="CHANGE_ME_IN_PRODUCTION"
    )
    
    print("=" * 60)
    print("  DATABASE SYNCHRONIZATION SERVICE")
    print("=" * 60)
    print(f"  Instance: {'LOCAL (Raspberry)' if config.IS_LOCAL else 'CLOUD (AWS)'}")
    print(f"  Sync interval: {config.SYNC_INTERVAL} seconds")
    print(f"  Database: {config.LOCAL_DB_PATH}")
    print("=" * 60)
    
    service = DatabaseSyncService(config)
    service.start()
    
    try:
        # Keep running
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[Sync] → Shutting down...")
        service.stop()
        print("[Sync] → Service stopped by user")

if __name__ == "__main__":
    main()