""" 
wFirma API - Web Service dla Render
Flask web app z OAuth 2.0 i endpointami API
"""
from flask import Flask, request, redirect, jsonify, Response
import requests
import json
import os
import time
import re
import datetime
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


# ==================== POMOCNICZE: WFIRMA (kontrahenci, faktury, PDF, mail) ====================


def get_wfirma_headers(token: str, accept: str = "application/json", with_content_type: bool = True) -> dict:
    """Zwraca nagłówki autoryzacji do wFirma; łatwe do podmiany na M2M w przyszłości."""
    headers = {
        'Authorization': f'Bearer {token}',
    }
    if with_content_type:
        headers['Content-Type'] = 'application/json'
    if accept:
        headers['Accept'] = accept
    return headers


def wfirma_find_contractor_by_nip(token: str, nip: str) -> tuple[dict | None, requests.Response | None]:
    """Znajdź kontrahenta po NIP; zwraca (contractor_dict|None, response)."""
    clean_nip = nip.replace("-", "").replace(" ", "")
    api_url = "https://api2.wfirma.pl/contractors/find?inputFormat=json&outputFormat=json&oauth_version=2"
    headers = get_wfirma_headers(token)
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
    resp = None
    try:
        resp = requests.post(api_url, headers=headers, json=search_data)
        if resp.status_code == 200:
            data = resp.json()
            contractors = data.get('contractors', {})
            if contractors and isinstance(contractors, dict):
                for key in contractors:
                    if key.isdigit():
                        return contractors[key].get('contractor'), resp
                if 'contractor' in contractors:
                    return contractors['contractor'], resp
        return None, resp
    except Exception:
        return None, resp


def wfirma_add_contractor(token: str, contractor_payload: dict) -> tuple[dict | None, requests.Response | None]:
    """Dodaj kontrahenta; zwraca (contractor_dict|None, response)."""
    api_url = "https://api2.wfirma.pl/contractors/add?inputFormat=json&outputFormat=json&oauth_version=2"
    headers = get_wfirma_headers(token)
    resp = None
    try:
        resp = requests.post(api_url, headers=headers, json={"contractor": contractor_payload})
        if resp.status_code == 200:
            result = resp.json()
            contractor = result.get('contractor') or result.get('contractors', {}).get('contractor')
            return contractor or result, resp
        return None, resp
    except Exception:
        return None, resp


def wfirma_create_invoice(token: str, invoice_payload: dict) -> tuple[dict | None, requests.Response | None]:
    """Utwórz fakturę; zwraca (invoice_dict|None, response)."""
    api_url = "https://api2.wfirma.pl/invoices/add?inputFormat=json&outputFormat=json&oauth_version=2"
    headers = get_wfirma_headers(token)
    resp = None
    try:
        request_body = {"invoice": invoice_payload}
        # LOG: pełny request body
        try:
            import json as json_lib
            print("[WFIRMA DEBUG] FULL invoice request body:", json_lib.dumps(request_body, ensure_ascii=False, indent=2))
        except Exception:
            pass
        
        resp = requests.post(api_url, headers=headers, json=request_body)
        if resp.status_code == 200:
            result = resp.json()
            invoice = result.get('invoice') or result.get('invoices', {}).get('invoice')
            return invoice or result, resp
        return None, resp
    except Exception:
        return None, resp


def wfirma_get_invoice_pdf(token: str, invoice_id: str) -> requests.Response:
    """
    Pobierz PDF faktury z wFirma.
    Uwaga: bazujemy na wzorcu endpointu 'invoices/print' z outputFormat=pdf.
    """
    api_url = "https://api2.wfirma.pl/invoices/print"
    params = {
        "id": invoice_id,
        "outputFormat": "pdf",
        "oauth_version": "2",
    }
    headers = get_wfirma_headers(token, accept="application/pdf", with_content_type=False)
    return requests.get(api_url, headers=headers, params=params, stream=True)


def wfirma_send_invoice_email(token: str, invoice_id: str, email: str) -> requests.Response:
    """
    Wyślij fakturę e-mailem przez wFirma.
    Uwaga: bazujemy na module invoice_deliveries (write).
    """
    api_url = "https://api2.wfirma.pl/invoice_deliveries/send?inputFormat=json&outputFormat=json&oauth_version=2"
    headers = get_wfirma_headers(token)
    payload = {
        "invoice_delivery": {
            "invoice_id": invoice_id,
            "email": email,
        }
    }
    return requests.post(api_url, headers=headers, json=payload)


