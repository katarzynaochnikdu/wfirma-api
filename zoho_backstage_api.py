"""
Zoho Backstage API - pobieranie szczegółów wydarzeń i klas biletów.
Używa OAuth2 z refresh tokenem (podobnie jak wFirma).
"""
import os
import time
import requests
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

# Preferuj nowe nazwy ENV (ZOHO_MD_BACKSTAGE_*), fallback do BACKSTAGE_*
BACKSTAGE_CLIENT_ID = os.environ.get("ZOHO_MD_BACKSTAGE_CLIENT_ID") or os.environ.get("BACKSTAGE_CLIENT_ID", "")
BACKSTAGE_CLIENT_SECRET = os.environ.get("ZOHO_MD_BACKSTAGE_CLIENT_SECRET") or os.environ.get("BACKSTAGE_CLIENT_SECRET", "")
BACKSTAGE_REFRESH_TOKEN = os.environ.get("ZOHO_MD_BACKSTAGE_REFRESH_TOKEN") or os.environ.get("BACKSTAGE_REFRESH_TOKEN", "")

# Portal ID - można ustawić jako ENV (również ZOHO_MD_BACKSTAGE_PORTAL_ID)
BACKSTAGE_PORTAL_ID = os.environ.get("ZOHO_MD_BACKSTAGE_PORTAL_ID") or os.environ.get("BACKSTAGE_PORTAL_ID", "20101549222")

# Zoho OAuth2 endpoints (EU region)
ZOHO_TOKEN_URL = "https://accounts.zoho.eu/oauth/v2/token"
ZOHO_BACKSTAGE_API_BASE = "https://www.zohoapis.eu/backstage/v3"

# Cache dla access tokena (w pamięci)
_access_token_cache: Dict[str, Any] = {
    "token": None,
    "expires_at": 0,
}


def _log(level: str, message: str, data: Dict[str, Any] = None) -> None:
    """Loguje wiadomość."""
    import datetime
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    prefix = f"[{ts}] [BACKSTAGE_API] [{level}]"
    if data:
        print(f"{prefix} {message} | {data}")
    else:
        print(f"{prefix} {message}")


# ---------------------------------------------------------------------------
# TOKEN MANAGEMENT
# ---------------------------------------------------------------------------


def _get_access_token() -> Optional[str]:
    """
    Pobiera access token z cache lub odświeża z refresh tokena.
    
    Returns:
        Access token lub None jeśli błąd
    """
    global _access_token_cache
    
    # Sprawdź czy mamy ważny token w cache
    now = time.time()
    if _access_token_cache["token"] and _access_token_cache["expires_at"] > now + 60:
        return _access_token_cache["token"]
    
    # Sprawdź konfigurację
    if not BACKSTAGE_CLIENT_ID or not BACKSTAGE_CLIENT_SECRET or not BACKSTAGE_REFRESH_TOKEN:
        _log("ERROR", "Brak konfiguracji Backstage OAuth2 (CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN)")
        return None
    
    # Odśwież token
    _log("INFO", "Odświeżanie access tokena Backstage...")
    
    try:
        response = requests.post(
            ZOHO_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": BACKSTAGE_CLIENT_ID,
                "client_secret": BACKSTAGE_CLIENT_SECRET,
                "refresh_token": BACKSTAGE_REFRESH_TOKEN,
            },
            timeout=15,
        )
        
        if response.status_code != 200:
            _log("ERROR", f"Błąd odświeżania tokena: {response.status_code}", {"body": response.text[:500]})
            return None
        
        data = response.json()
        access_token = data.get("access_token")
        expires_in = data.get("expires_in", 3600)
        
        if not access_token:
            _log("ERROR", "Brak access_token w odpowiedzi", {"response": data})
            return None
        
        # Zapisz w cache
        _access_token_cache["token"] = access_token
        _access_token_cache["expires_at"] = now + expires_in
        
        _log("INFO", f"Access token odświeżony, wygasa za {expires_in}s")
        return access_token
        
    except requests.Timeout:
        _log("ERROR", "Timeout przy odświeżaniu tokena")
        return None
    except Exception as e:
        _log("ERROR", f"Wyjątek przy odświeżaniu tokena: {e}")
        return None


