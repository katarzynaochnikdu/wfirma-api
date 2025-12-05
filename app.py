"""
wFirma API - Web Service dla Render
Flask web app z OAuth 2.0 i endpointami API
"""
from flask import Flask, request, redirect, jsonify
import requests
import json
import os
import time
from urllib.parse import quote
from functools import wraps

app = Flask(__name__)

# Konfiguracja z zmiennych środowiskowych
CLIENT_ID = os.environ.get('CLIENT_ID')
CLIENT_SECRET = os.environ.get('CLIENT_SECRET')
REDIRECT_URI = os.environ.get('REDIRECT_URI', 'http://localhost:5000/callback')
TOKEN_FILE = "wfirma_token.json"

SCOPES = [
    "contractors-read", "contractors-write",
    "invoice_descriptions-read",
    "invoice_deliveries-read", "invoice_deliveries-write",
    "invoices-read", "invoices-write",
    "notes-read", "notes-write",
    "payments-read", "payments-write",
    "tags-read", "tags-write",
]

# ==================== FUNKCJE POMOCNICZE ====================

def save_token(access_token, expires_in):
    """Zapisz token do pliku"""
    token_data = {
        'access_token': access_token,
        'expires_at': time.time() + expires_in - 60  # 60 sek margines
    }
    try:
        with open(TOKEN_FILE, 'w') as f:
            json.dump(token_data, f)
    except Exception as e:
        print(f"[ERROR] Nie można zapisać tokenu: {e}")

def is_token_valid():
    """Sprawdź czy zapisany token jest ważny"""
    if not os.path.exists(TOKEN_FILE):
        return False
    try:
        with open(TOKEN_FILE, 'r') as f:
            token_data = json.load(f)
        return time.time() < token_data.get('expires_at', 0)
    except:
        return False

def load_token(silent=False):
    """Wczytaj token z pliku jeśli istnieje i jest ważny"""
    if not os.path.exists(TOKEN_FILE):
        return None
    
    try:
        with open(TOKEN_FILE, 'r') as f:
            token_data = json.load(f)
        
        if time.time() < token_data.get('expires_at', 0):
            remaining = int(token_data['expires_at'] - time.time())
            if not silent:
                print(f"[LOG] ✓ Token ważny jeszcze {remaining} sekund")
            return token_data['access_token']
        else:
            if not silent:
                print("[LOG] Token wygasł")
            return None
    except Exception as e:
        if not silent:
            print(f"[LOG] Błąd wczytywania tokenu: {e}")
        return None