# ==================== POMOCNICZE: GUS LOOKUP (do ponownego użycia w workflow) ====================


def gus_lookup_nip(clean_nip: str) -> tuple[list[dict] | None, str | None]:
    """
    Minimalny helper do ponownego użycia w workflow (bez HTTP round-trip do własnego endpointu).
    Zwraca (lista rekordów lub None, komunikat błędu lub None).
    """
    from_header_key = ''
    api_key = GUS_API_KEY or ''

    if not api_key:
        return None, 'Brak klucza GUS_API_KEY'

    use_test_env = api_key == 'abcde12345abcde12345' or GUS_USE_TEST
    bir_host = 'wyszukiwarkaregontest.stat.gov.pl' if use_test_env else 'wyszukiwarkaregon.stat.gov.pl'
    bir_url = f'https://{bir_host}/wsBIR/UslugaBIRzewnPubl.svc'

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
        return None, f'Błąd komunikacji z GUS podczas logowania: {e}'

    sid_match = re.search(r'<ZalogujResult>([^<]*)</ZalogujResult>', login_resp.text or '')
    sid = sid_match.group(1).strip() if sid_match else ''
    if not sid:
        return None, 'Logowanie do GUS nie powiodło się (brak SID)'

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
        return None, f'Błąd komunikacji z GUS podczas wyszukiwania: {e}'

    soap_part = search_resp.text or ''
    if 'Content-Type: application/xop+xml' in soap_part:
        match = re.search(
            r'Content-Type: application/xop\+xml[^\r\n]*\r?\n\r?\n([\s\S]*?)\r?\n--uuid:',
            soap_part,
            re.MULTILINE | re.DOTALL,
        )
        if match:
            soap_part = match.group(1)

    if re.search(r'<DaneSzukajResult\s*/>', soap_part):
        return [], None

    result_match = re.search(
        r'<DaneSzukajPodmiotyResult>([\s\S]*?)</DaneSzukajPodmiotyResult>',
        soap_part,
        re.MULTILINE | re.DOTALL,
    )
    inner_xml = result_match.group(1) if result_match else ''
    if not inner_xml:
        return None, 'Brak danych w odpowiedzi GUS (DaneSzukajPodmiotyResult pusty)'

    decoded_xml = decode_bir_inner_xml(inner_xml)
    if not decoded_xml:
        return None, 'Brak danych po dekodowaniu odpowiedzi GUS'

    try:
        root = ET.fromstring(decoded_xml)
    except ET.ParseError as e:
        return None, f'Nie udało się sparsować danych GUS: {e}'

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

    return data_list, None


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
    contractor, resp = wfirma_find_contractor_by_nip(token, nip)
    if contractor:
        return jsonify({'exists': True, 'contractor': contractor})

    clean_nip = nip.replace("-", "").replace(" ", "")
    status = resp.status_code if resp else None
    return jsonify({
        'exists': False,
        'nip': clean_nip,
        'message': 'Kontrahent nie został znaleziony',
        'status': status
    })

@app.route('/api/contractor/add', methods=['POST'])
@require_token
def add_contractor(token):
    """Dodaj nowego kontrahenta"""
    data = request.json
    
    if not data:
        return jsonify({'error': 'Brak danych w żądaniu'}), 400
    contractor, resp = wfirma_add_contractor(token, data)
    if contractor:
        return jsonify({'success': True, 'contractor': contractor})

    status = resp.status_code if resp else None
    return jsonify({
        'error': 'Błąd podczas dodawania kontrahenta',
        'status': status,
        'details': resp.text if resp else 'Brak odpowiedzi'
    }), status or 500

@app.route('/api/invoice/create', methods=['POST'])
@require_token
def create_invoice(token):
    """Utwórz fakturę"""
    data = request.json
    
    if not data:
        return jsonify({'error': 'Brak danych w żądaniu'}), 400
    invoice, resp = wfirma_create_invoice(token, data)
    if invoice:
        return jsonify({'success': True, 'invoice': invoice})

    status = resp.status_code if resp else None
    return jsonify({
        'error': 'Błąd podczas tworzenia faktury',
        'status': status,
        'details': resp.text if resp else 'Brak odpowiedzi'
    }), status or 500


