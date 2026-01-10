// ========================================
// AUTHENTICATION MANAGEMENT
// ========================================

// Check if user is authenticated on page load
document.addEventListener('DOMContentLoaded', function() {
    const token = localStorage.getItem('auth_token');
    
    if (!token) {
        console.log('[Auth] No token found, user needs to login');
        // Se non c'è token e siamo nella dashboard, potremmo reindirizzare a /login
        // ma per ora lasciamo che l'utente veda la pagina
    } else {
        console.log('[Auth] Token found:', token.substring(0, 10) + '...');
        // Verifica che il token sia valido
        verifyToken(token);
    }
});

// Verify token is still valid
async function verifyToken(token) {
    try {
        const response = await fetch('/api/status', {
            credentials: 'include',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            }
        });
        
        if (response.status === 401) {
            console.log('[Auth] Token expired, clearing');
            localStorage.removeItem('auth_token');
        } else {
            console.log('[Auth] Token valid');
        }
    } catch (error) {
        console.error('[Auth] Error verifying token:', error);
    }
}

// Login function (can be called from anywhere)
async function doLogin(username, password) {
    try {
        const response = await fetch('/api/auth/login', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ username, password })
        });
        
        const data = await response.json();
        
        if (data.success && data.session_token) {
            // Save token
            localStorage.setItem('auth_token', data.session_token);
            console.log('[Auth] Login successful, token saved');
            return { success: true, user: data.user };
        } else {
            console.error('[Auth] Login failed:', data.error);
            return { success: false, error: data.error };
        }
    } catch (error) {
        console.error('[Auth] Login error:', error);
        return { success: false, error: error.message };
    }
}

// Logout function
async function doLogout() {
    const token = localStorage.getItem('auth_token');
    
    if (token) {
        try {
            await fetch('/api/auth/logout', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                }
            });
        } catch (error) {
            console.error('[Auth] Logout error:', error);
        }
    }
    
    // Clear token
    localStorage.removeItem('auth_token');
    console.log('[Auth] Logged out, token cleared');
    
    // Redirect to login page
    window.location.href = '/login';
}

// Get current token
function getAuthToken() {
    return localStorage.getItem('auth_token');
}

// Export functions to window
window.doLogin = doLogin;
window.doLogout = doLogout;
window.getAuthToken = getAuthToken;
window.verifyToken = verifyToken;

console.log('[Auth] Authentication module loaded');

// ========================================
// AUTO-INTERCEPT LOGIN RESPONSES
// ========================================

// Intercetta tutte le fetch per salvare automaticamente il token
const originalFetch = window.fetch;
window.fetch = async function(...args) {
    const response = await originalFetch(...args);
    
    // Clona la response per poterla leggere
    const clonedResponse = response.clone();
    
    // Se è una risposta alla login API
    if (args[0].includes('/api/auth/login')) {
        try {
            const data = await clonedResponse.json();
            
            // Se login successful, salva il token
            if (data.success && data.session_token) {
                localStorage.setItem('auth_token', data.session_token);
                console.log('[Auth] Token auto-saved after login');
            }
        } catch (e) {
            // Ignora errori di parsing JSON
        }
    }
    
    return response;
};

console.log('[Auth] Auto-intercept enabled for login');