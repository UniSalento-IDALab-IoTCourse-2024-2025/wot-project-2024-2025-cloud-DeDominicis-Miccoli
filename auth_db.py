"""
Sistema di Autenticazione e Database Utenti
SQLite + bcrypt per password hashing
Con supporto sincronizzazione (updated_at)
"""

import sqlite3
import bcrypt
from datetime import datetime, timedelta
import secrets
import json
from pathlib import Path

class AuthDB:
    def __init__(self, db_path='users.db'):
        self.db_path = db_path
        self.init_database()
        self.fix_null_updated_at() 
    
    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def init_database(self):
        """Inizializza database con tabelle utenti e sessioni"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Tabella utenti
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                nome TEXT NOT NULL,
                cognome TEXT NOT NULL,
                ruolo TEXT NOT NULL CHECK(ruolo IN ('paziente', 'medico', 'admin')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP
            )
        ''')
        
        # Tabella sessioni
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                session_token TEXT UNIQUE NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        ''')
        
        # Crea admin di default se non esiste
        cursor.execute("SELECT COUNT(*) FROM users WHERE ruolo = 'admin'")
        if cursor.fetchone()[0] == 0:
            admin_password = self.hash_password('admin123')
            cursor.execute('''
                INSERT INTO users (username, password_hash, nome, cognome, ruolo)
                VALUES (?, ?, ?, ?, ?)
            ''', ('admin', admin_password, 'Admin', 'System', 'admin'))
            print("[AuthDB] ✓ Admin di default creato (username: admin, password: admin123)")
        
        conn.commit()
        conn.close()
    
    def fix_null_updated_at(self):
        """Fix per utenti con updated_at NULL (creati prima della migrazione)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            # Controlla se colonna updated_at esiste
            cursor.execute("PRAGMA table_info(users)")
            columns = [col[1] for col in cursor.fetchall()]
            
            if 'updated_at' not in columns:
                print("[AuthDB] ⚠ Colonna updated_at non presente - esegui migration!")
                return
            
            # Fix utenti con updated_at NULL
            cursor.execute('''
                UPDATE users 
                SET updated_at = COALESCE(created_at, datetime('now'))
                WHERE updated_at IS NULL
            ''')
            
            fixed = cursor.rowcount
            if fixed > 0:
                conn.commit()
                print(f"[AuthDB] ✓ Fixati {fixed} utenti con updated_at NULL")
        
        except sqlite3.OperationalError as e:
            print(f"[AuthDB] ⚠ Errore fix updated_at: {e}")
        finally:
            conn.close()
    
    def hash_password(self, password):
        """Hash password con bcrypt"""
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    def verify_password(self, password, password_hash):
        """Verifica password"""
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
    
    def register_user(self, username, password, nome, cognome, ruolo):
        """Registra nuovo utente"""
        if ruolo not in ['paziente', 'medico', 'admin']:
            return {'success': False, 'error': 'Ruolo non valido'}
        
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            # Verifica username univoco
            cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
            if cursor.fetchone():
                return {'success': False, 'error': 'Username già esistente'}
            
            # Inserisci utente con updated_at
            password_hash = self.hash_password(password)
            cursor.execute('''
                INSERT INTO users (username, password_hash, nome, cognome, ruolo, updated_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
            ''', (username, password_hash, nome, cognome, ruolo))
            
            conn.commit()
            user_id = cursor.lastrowid
            
            return {
                'success': True,
                'user_id': user_id,
                'message': 'Utente registrato con successo'
            }
        
        except sqlite3.IntegrityError as e:
            return {'success': False, 'error': f'Errore database: {str(e)}'}
        finally:
            conn.close()
    
    def login(self, username, password):
        """Login utente e crea sessione"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            # Trova utente
            cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
            user = cursor.fetchone()
            
            if not user:
                return {'success': False, 'error': 'Username o password errati'}
            
            # Verifica password
            if not self.verify_password(password, user['password_hash']):
                return {'success': False, 'error': 'Username o password errati'}
            
            # Crea sessione (40 minuti)
            session_token = secrets.token_urlsafe(32)
            expires_at = datetime.now() + timedelta(minutes=40)
            
            cursor.execute('''
                INSERT INTO sessions (user_id, session_token, expires_at)
                VALUES (?, ?, ?)
            ''', (user['id'], session_token, expires_at))
            
            # Aggiorna last_login (NON updated_at - solo last_login cambia)
            cursor.execute('''
                UPDATE users SET last_login = datetime('now') WHERE id = ?
            ''', (user['id'],))
            
            conn.commit()
            
            return {
                'success': True,
                'session_token': session_token,
                'user': {
                    'id': user['id'],
                    'username': user['username'],
                    'nome': user['nome'],
                    'cognome': user['cognome'],
                    'ruolo': user['ruolo']
                }
            }
        
        finally:
            conn.close()
    
    def verify_session(self, session_token):
        """Verifica sessione valida"""
        if not session_token:
            return {'success': False, 'error': 'Sessione non presente'}
        
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT s.*, u.id as user_id, u.username, u.nome, u.cognome, u.ruolo
                FROM sessions s
                JOIN users u ON s.user_id = u.id
                WHERE s.session_token = ? AND s.expires_at > datetime('now')
            ''', (session_token,))
            
            session = cursor.fetchone()
            
            if not session:
                return {'success': False, 'error': 'Sessione scaduta o non valida'}
            
            return {
                'success': True,
                'user': {
                    'id': session['user_id'],
                    'username': session['username'],
                    'nome': session['nome'],
                    'cognome': session['cognome'],
                    'ruolo': session['ruolo']
                }
            }
        
        finally:
            conn.close()
    
    def logout(self, session_token):
        """Logout - elimina sessione"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("DELETE FROM sessions WHERE session_token = ?", (session_token,))
            conn.commit()
            return {'success': True, 'message': 'Logout effettuato'}
        finally:
            conn.close()
    
    def cleanup_expired_sessions(self):
        """Rimuove sessioni scadute"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("DELETE FROM sessions WHERE expires_at < datetime('now')")
            deleted = cursor.rowcount
            conn.commit()
            return {'success': True, 'deleted': deleted}
        finally:
            conn.close()
    
    # ========== GESTIONE UTENTI (ADMIN) ==========
    
    def get_all_users(self):
        """Ottieni lista tutti utenti (admin only)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT id, username, nome, cognome, ruolo, created_at, last_login, updated_at
                FROM users
                ORDER BY created_at DESC
            ''')
            
            users = []
            for row in cursor.fetchall():
                users.append({
                    'id': row['id'],
                    'username': row['username'],
                    'nome': row['nome'],
                    'cognome': row['cognome'],
                    'ruolo': row['ruolo'],
                    'created_at': row['created_at'],
                    'last_login': row['last_login'],
                    'updated_at': row['updated_at']
                })
            
            return {'success': True, 'users': users}
        finally:
            conn.close()
    
    def get_user_by_id(self, user_id):
        """Ottieni utente per ID"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT id, username, nome, cognome, ruolo, created_at, last_login, updated_at
                FROM users WHERE id = ?
            ''', (user_id,))
            
            user = cursor.fetchone()
            if not user:
                return {'success': False, 'error': 'Utente non trovato'}
            
            return {
                'success': True,
                'user': {
                    'id': user['id'],
                    'username': user['username'],
                    'nome': user['nome'],
                    'cognome': user['cognome'],
                    'ruolo': user['ruolo'],
                    'created_at': user['created_at'],
                    'last_login': user['last_login'],
                    'updated_at': user['updated_at']
                }
            }
        finally:
            conn.close()
    
    def update_user(self, user_id, nome=None, cognome=None, ruolo=None, new_password=None):
        """Aggiorna utente (admin only)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            updates = []
            params = []
            
            if nome:
                updates.append("nome = ?")
                params.append(nome)
            if cognome:
                updates.append("cognome = ?")
                params.append(cognome)
            if ruolo:
                if ruolo not in ['paziente', 'medico', 'admin']:
                    return {'success': False, 'error': 'Ruolo non valido'}
                updates.append("ruolo = ?")
                params.append(ruolo)
            if new_password:
                updates.append("password_hash = ?")
                params.append(self.hash_password(new_password))
            
            if not updates:
                return {'success': False, 'error': 'Nessun campo da aggiornare'}
            
            # IMPORTANTE: Aggiungi updated_at quando modifichi utente
            updates.append("updated_at = datetime('now')")
            
            params.append(user_id)
            query = f"UPDATE users SET {', '.join(updates)} WHERE id = ?"
            
            cursor.execute(query, params)
            conn.commit()
            
            if cursor.rowcount == 0:
                return {'success': False, 'error': 'Utente non trovato'}
            
            return {'success': True, 'message': 'Utente aggiornato'}
        
        finally:
            conn.close()
    
    def delete_user(self, user_id):
        """Elimina utente (admin only)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            # Non permettere eliminazione ultimo admin
            cursor.execute("SELECT COUNT(*) FROM users WHERE ruolo = 'admin'")
            admin_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT ruolo FROM users WHERE id = ?", (user_id,))
            user = cursor.fetchone()
            
            if not user:
                return {'success': False, 'error': 'Utente non trovato'}
            
            if user['ruolo'] == 'admin' and admin_count <= 1:
                return {'success': False, 'error': 'Impossibile eliminare ultimo admin'}
            
            cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()
            
            return {'success': True, 'message': 'Utente eliminato'}
        
        finally:
            conn.close()
    
    # ========== SYNC SUPPORT ==========
    
    def get_all_users_for_sync(self):
        """Ottieni TUTTI gli utenti con password_hash per sync"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT * FROM users")
            users = [dict(row) for row in cursor.fetchall()]
            return users
        finally:
            conn.close()

# Test
if __name__ == '__main__':
    db = AuthDB()
    print("[AuthDB] Database inizializzato")
    print("[AuthDB] Admin default: username='admin', password='admin123'")