# ==================== ENDPOINT WORKFLOW: NIP -> GUS -> KONTRAHENT -> FAKTURA ====================


def build_invoice_payload(invoice_input: dict, contractor_id: str) -> tuple[dict | None, str | None]:
    """Mapper uproszczonego JSON na strukturę wFirma invoices/add."""
    if not invoice_input:
        return None, 'Brak sekcji invoice'

    positions = invoice_input.get('positions') or []
    if not isinstance(positions, list) or len(positions) == 0:
        return None, 'Brak pozycji faktury'

    # Daty
    issue_date = invoice_input.get('issue_date')
    sale_date = invoice_input.get('sale_date') or issue_date

    payment_due_date = invoice_input.get('payment_due_date')
    if not payment_due_date:
        due_days = invoice_input.get('payment_due_days')
        if due_days is not None:
            try:
                days_int = int(due_days)
                payment_due_date = (datetime.date.today() + datetime.timedelta(days=days_int)).isoformat()
            except Exception:
                return None, 'Niepoprawny payment_due_days'

    # Minimalny payload - tylko najważniejsze pola
    # contractor_id jako liczba (może wFirma wymaga int, nie string)
    try:
        contractor_id_int = int(contractor_id)
    except (ValueError, TypeError):
        contractor_id_int = contractor_id
    
    try:
        print(f"[WFIRMA DEBUG] contractor_id type: {type(contractor_id).__name__} -> {type(contractor_id_int).__name__}")
    except:
        pass
    
    payload = {
        "contractor_id": contractor_id_int,
        "date": issue_date,  # data wystawienia
        "paymenttype": "przelew",  # może wymaga polskiej nazwy?
    }
    
    # Opcjonalne pola (dodajemy tylko jeśli są w input)
    if sale_date:
        payload["sale_date"] = sale_date
    if payment_due_date:
        payload["payment_date"] = payment_due_date
    # Usuńmy opcjonalne pola - może powodują błąd
    # if invoice_input.get('place'):
    #     payload["issue_place"] = invoice_input.get('place')
    # if invoice_input.get('currency'):
    #     payload["currency"] = invoice_input.get('currency', 'PLN')

    # Pozycje – wFirma zwykle oczekuje struktury invoicecontents -> invoicecontent[]
    invoice_contents = []
    for pos in positions:
        name = pos.get('name')
        qty = pos.get('quantity')
        price_net = pos.get('unit_price_net')
        vat_rate = pos.get('vat_rate')
        if name is None or qty is None or price_net is None or vat_rate is None:
            return None, 'Pozycja wymaga pól: name, quantity, unit_price_net, vat_rate'
        
        # Konwersja na liczby (wFirma wymaga liczb, nie stringów)
        try:
            qty_num = float(qty) if isinstance(qty, str) else qty
            price_num = float(price_net) if isinstance(price_net, str) else price_net
            vat_num = float(vat_rate) if isinstance(vat_rate, str) else vat_rate
        except (ValueError, TypeError):
            return None, f'Niepoprawne wartości liczbowe w pozycji: {name}'
        
        invoice_contents.append({
            "name": name,
            "count": qty_num,
            "unit": pos.get('unit', 'szt'),
            "price": price_num,
            "vat": vat_num,
        })

    # Próbujemy obu wariantów struktury pozycji
    payload["invoicecontent"] = invoice_contents  # format z dokumentacji (tablica bezpośrednio)
    
    # Debug: loguj typy danych w pierwszej pozycji
    if invoice_contents:
        first_pos = invoice_contents[0]
        try:
            print(f"[WFIRMA DEBUG] invoice first position types: count={type(first_pos['count']).__name__}, price={type(first_pos['price']).__name__}, vat={type(first_pos['vat']).__name__}")
        except Exception:
            pass
    
    return payload, None