def require_token(f):
    """Decorator wymagający ważnego tokenu"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = load_token(silent=True)
        if not token or not is_token_valid():
            return jsonify({
                'error': 'Brak autoryzacji',
                'message': 'Przejdź do /auth aby się zalogować'
            }), 401
        return f(token, *args, **kwargs)
    return decorated_function

# ==================== ENDPOINTY OAUTH ====================

@app.route('/')
def index():
    """Strona główna z dokumentacją API"""
    return jsonify({
        'message': 'wFirma API Service',
        'version': '1.0',
        'endpoints': {
            '/auth': 'Rozpocznij autoryzację OAuth 2.0',
            '/callback': 'Callback OAuth (automatyczny redirect)',
            '/api/contractor/<nip>': 'GET - Sprawdź kontrahenta po NIP',
            '/api/contractor/add': 'POST - Dodaj nowego kontrahenta',
            '/api/invoice/create': 'POST - Utwórz fakturę',
            '/api/token/status': 'GET - Sprawdź status tokenu',
        }
    })

@app.route('/auth')
def auth():
    """Rozpocznij autoryzację OAuth 2.0"""
    if not CLIENT_ID:
        return jsonify({'error': 'CLIENT_ID nie jest ustawiony'}), 500
    
    scope_str = " ".join(SCOPES)
    auth_url = (
        "https://wfirma.pl/oauth2/auth?"
        f"response_type=code&"
        f"client_id={CLIENT_ID}&"
        f"scope={quote(scope_str)}&"
        f"redirect_uri={quote(REDIRECT_URI, safe='')}"
    )
    return redirect(auth_url)

@app.route('/callback')
def callback():
    """Odbierz kod autoryzacyjny i wymień na token"""
    code = request.args.get('code')
    error = request.args.get('error')
    
    if error:
        return jsonify({
            'error': 'Błąd autoryzacji',
            'details': error
        }), 400
    
    if not code:
        return jsonify({'error': 'Brak kodu autoryzacyjnego'}), 400
    
    # Wymień kod na token
    token_url = "https://api2.wfirma.pl/oauth2/token?oauth_version=2"
    data = {
        'grant_type': 'authorization_code',
        'code': code,
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'redirect_uri': REDIRECT_URI
    }
    
    try:
        response = requests.post(token_url, data=data)
        if response.status_code != 200:
            return jsonify({
                'error': 'Błąd wymiany tokenu',
                'status': response.status_code,
                'details': response.text
            }), 400
        
        token_data = response.json()
        expires_in = token_data.get('expires_in', 3600)
        access_token = token_data['access_token']
        
        # Zapisz token
        save_token(access_token, expires_in)
        
        return jsonify({
            'message': 'Autoryzacja zakończona pomyślnie',
            'token_valid_for': f"{expires_in} sekund",
            'expires_in': expires_in
        })
    except Exception as e:
        return jsonify({
            'error': 'Błąd podczas wymiany tokenu',
            'details': str(e)
        }), 500

# ==================== ENDPOINTY API ====================

@app.route('/api/token/status')
def token_status():
    """Sprawdź status tokenu"""
    token = load_token(silent=True)
    is_valid = is_token_valid()
    
    if token and is_valid:
        try:
            with open(TOKEN_FILE, 'r') as f:
                token_data = json.load(f)
            remaining = int(token_data['expires_at'] - time.time())
            return jsonify({
                'status': 'valid',
                'remaining_seconds': remaining,
                'expires_at': token_data['expires_at']
            })
        except:
            pass
    
    return jsonify({
        'status': 'invalid',
        'message': 'Brak ważnego tokenu. Przejdź do /auth'
    })

@app.route('/api/contractor/<nip>')
@require_token
def check_contractor(token, nip):
    """Sprawdź czy kontrahent istnieje po NIP"""
    clean_nip = nip.replace("-", "").replace(" ", "")
    
    api_url = "https://api2.wfirma.pl/contractors/find?inputFormat=json&outputFormat=json&oauth_version=2"
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    
    search_data = {
        "contractors": {
            "parameters": {
                "conditions": {
                    "condition": {
                        "field": "nip",
                        "operator": "eq",
                        "value": clean_nip
                    }
                }
            }
        }
    }
    
    try:
        response = requests.post(api_url, headers=headers, json=search_data)
        
        if response.status_code == 200:
            data = response.json()
            contractors = data.get('contractors', {})
            
            if contractors:
                # wFirma zwraca dict z kluczami "0", "1", etc.
                contractor = None
                if isinstance(contractors, dict):
                    for key in contractors:
                        if key.isdigit():
                            contractor = contractors[key].get('contractor')
                            break
                    if not contractor and 'contractor' in contractors:
                        contractor = contractors['contractor']
                
                if contractor:
                    return jsonify({
                        'exists': True,
                        'contractor': contractor
                    })
        
        return jsonify({
            'exists': False,
            'nip': clean_nip,
            'message': 'Kontrahent nie został znaleziony'
        })
    
    except Exception as e:
        return jsonify({
            'error': 'Błąd podczas wyszukiwania kontrahenta',
            'details': str(e)
        }), 500

@app.route('/api/contractor/add', methods=['POST'])
@require_token
def add_contractor(token):
    """Dodaj nowego kontrahenta"""
    data = request.json
    
    if not data:
        return jsonify({'error': 'Brak danych w żądaniu'}), 400
    
    api_url = "https://api2.wfirma.pl/contractors/add?inputFormat=json&outputFormat=json&oauth_version=2"
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    
    # Struktura wg dokumentacji wFirma
    contractor_data = {
        "contractor": data
    }
    
    try:
        response = requests.post(api_url, headers=headers, json=contractor_data)
        
        if response.status_code == 200:
            result = response.json()
            return jsonify({
                'success': True,
                'contractor': result.get('contractor', {})
            })
        else:
            return jsonify({
                'error': 'Błąd podczas dodawania kontrahenta',
                'status': response.status_code,
                'details': response.text
            }), response.status_code
    
    except Exception as e:
        return jsonify({
            'error': 'Błąd podczas dodawania kontrahenta',
            'details': str(e)
        }), 500

@app.route('/api/invoice/create', methods=['POST'])
@require_token
def create_invoice(token):
    """Utwórz fakturę"""
    data = request.json
    
    if not data:
        return jsonify({'error': 'Brak danych w żądaniu'}), 400
    
    api_url = "https://api2.wfirma.pl/invoices/add?inputFormat=json&outputFormat=json&oauth_version=2"
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    
    # Struktura wg dokumentacji wFirma
    invoice_data = {
        "invoice": data
    }
    
    try:
        response = requests.post(api_url, headers=headers, json=invoice_data)
        
        if response.status_code == 200:
            result = response.json()
            return jsonify({
                'success': True,
                'invoice': result.get('invoice', {})
            })
        else:
            return jsonify({
                'error': 'Błąd podczas tworzenia faktury',
                'status': response.status_code,
                'details': response.text
            }), response.status_code
    
    except Exception as e:
        return jsonify({
            'error': 'Błąd podczas tworzenia faktury',
            'details': str(e)
        }), 500

# ==================== START SERWERA ====================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

