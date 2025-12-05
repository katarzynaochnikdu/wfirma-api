"""
wFirma API - Web Service dla Render
Flask web app z OAuth 2.0 i endpointami API
"""
from flask import Flask, request, redirect, jsonify
import requests
import json
import os
import time
import re
import xml.etree.ElementTree as ET
from urllib.parse import quote
from functools import wraps

app = Flask(__name__)

# Konfiguracja z zmiennych środowiskowych (wFirma OAuth)
CLIENT_ID = os.environ.get('CLIENT_ID')
CLIENT_SECRET = os.environ.get('CLIENT_SECRET')
REDIRECT_URI = os.environ.get('REDIRECT_URI', 'http://localhost:5000/callback')
TOKEN_FILE = "wfirma_token.json"

# Konfiguracja GUS/BIR (przeniesiona z backendu Googie_GUS)
# Najpierw próbujemy standardowej zmiennej GUS_API_KEY,
# jeśli brak – użyjemy ewentualnej BIR1_medidesk (z GCP).
GUS_API_KEY = os.environ.get('GUS_API_KEY') or os.environ.get('BIR1_medidesk')
GUS_USE_TEST = (os.environ.get('GUS_USE_TEST', 'false') or '').lower() == 'true'

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


# ==================== FUNKCJE GUS/BIR (prosty port z Googie_GUS) ====================