@app.route('/api/workflow/create-invoice-from-nip', methods=['POST'])
@require_token
def workflow_create_invoice(token):
    """Pełny workflow: NIP -> (GUS) -> kontrahent -> faktura."""
    body = request.get_json(silent=True) or {}
    nip_raw = str(body.get('nip', '')).strip()
    clean_nip = re.sub(r'[^0-9]', '', nip_raw)
    invoice_input = body.get('invoice')
    email_address = (body.get('email') or '').strip()
    send_email_requested = bool(body.get('send_email')) or bool(email_address)

    # LOG: wejście requestu (bez danych wrażliwych)
    try:
        print("[WFIRMA DEBUG] workflow_create_invoice called")
        print("[WFIRMA DEBUG] raw nip:", nip_raw)
        print("[WFIRMA DEBUG] clean nip:", clean_nip)
        print("[WFIRMA DEBUG] invoice keys:", list(invoice_input.keys()) if isinstance(invoice_input, dict) else invoice_input)
        print("[WFIRMA DEBUG] send_email_requested:", send_email_requested, "email:", email_address)
    except Exception:
        pass

    if not clean_nip or len(clean_nip) != 10:
        return jsonify({'error': 'NIP musi mieć 10 cyfr'}), 400
    if not invoice_input:
        return jsonify({'error': 'Brak sekcji invoice'}), 400

    # 1) Szukamy kontrahenta w wFirma
    contractor, resp_find = wfirma_find_contractor_by_nip(token, clean_nip)
    contractor_id = contractor.get('id') if contractor else None
    contractor_created = False

    try:
        print("[WFIRMA DEBUG] find_contractor_by_nip contractor_id:", contractor_id)
        print("[WFIRMA DEBUG] find_contractor_by_nip raw contractor:", contractor)
        if resp_find is not None:
            print("[WFIRMA DEBUG] find response status:", resp_find.status_code)
            body_txt = resp_find.text or ""
            print("[WFIRMA DEBUG] find response body len:", len(body_txt))
            print("[WFIRMA DEBUG] find response body snippet 2000:", body_txt[:2000])
    except Exception:
        pass

    # 2) Jeśli brak kontrahenta – spróbuj GUS i utwórz w wFirma
    if not contractor_id:
        gus_records, gus_err = gus_lookup_nip(clean_nip)
        try:
            print("[WFIRMA DEBUG] gus_lookup_nip records len:", len(gus_records) if gus_records else gus_records, "err:", gus_err)
            if gus_records:
                print("[WFIRMA DEBUG] gus first record:", gus_records[0])
        except Exception:
            pass
        if gus_err:
            return jsonify({'error': 'GUS lookup failed', 'details': gus_err}), 502
        if gus_records is None:
            return jsonify({'error': 'GUS zwrócił błąd'}), 502
        if len(gus_records) == 0:
            return jsonify({'error': 'GUS nie znalazł firmy dla podanego NIP'}), 404

        gus_first = gus_records[0]
        # Sklejamy ulicę z numerem domu/lokalu – wFirma często wymaga pełnego adresu
        street_parts = []
        if gus_first.get('ulica'):
            street_parts.append(gus_first.get('ulica'))
        if gus_first.get('nrNieruchomosci'):
            street_parts.append(gus_first.get('nrNieruchomosci'))
        if gus_first.get('nrLokalu'):
            street_parts.append(gus_first.get('nrLokalu'))
        # Format adresu jak w wFirma - z UKOŚNIKIEM między numerem domu a lokalu
        street_base = gus_first.get('ulica') or ""
        nr_domu = gus_first.get('nrNieruchomosci') or ""
        nr_lokalu = gus_first.get('nrLokalu') or ""
        
        if street_base and nr_domu and nr_lokalu:
            street_full = f"{street_base} {nr_domu}/{nr_lokalu}"
        elif street_base and nr_domu:
            street_full = f"{street_base} {nr_domu}"
        else:
            street_full = street_base

        try:
            print("[WFIRMA DEBUG] street_base:", street_base)
            print("[WFIRMA DEBUG] nr_domu:", nr_domu, "nr_lokalu:", nr_lokalu)
            print("[WFIRMA DEBUG] street_full:", street_full)
        except Exception:
            pass

        # Payload zgodny z formatem zwracanym przez wFirma (po analizie ręcznie dodanego kontrahenta)
        contractor_payload = {
            "name": gus_first.get('nazwa') or clean_nip,
            "altname": gus_first.get('nazwa') or clean_nip,  # WYMAGANE - taka sama wartość jak name
            "nip": clean_nip,
            "tax_id_type": "nip",  # WYMAGANE - typ identyfikatora
            "street": street_full,
            "zip": gus_first.get('kodPocztowy') or "",
            "city": gus_first.get('miejscowosc') or "",
            "country": "PL",  # ISO kod
        }

        try:
            print("[WFIRMA DEBUG] create contractor payload:", contractor_payload)
        except Exception:
            pass

        new_contractor, resp_add = wfirma_add_contractor(token, contractor_payload)
        try:
            print("[WFIRMA DEBUG] add contractor status:", resp_add.status_code if resp_add else None)
            if resp_add is not None:
                body_txt = resp_add.text or ""
                print("[WFIRMA DEBUG] add contractor body len:", len(body_txt))
                print("[WFIRMA DEBUG] add contractor FULL body:", body_txt)  # pełna odpowiedź
                try:
                    resp_json = resp_add.json()
                    if 'status' in resp_json:
                        print("[WFIRMA DEBUG] status object:", resp_json['status'])
                except:
                    pass
            print("[WFIRMA DEBUG] new contractor:", new_contractor)
        except Exception:
            pass
        if not new_contractor:
            status = resp_add.status_code if resp_add else None
            return jsonify({
                'error': 'Nie udało się dodać kontrahenta w wFirma',
                'status': status,
                'details': resp_add.text if resp_add else 'Brak odpowiedzi',
                'contractor_payload': contractor_payload
            }), status or 502

        contractor = new_contractor
        contractor_id = contractor.get('id')
        contractor_created = True

    if not contractor_id:
        status = resp_find.status_code if resp_find else None
        # Log diagnostyczny z odpowiedzi find (bez wrażliwych danych) – ułatwia debug na Render
        try:
            print("[WFIRMA DEBUG] find response status:", status)
            if resp_find is not None:
                print("[WFIRMA DEBUG] find response body snippet:", (resp_find.text or "")[:500])
            print("[WFIRMA DEBUG] contractor object before failure:", contractor)
        except Exception:
            pass
        return jsonify({
            'error': 'Nie udało się uzyskać ID kontrahenta w wFirma',
            'status': status
        }), status or 502

    # 3) Budujemy payload faktury
    invoice_payload, map_err = build_invoice_payload(invoice_input, contractor_id)
    try:
        print("[WFIRMA DEBUG] invoice payload:", invoice_payload)
        if invoice_payload and 'invoicecontents' in invoice_payload:
            import json as json_lib
            print("[WFIRMA DEBUG] invoicecontents JSON:", json_lib.dumps(invoice_payload['invoicecontents'], ensure_ascii=False))
    except Exception as e:
        print("[WFIRMA DEBUG] log error:", e)
    if map_err:
        return jsonify({'error': map_err}), 400

    invoice, resp_inv = wfirma_create_invoice(token, invoice_payload)
    try:
        print("[WFIRMA DEBUG] invoice create status:", resp_inv.status_code if resp_inv else None)
        if resp_inv is not None:
            body_txt = resp_inv.text or ""
            print("[WFIRMA DEBUG] invoice create body len:", len(body_txt))
            print("[WFIRMA DEBUG] invoice create body snippet 2000:", body_txt[:2000])
        print("[WFIRMA DEBUG] invoice obj:", invoice)
    except Exception:
        pass
    if not invoice:
        status = resp_inv.status_code if resp_inv else None
        error_details = resp_inv.text if resp_inv else 'Brak odpowiedzi'
        
        # Specjalny komunikat dla błędu schematu księgowego
        if 'schematu księgowego' in error_details.lower() or 'schematu ksiegowego' in error_details.lower():
            return jsonify({
                'error': 'Brak konfiguracji schematu księgowego w wFirma',
                'message': 'W panelu wFirma ustaw: Ustawienia → Firma → Księgowość → Schematy księgowe',
                'details': error_details,
                'status': status
            }), 400
        
        return jsonify({
            'error': 'Błąd podczas tworzenia faktury',
            'status': status,
            'details': error_details
        }), status or 502

    # Opcjonalnie wyślij fakturę mailem (żądanie musi zawierać email)
    email_result = None
    if send_email_requested:
        if not email_address or '@' not in email_address:
            return jsonify({
                'error': 'Brak lub niepoprawny email do wysyłki faktury',
                'invoice': invoice
            }), 400

        invoice_id = str(invoice.get('id') or invoice.get('invoice_id') or '')
        if not invoice_id:
            try:
                print("[WFIRMA DEBUG] brak invoice_id, invoice obj:", invoice)
            except Exception:
                pass
            return jsonify({
                'error': 'Brak ID faktury do wysyłki maila',
                'invoice': invoice
            }), 502

        resp_email = wfirma_send_invoice_email(token, invoice_id, email_address)
        try:
            print("[WFIRMA DEBUG] send email status:", resp_email.status_code if resp_email else None)
            if resp_email is not None:
                body_txt = resp_email.text or ""
                print("[WFIRMA DEBUG] send email body len:", len(body_txt))
                print("[WFIRMA DEBUG] send email body snippet 2000:", body_txt[:2000])
        except Exception:
            pass
        if resp_email.status_code != 200:
            return jsonify({
                'error': 'Nie udało się wysłać faktury mailem',
                'status': resp_email.status_code,
                'details': resp_email.text[:500] if resp_email.text else '',
                'invoice': invoice
            }), resp_email.status_code
        try:
            email_result = resp_email.json()
        except Exception:
            email_result = {}

    return jsonify({
        'success': True,
        'contractor_created': contractor_created,
        'contractor': contractor,
        'invoice': invoice,
        'email_sent': bool(email_result),
        'email_response': email_result
    })


