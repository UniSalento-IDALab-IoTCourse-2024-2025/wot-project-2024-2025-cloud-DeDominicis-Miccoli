// ========== USER MANAGEMENT (ADMIN ONLY) ==========

let allUsers = [];

function showUserManagement() {
    document.querySelectorAll('.realtime-view, .history-view, .anomalies-view, .debug-view, .models-view, .settings-view, .user-management-view').forEach(view => {
        view.classList.remove('active');
    });
    document.getElementById('userManagementView').classList.add('active');
    updateSidebarActive('user-management');
    
    loadUsers();
}

async function loadUsers() {
    try {
        const token = localStorage.getItem('auth_token');
        
        const response = await fetch('/api/users/list', {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        
        const data = await response.json();
        
        if (data.success) {
            allUsers = data.users;
            renderUsersTable();
        } else {
            showUserError(data.error || 'Errore caricamento utenti');
        }
    } catch (error) {
        console.error('[UserManagement] Error loading users:', error);
        showUserError('Errore di connessione');
    }
}

function renderUsersTable() {
    const tbody = document.getElementById('usersTableBody');
    
    if (allUsers.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="6" style="text-align: center; padding: 2rem; color: var(--text-secondary);">
                    Nessun utente registrato
                </td>
            </tr>
        `;
        return;
    }
    
    tbody.innerHTML = allUsers.map(user => {
        const roleColors = {
            'paziente': '#10b981',
            'medico': '#3b82f6',
            'admin': '#ef4444'
        };
        
        const roleColor = roleColors[user.ruolo] || '#94a3b8';
        const lastLogin = user.last_login ? new Date(user.last_login).toLocaleString('it-IT') : 'Mai';
        
        return `
            <tr>
                <td>${user.id}</td>
                <td><strong>${user.username}</strong></td>
                <td>${user.nome} ${user.cognome}</td>
                <td>
                    <span class="role-badge" style="background: ${roleColor}20; color: ${roleColor}; padding: 0.25rem 0.75rem; border-radius: 12px; font-size: 0.75rem; font-weight: 600; text-transform: uppercase;">
                        ${user.ruolo}
                    </span>
                </td>
                <td style="font-size: 0.85rem; color: var(--text-secondary);">${lastLogin}</td>
                <td>
                    <div style="display: flex; gap: 0.5rem; justify-content: flex-end;">
                        <button class="btn-user-action btn-edit" onclick="editUser(${user.id})" title="Modifica">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                                <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                            </svg>
                        </button>
                        <button class="btn-user-action btn-delete" onclick="deleteUser(${user.id}, '${user.username}')" title="Elimina">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <polyline points="3 6 5 6 21 6"/>
                                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                            </svg>
                        </button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

function editUser(userId) {
    const user = allUsers.find(u => u.id === userId);
    if (!user) return;
    
    document.getElementById('editUserId').value = user.id;
    document.getElementById('editNome').value = user.nome;
    document.getElementById('editCognome').value = user.cognome;
    document.getElementById('editRuolo').value = user.ruolo;
    document.getElementById('editPassword').value = '';
    
    const modal = document.getElementById('editUserModal');
    modal.classList.add('active');
}

function closeEditModal() {
    const modal = document.getElementById('editUserModal');
    modal.classList.remove('active');
}

async function saveUserEdit() {
    const userId = document.getElementById('editUserId').value;
    const nome = document.getElementById('editNome').value;
    const cognome = document.getElementById('editCognome').value;
    const ruolo = document.getElementById('editRuolo').value;
    const password = document.getElementById('editPassword').value;
    
    const token = localStorage.getItem('auth_token');
    const saveBtn = document.getElementById('saveUserEditBtn');
    
    saveBtn.disabled = true;
    saveBtn.textContent = 'Salvataggio...';
    
    try {
        const payload = { nome, cognome, ruolo };
        if (password) {
            payload.new_password = password;
        }
        
        const response = await fetch(`/api/users/${userId}`, {
            method: 'PUT',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });
        
        const data = await response.json();
        
        if (data.success) {
            showUserSuccess('Utente aggiornato con successo');
            closeEditModal();
            loadUsers();
        } else {
            showUserError(data.error || 'Errore aggiornamento utente');
        }
    } catch (error) {
        console.error('[UserManagement] Error updating user:', error);
        showUserError('Errore di connessione');
    } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = 'Salva Modifiche';
    }
}

async function deleteUser(userId, username) {
    const confirmed = await showConfirm(`Sei sicuro di voler eliminare l'utente "${username}"?\n\nQuesta azione è irreversibile.`, 'Conferma Eliminazione');
    if (!confirmed) {
    }
    
    const token = localStorage.getItem('auth_token');
    
    fetch(`/api/users/${userId}`, {
        method: 'DELETE',
        headers: {
            'Authorization': `Bearer ${token}`
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showUserSuccess('Utente eliminato con successo');
            loadUsers();
        } else {
            showUserError(data.error || 'Errore eliminazione utente');
        }
    })
    .catch(error => {
        console.error('[UserManagement] Error deleting user:', error);
        showUserError('Errore di connessione');
    });
}

function showUserSuccess(message) {
    const resultDiv = document.getElementById('userManagementResult');
    if (resultDiv) {
        resultDiv.className = 'user-result success';
        resultDiv.textContent = message;
        resultDiv.style.display = 'block';
        
        setTimeout(() => {
            resultDiv.style.display = 'none';
        }, 5000);
    }
}

function showUserError(message) {
    const resultDiv = document.getElementById('userManagementResult');
    if (resultDiv) {
        resultDiv.className = 'user-result error';
        resultDiv.textContent = message;
        resultDiv.style.display = 'block';
        
        setTimeout(() => {
            resultDiv.style.display = 'none';
        }, 5000);
    }
}

// Close modal on outside click
document.addEventListener('click', (e) => {
    const modal = document.getElementById('editUserModal');
    if (modal && e.target === modal) {
        closeEditModal();
    }
});