def escape_xml(unsafe: str) -> str:
    """
    Bezpieczne wstawianie wartości do SOAP XML (ochrona przed SOAP injection).
    Port funkcji escapeXml z backendu Googie_GUS (Node).
    """
    if not isinstance(unsafe, str):
        return ""
    return (
        unsafe.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def decode_bir_inner_xml(encoded: str) -> str:
    """
    Dekodowanie wewnętrznego XML zwracanego przez GUS (DaneSzukajPodmiotyResult).
    Port funkcji decodeBirInnerXml z backendu Googie_GUS.
    """
    if not isinstance(encoded, str):
        return ""

    return (
        encoded.lstrip("\ufeff")
        .replace("&amp;amp;", "&amp;")
        .replace("&#xD;", "\r")
        .replace("&#xA;", "\n")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
        .replace("&amp;", "&")
        .strip()
    )


def post_soap_gus(bir_host: str, envelope: str, sid: str | None, timeout: int = 10) -> requests.Response:
    """
    Minimalna wersja postSoap z Googie_GUS – wysyła envelope SOAP do GUS/BIR.
    Używa requests, timeout domyślnie 10s. Nagłówek 'sid' ustawiany jeśli podano.
    """
    url = f"https://{bir_host}/wsBIR/UslugaBIRzewnPubl.svc"
    headers = {
        "Content-Type": "application/soap+xml; charset=utf-8",
        "Accept": "application/soap+xml",
        "User-Agent": "Googie_GUS Widget/0.0.1",
    }
    if sid:
        headers["sid"] = str(sid)

    # Wysyłamy surowy envelope jako dane POST
    response = requests.post(url, data=envelope.encode("utf-8"), headers=headers, timeout=timeout)
    return response


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


# ==================== ENDPOINTY GUS / REGON ====================

@app.route('/api/gus/name-by-nip', methods=['POST'])
def gus_name_by_nip():
    """
    Prosty port endpointu /api/gus/name-by-nip z backendu Googie_GUS.
    Wejście: JSON { "nip": "1234567890" }
    Wyjście: { "data": [ { regon, nip, nazwa, ... } ] } albo komunikat błędu.
    """
    body = request.get_json(silent=True) or {}

    # Walidacja i oczyszczenie NIP (jak w Node)
    nip_raw = str(body.get('nip', ''))[:20]
    clean_nip = re.sub(r'[^0-9]', '', nip_raw)

    from_header_key = (request.headers.get('x-gus-api-key') or '')[:100]
    api_key = from_header_key or GUS_API_KEY or ''

    if not clean_nip:
        return jsonify({'error': 'Brak NIP'}), 400

    if len(clean_nip) != 10:
        return jsonify({'error': 'NIP musi składać się z dokładnie 10 cyfr'}), 400

    if not api_key:
        return jsonify({
            'error': 'Brak klucza GUS_API_KEY',
            'hint': 'Ustaw zmienną środowiskową GUS_API_KEY / BIR1_medidesk lub przekaż nagłówek x-gus-api-key.'
        }), 400

    # Przełącznik środowiska test/produkcyjne – zgodnie z Googie_GUS
    use_test_env = api_key == 'abcde12345abcde12345' or GUS_USE_TEST
    bir_host = 'wyszukiwarkaregontest.stat.gov.pl' if use_test_env else 'wyszukiwarkaregon.stat.gov.pl'
    bir_url = f'https://{bir_host}/wsBIR/UslugaBIRzewnPubl.svc'

    # Log tylko diagnostyczny (bez pełnego klucza)
    print(f"[GUS] name-by-nip nip={clean_nip} env={'TEST' if use_test_env else 'PROD'} host={bir_host}")

    safe_api_key = escape_xml(api_key)
    login_envelope = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:ns="http://CIS/BIR/PUBL/2014/07">'
        '<soap:Header xmlns:wsa="http://www.w3.org/2005/08/addressing">'
        f'<wsa:To>{bir_url}</wsa:To>'
        '<wsa:Action>http://CIS/BIR/PUBL/2014/07/IUslugaBIRzewnPubl/Zaloguj</wsa:Action>'
        '</soap:Header>'
        '<soap:Body>'
        '<ns:Zaloguj>'
        f'<ns:pKluczUzytkownika>{safe_api_key}</ns:pKluczUzytkownika>'
        '</ns:Zaloguj>'
        '</soap:Body>'
        '</soap:Envelope>'
    )

    try:
        login_resp = post_soap_gus(bir_host, login_envelope, sid=None, timeout=10)
    except Exception as e:
        return jsonify({
            'error': 'Błąd komunikacji z GUS podczas logowania',
            'message': str(e)
        }), 502

    sid_match = re.search(r'<ZalogujResult>([^<]*)</ZalogujResult>', login_resp.text or '')
    sid = sid_match.group(1).strip() if sid_match else ''

    if not sid:
        snippet = (login_resp.text or '')[:300]
        return jsonify({
            'error': 'Logowanie do GUS nie powiodło się (brak SID)',
            'debug': snippet
        }), 502

    safe_nip = escape_xml(clean_nip)
    search_envelope = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" '
        'xmlns:ns="http://CIS/BIR/PUBL/2014/07" '
        'xmlns:q1="http://CIS/BIR/PUBL/2014/07/DataContract" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        '<soap:Header xmlns:wsa="http://www.w3.org/2005/08/addressing">'
        f'<wsa:To>{bir_url}</wsa:To>'
        '<wsa:Action>http://CIS/BIR/PUBL/2014/07/IUslugaBIRzewnPubl/DaneSzukajPodmioty</wsa:Action>'
        '</soap:Header>'
        '<soap:Body>'
        '<ns:DaneSzukajPodmioty>'
        '<ns:pParametryWyszukiwania>'
        '<q1:Krs xsi:nil="true"/>'
        '<q1:Krsy xsi:nil="true"/>'
        f'<q1:Nip>{safe_nip}</q1:Nip>'
        '<q1:Nipy xsi:nil="true"/>'
        '<q1:Regon xsi:nil="true"/>'
        '<q1:Regony14zn xsi:nil="true"/>'
        '<q1:Regony9zn xsi:nil="true"/>'
        '</ns:pParametryWyszukiwania>'
        '</ns:DaneSzukajPodmioty>'
        '</soap:Body>'
        '</soap:Envelope>'
    )

    try:
        search_resp = post_soap_gus(bir_host, search_envelope, sid=sid, timeout=10)
    except Exception as e:
        return jsonify({
            'error': 'Błąd komunikacji z GUS podczas wyszukiwania',
            'message': str(e)
        }), 502

    soap_part = search_resp.text or ''

    # Obsługa odpowiedzi multipart/MTOM – wyciągamy część SOAP, jeśli trzeba
    if 'Content-Type: application/xop+xml' in soap_part:
        match = re.search(
            r'Content-Type: application/xop\+xml[^\r\n]*\r?\n\r?\n([\s\S]*?)\r?\n--uuid:',
            soap_part,
            re.MULTILINE | re.DOTALL,
        )
        if match:
            soap_part = match.group(1)

    # Brak wyniku
    if re.search(r'<DaneSzukajResult\s*/>', soap_part):
        return jsonify({
            'error': 'GUS nie znalazł podmiotu dla podanego NIP'
        }), 404

    result_match = re.search(
        r'<DaneSzukajPodmiotyResult>([\s\S]*?)</DaneSzukajPodmiotyResult>',
        soap_part,
        re.MULTILINE | re.DOTALL,
    )
    inner_xml = result_match.group(1) if result_match else ''

    if not inner_xml:
        return jsonify({
            'error': 'Brak danych w odpowiedzi GUS (DaneSzukajPodmiotyResult pusty)'
        }), 404

    decoded_xml = decode_bir_inner_xml(inner_xml)
    if not decoded_xml:
        return jsonify({
            'error': 'Brak danych po dekodowaniu odpowiedzi GUS'
        }), 502

    try:
        root = ET.fromstring(decoded_xml)
    except ET.ParseError as e:
        return jsonify({
            'error': 'Nie udało się sparsować danych GUS',
            'message': str(e)
        }), 502

    data_list: list[dict] = []

    for dane in root.findall('.//dane'):
        def get_text(tag: str) -> str | None:
            el = dane.find(tag)
            return el.text if el is not None else None

        mapped = {
            'regon': get_text('Regon'),
            'nip': get_text('Nip'),
            'nazwa': get_text('Nazwa'),
            'wojewodztwo': get_text('Wojewodztwo'),
            'powiat': get_text('Powiat'),
            'gmina': get_text('Gmina'),
            'miejscowosc': get_text('Miejscowosc'),
            'kodPocztowy': get_text('KodPocztowy'),
            'ulica': get_text('Ulica'),
            'nrNieruchomosci': get_text('NrNieruchomosci'),
            'nrLokalu': get_text('NrLokalu'),
            'typ': get_text('Typ'),
            'silosId': get_text('SilosID'),
            'miejscowoscPoczty': get_text('MiejscowoscPoczty'),
            'krs': get_text('Krs'),
        }
        data_list.append(mapped)

    return jsonify({'data': data_list}), 200


# ==================== START SERWERA ====================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