# ==================== ENDPOINTY GUS / REGON ====================

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
        # Szczegółowe logi z logowania do GUS
        print(f"[GUS] LOGIN status={login_resp.status_code}")
        login_snippet = (login_resp.text or '')[:500]
        print(f"[GUS] LOGIN body snippet={repr(login_snippet)}")
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
        # Szczegółowe logi z wyszukiwania w GUS
        print(f"[GUS] SEARCH status={search_resp.status_code}")
        search_snippet = (search_resp.text or '')[:800]
        print(f"[GUS] SEARCH body snippet={repr(search_snippet)}")
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
        print("[GUS] Brak sekcji <DaneSzukajPodmiotyResult> w odpowiedzi GUS")
        return jsonify({
            'error': 'Brak danych w odpowiedzi GUS (DaneSzukajPodmiotyResult pusty)'
        }), 404

    decoded_xml = decode_bir_inner_xml(inner_xml)
    decoded_snippet = decoded_xml[:800]
    print(f"[GUS] DECODED inner XML snippet={repr(decoded_snippet)}")
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

    print(f"[GUS] PARSED records={len(data_list)}")
    if data_list:
        # Dla podglądu logujemy tylko pierwszy rekord
        print(f"[GUS] FIRST record={repr(data_list[0])}")

    return jsonify({'data': data_list}), 200