def _make_api_request(
    method: str,
    endpoint: str,
    params: Dict[str, Any] = None,
    json_data: Dict[str, Any] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Wykonuje request do Backstage API.
    
    Args:
        method: HTTP method (GET, POST, etc.)
        endpoint: Endpoint API (np. /portals/{portal_id}/events/{event_id})
        params: Query parameters
        json_data: JSON body (dla POST/PUT)
    
    Returns:
        (data, error) - data jeśli sukces, error jeśli błąd
    """
    access_token = _get_access_token()
    if not access_token:
        return None, "Brak access tokena"
    
    url = f"{ZOHO_BACKSTAGE_API_BASE}{endpoint}"
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Content-Type": "application/json",
    }
    
    try:
        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json=json_data,
            timeout=30,
        )
        
        if response.status_code == 401:
            # Token wygasł - wyczyść cache i spróbuj ponownie
            _log("WARN", "Token wygasł (401), czyszczenie cache...")
            _access_token_cache["token"] = None
            _access_token_cache["expires_at"] = 0
            
            # Ponów request
            access_token = _get_access_token()
            if not access_token:
                return None, "Nie udało się odświeżyć tokena"
            
            headers["Authorization"] = f"Zoho-oauthtoken {access_token}"
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json_data,
                timeout=30,
            )
        
        if response.status_code not in (200, 201, 202):
            _log("ERROR", f"API error: {response.status_code}", {"url": url, "body": response.text[:500]})
            return None, f"API error {response.status_code}: {response.text[:200]}"
        
        return response.json(), None
        
    except requests.Timeout:
        _log("ERROR", f"Timeout przy wywołaniu {url}")
        return None, "Timeout"
    except Exception as e:
        _log("ERROR", f"Wyjątek przy wywołaniu API: {e}")
        return None, str(e)


# ---------------------------------------------------------------------------
# EVENT API
# ---------------------------------------------------------------------------


def fetch_event_details(event_id: str, portal_id: str = None) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Pobiera szczegóły wydarzenia z Backstage API.
    
    Args:
        event_id: ID wydarzenia w Backstage
        portal_id: ID portalu (domyślnie z ENV)
    
    Returns:
        (event_data, error)
    """
    portal_id = portal_id or BACKSTAGE_PORTAL_ID
    
    _log("INFO", f"Pobieranie szczegółów wydarzenia", {"event_id": event_id, "portal_id": portal_id})
    
    data, error = _make_api_request(
        method="GET",
        endpoint=f"/portals/{portal_id}/events/{event_id}",
    )
    
    if error:
        return None, error
    
    _log("INFO", f"Pobrano szczegóły wydarzenia: {data.get('name', '?')}")
    return data, None


def fetch_ticket_classes(event_id: str, portal_id: str = None) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """
    Pobiera klasy biletów dla wydarzenia z Backstage API.
    
    Args:
        event_id: ID wydarzenia w Backstage
        portal_id: ID portalu (domyślnie z ENV)
    
    Returns:
        (ticket_classes, error)
    """
    portal_id = portal_id or BACKSTAGE_PORTAL_ID
    
    _log("INFO", f"Pobieranie klas biletów", {"event_id": event_id, "portal_id": portal_id})
    
    data, error = _make_api_request(
        method="GET",
        endpoint=f"/portals/{portal_id}/events/{event_id}/ticket_classes",
    )
    
    if error:
        return None, error
    
    ticket_classes = data.get("ticket_classes", [])
    _log("INFO", f"Pobrano {len(ticket_classes)} klas biletów")
    return ticket_classes, None


def fetch_event_with_tickets(event_id: str, portal_id: str = None) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Pobiera szczegóły wydarzenia wraz z klasami biletów.
    
    Args:
        event_id: ID wydarzenia w Backstage
        portal_id: ID portalu (domyślnie z ENV)
    
    Returns:
        (combined_data, error) - dane wydarzenia z kluczem 'ticket_classes'
    """
    portal_id = portal_id or BACKSTAGE_PORTAL_ID
    
    # Pobierz szczegóły wydarzenia
    event_data, error = fetch_event_details(event_id, portal_id)
    if error:
        return None, error
    
    # Pobierz klasy biletów
    ticket_classes, error = fetch_ticket_classes(event_id, portal_id)
    if error:
        # Kontynuuj bez biletów
        _log("WARN", f"Nie udało się pobrać klas biletów: {error}")
        ticket_classes = []
    
    # Połącz dane
    event_data["ticket_classes"] = ticket_classes
    
    return event_data, None


# ---------------------------------------------------------------------------
# ATTENDEES API
# ---------------------------------------------------------------------------


def fetch_attendees(
    event_id: str,
    portal_id: str = None,
    page: int = 1,
    per_page: int = 500,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Pobiera listę uczestników z Backstage API.
    
    Args:
        event_id: ID wydarzenia w Backstage
        portal_id: ID portalu (domyślnie z ENV)
        page: Numer strony (domyślnie 1)
        per_page: Liczba rekordów na stronę (domyślnie 500)
    
    Returns:
        (data, error) gdzie data zawiera {"attendees": [...], "pagination": {...}}
    """
    portal_id = portal_id or BACKSTAGE_PORTAL_ID
    
    _log("INFO", "Pobieranie uczestników", {"event_id": event_id, "portal_id": portal_id, "page": page})
    
    data, error = _make_api_request(
        method="GET",
        endpoint=f"/portals/{portal_id}/events/{event_id}/attendees",
        params={"page": page, "per_page": per_page},
    )
    
    if error:
        return None, error
    
    return {
        "attendees": data.get("attendees", []),
        "pagination": data.get("pagination", {}),
    }, None


def fetch_attendee_details(
    event_id: str,
    attendee_id: str,
    portal_id: str = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Pobiera szczegóły pojedynczego uczestnika z Backstage API.
    
    Args:
        event_id: ID wydarzenia w Backstage
        attendee_id: ID uczestnika w Backstage
        portal_id: ID portalu (domyślnie z ENV)
    
    Returns:
        (attendee_data, error)
    """
    portal_id = portal_id or BACKSTAGE_PORTAL_ID
    
    _log("INFO", "Pobieranie szczegółów uczestnika", {
        "event_id": event_id,
        "attendee_id": attendee_id,
        "portal_id": portal_id,
    })
    
    data, error = _make_api_request(
        method="GET",
        endpoint=f"/portals/{portal_id}/events/{event_id}/attendees/{attendee_id}",
    )
    
    if error:
        return None, error
    
    return data, None


# ---------------------------------------------------------------------------
# DATA MAPPING - konwersja danych Backstage na format lokalny
# ---------------------------------------------------------------------------


def map_event_to_local(backstage_event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Mapuje dane wydarzenia z Backstage na format lokalny (pg_storage).
    
    Args:
        backstage_event: Dane z API Backstage
    
    Returns:
        Dict w formacie do zapisania w events.data
    """
    # #region agent log
    import json as _json
    try:
        with open(r'c:\Users\kochn\.cursor\Medidesk\wFirma\APIV1\.cursor\debug.log', 'a', encoding='utf-8') as _f:
            _f.write(_json.dumps({"location":"zoho_backstage_api.py:map_event_to_local","message":"Raw backstage_event keys","data":{"keys":list(backstage_event.keys()),"venue_raw":backstage_event.get("venue"),"venue_type":str(type(backstage_event.get("venue"))),"location_raw":backstage_event.get("location"),"address_raw":backstage_event.get("address")},"timestamp":__import__('time').time(),"sessionId":"debug-session","hypothesisId":"H1,H2,H3,H4"}) + '\n')
    except: pass
    # #endregion
    venue = backstage_event.get("venue") or {}
    
    # #region agent log
    try:
        with open(r'c:\Users\kochn\.cursor\Medidesk\wFirma\APIV1\.cursor\debug.log', 'a', encoding='utf-8') as _f:
            _f.write(_json.dumps({"location":"zoho_backstage_api.py:venue_parsed","message":"Venue object details","data":{"venue_keys":list(venue.keys()) if isinstance(venue, dict) else "NOT_DICT","venue_name":venue.get("name") if isinstance(venue, dict) else str(venue)[:100],"venue_city":venue.get("city") if isinstance(venue, dict) else None,"venue_street":venue.get("street") if isinstance(venue, dict) else None,"venue_address":venue.get("address") if isinstance(venue, dict) else None},"timestamp":__import__('time').time(),"sessionId":"debug-session","hypothesisId":"H1,H2"}) + '\n')
    except: pass
    # #endregion
    
    # Buduj adres lokalizacji
    venue_parts = []
    if venue.get("name"):
        venue_parts.append(venue["name"])
    if venue.get("street"):
        venue_parts.append(venue["street"])
    venue_address = ", ".join(venue_parts) if venue_parts else ""
    
    location_full = venue_address
    if venue.get("city"):
        if location_full:
            location_full += f", {venue['city']}"
        else:
            location_full = venue["city"]
    
    # Parsuj daty
    start_time = backstage_event.get("start_time", "")
    end_time = backstage_event.get("end_time", "")
    
    # Wyciągnij datę i godzinę
    event_date = ""
    event_time = ""
    event_end_date = ""
    event_end_time = ""
    
    if start_time:
        # Format: 2026-02-05T09:00:00Z
        if "T" in start_time:
            date_part, time_part = start_time.split("T")
            event_date = date_part
            event_time = time_part.replace("Z", "")[:5]  # HH:MM
    
    if end_time:
        if "T" in end_time:
            date_part, time_part = end_time.split("T")
            event_end_date = date_part
            event_end_time = time_part.replace("Z", "")[:5]
    
    result = {
        # Podstawowe dane
        "backstage_event_id": backstage_event.get("id"),
        "backstage_portal_id": backstage_event.get("space", {}).get("id"),
        "backstage_website_url": backstage_event.get("website_url"),
        
        # Opis i podsumowanie
        "event_description": backstage_event.get("description", ""),
        "event_summary": backstage_event.get("summary", ""),
        
        # Lokalizacja - KANONICZNE NAZWY (V1 format: event_location_*)
        "event_location_place": venue.get("name", ""),
        "event_location_address": venue.get("street", ""),
        "event_location_city": venue.get("city", ""),
        "event_location_state": venue.get("state", ""),
        "event_location_country": venue.get("country", ""),
        "event_location_zip": "",  # Backstage nie zwraca kodu pocztowego bezpośrednio
        "location": location_full,  # Pełny adres jako fallback
        
        # Aliasy dla kompatybilności z V2 (eventLocation, eventCity, eventAddress)
        "eventLocation": venue.get("name", ""),
        "eventCity": venue.get("city", ""),
        "eventAddress": venue.get("street", ""),
        
        # Daty i godziny - KANONICZNE (event_date, event_time)
        "event_date": event_date,
        "event_time": event_time,
        "event_end_date": event_end_date,
        "event_end_time": event_end_time,
        
        # Daty i godziny - FORMAT FORMULARZA (event_date_time = YYYY-MM-DDTHH:MM:SS)
        "event_date_time": f"{event_date}T{event_time}:00" if event_date and event_time else "",
        "event_end_date_time": f"{event_end_date}T{event_end_time}:00" if event_end_date and event_end_time else "",
        
        # Daty i godziny - ALIASY V2 (eventDate, eventTime)
        "eventDate": event_date,
        "eventTime": event_time,
        "eventEndDate": event_end_date,
        "eventEndTime": event_end_time,
        
        "timezone": backstage_event.get("timezone", "Europe/Warsaw"),
        
        # Status
        "backstage_status": backstage_event.get("status_string", ""),
        "event_type": backstage_event.get("event_type_string", ""),
        
        # Obrazki
        "thumbnail_url": backstage_event.get("thumbnail_url", ""),
        
        # Metadane
        "backstage_synced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    
    # #region agent log
    try:
        with open(r'c:\Users\kochn\.cursor\Medidesk\wFirma\APIV1\.cursor\debug.log', 'a', encoding='utf-8') as _f:
            _result = result  # reference for logging
            _f.write(_json.dumps({"location":"zoho_backstage_api.py:map_result","message":"Final mapped location values","data":{"event_location_place":result.get("event_location_place"),"event_location_address":result.get("event_location_address"),"event_location_city":result.get("event_location_city"),"location_full":result.get("location"),"eventLocation":result.get("eventLocation"),"eventCity":result.get("eventCity"),"eventAddress":result.get("eventAddress")},"timestamp":__import__('time').time(),"sessionId":"debug-session","hypothesisId":"H1,H2,H3"}) + '\n')
    except: pass
    # #endregion
    
    return result


def map_ticket_class_to_local(ticket_class: Dict[str, Any]) -> Dict[str, Any]:
    """
    Mapuje klasę biletu z Backstage na format lokalny.
    
    Args:
        ticket_class: Dane klasy biletu z API Backstage
    
    Returns:
        Dict w formacie do zapisania w event_ticket_classes.data
    """
    return {
        "ticket_class_id": ticket_class.get("id"),
        "ticket_name": ticket_class.get("name", ""),
        "ticket_description": ticket_class.get("description", ""),
        "ticket_type": ticket_class.get("ticket_class_type_string", ""),
        "price": ticket_class.get("amount", 0),
        "currency": ticket_class.get("currency_code", "PLN"),
        "quantity": ticket_class.get("quantity", 0),
        "sold": ticket_class.get("sold", 0),
        "hidden": ticket_class.get("hidden", False),
        "status": ticket_class.get("status_string", ""),
        "min_buy": ticket_class.get("minimum_buying_limit", 1),
        "max_buy": ticket_class.get("maximum_buying_limit", 10),
        "sales_start_date": ticket_class.get("sales_start_date", ""),
        "sales_end_date": ticket_class.get("sales_end_date", ""),
    }


# ---------------------------------------------------------------------------
# HIGH-LEVEL FUNCTIONS
# ---------------------------------------------------------------------------


def sync_event_from_backstage(event_id: str, portal_id: str = None) -> Dict[str, Any]:
    """
    Pobiera i synchronizuje dane wydarzenia z Backstage.
    
    Args:
        event_id: ID wydarzenia w Backstage
        portal_id: ID portalu (opcjonalnie)
    
    Returns:
        Dict z:
        - success: bool
        - event_data: zmapowane dane wydarzenia (jeśli sukces)
        - ticket_classes: zmapowane klasy biletów (jeśli sukces)
        - error: komunikat błędu (jeśli błąd)
    """
    _log("INFO", f"Synchronizacja wydarzenia z Backstage", {"event_id": event_id})
    
    # Pobierz dane
    backstage_data, error = fetch_event_with_tickets(event_id, portal_id)
    if error:
        return {"success": False, "error": error}
    
    # Mapuj dane
    event_data = map_event_to_local(backstage_data)
    
    ticket_classes = []
    for tc in backstage_data.get("ticket_classes", []):
        ticket_classes.append(map_ticket_class_to_local(tc))
    
    _log("INFO", f"Dane zsynchronizowane", {
        "event_name": backstage_data.get("name"),
        "venue": event_data.get("venue_name"),
        "ticket_classes_count": len(ticket_classes),
    })
    
    return {
        "success": True,
        "event_name": backstage_data.get("name", ""),
        "event_data": event_data,
        "ticket_classes": ticket_classes,
        "raw_backstage_data": backstage_data,
    }


def is_backstage_configured() -> bool:
    """Sprawdza czy Backstage API jest skonfigurowane."""
    return bool(BACKSTAGE_CLIENT_ID and BACKSTAGE_CLIENT_SECRET and BACKSTAGE_REFRESH_TOKEN)