# ==================== ENDPOINTY FAKTURA: PDF i WYSYŁKA MAILEM ====================


@app.route('/api/invoice/<invoice_id>/pdf')
@require_token
def invoice_pdf(token, invoice_id):
    """Pobierz PDF faktury z wFirma (proxy)."""
    resp = wfirma_get_invoice_pdf(token, invoice_id)
    if resp.status_code == 200 and resp.content:
        return Response(resp.content, mimetype='application/pdf')

    return jsonify({
        'error': 'Nie udało się pobrać PDF faktury',
        'status': resp.status_code,
        'details': resp.text[:500] if resp.text else ''
    }), resp.status_code


@app.route('/api/invoice/<invoice_id>/send-email', methods=['POST'])
@require_token
def invoice_send_email(token, invoice_id):
    """Wyślij fakturę mailem przez wFirma."""
    body = request.get_json(silent=True) or {}
    email = (body.get('email') or '').strip()
    if not email or '@' not in email:
        return jsonify({'error': 'Brak lub niepoprawny email'}), 400

    resp = wfirma_send_invoice_email(token, invoice_id, email)
    if resp.status_code == 200:
        try:
            data = resp.json()
        except Exception:
            data = {}
        return jsonify({'success': True, 'wfirma_response': data})

    return jsonify({
        'error': 'Nie udało się wysłać faktury mailem',
        'status': resp.status_code,
        'details': resp.text[:500] if resp.text else ''
    }), resp.status_code


# ==================== START SERWERA ====================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

