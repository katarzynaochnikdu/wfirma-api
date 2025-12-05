"""
Klasa do komunikacji z API wFirma używając OAuth 2.0
"""

import requests
import json
from datetime import datetime, timedelta
from typing import Dict, Optional, Any


class WFirmaOAuth2API:
    """
    Klasa do komunikacji z API wFirma używając OAuth 2.0
    """
    
    BASE_URL = "https://api2.wfirma.pl"
    TOKEN_URL = "https://api2.wfirma.pl/oauth2/token"
    
    def __init__(self, client_id: str, client_secret: str):
        """
        Inicjalizacja połączenia z API wFirma używając OAuth 2.0
        
        Args:
            client_id: Client ID z wFirma OAuth 2.0
            client_secret: Client Secret z wFirma OAuth 2.0
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = None
        self.token_expires_at = None
        self.session = requests.Session()
        
        # Pobierz token przy inicjalizacji
        self._get_access_token()
    
    def _get_access_token(self):
        """
        Pobierz token dostępu OAuth 2.0 używając Client Credentials Flow
        """
        data = {
            'grant_type': 'client_credentials',
            'client_id': self.client_id,
            'client_secret': self.client_secret
        }
        
        response = requests.post(self.TOKEN_URL, data=data)
        response.raise_for_status()
        
        token_data = response.json()
        self.access_token = token_data['access_token']
        
        # Oblicz kiedy token wygaśnie (domyślnie 3600 sekund = 1 godzina)
        expires_in = token_data.get('expires_in', 3600)
        self.token_expires_at = datetime.now() + timedelta(seconds=expires_in - 60)  # 60s bufora
        
        # Ustaw token w sesji
        self.session.headers.update({
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })
    
    def _ensure_valid_token(self):
        """
        Sprawdź czy token jest ważny, jeśli nie - pobierz nowy
        """
        if not self.access_token or datetime.now() >= self.token_expires_at:
            self._get_access_token()
    
    def _make_request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Dict:
        """
        Wykonanie żądania do API
        
        Args:
            method: Metoda HTTP (GET, POST, PUT, DELETE)
            endpoint: Endpoint API
            data: Dane do wysłania
            
        Returns:
            Odpowiedź z API jako słownik
        """
        self._ensure_valid_token()
        
        url = f"{self.BASE_URL}/{endpoint}"
        
        if method.upper() == 'GET':
            response = self.session.get(url, params=data)
        elif method.upper() == 'POST':
            response = self.session.post(url, json=data)
        elif method.upper() == 'PUT':
            response = self.session.put(url, json=data)
        elif method.upper() == 'DELETE':
            response = self.session.delete(url)
        else:
            raise ValueError(f"Nieobsługiwana metoda HTTP: {method}")
        
        response.raise_for_status()
        return response.json()
    
    def find_contractor_by_nip(self, nip: str) -> Optional[Dict]:
        """
        Wyszukanie kontrahenta po NIPie
        
        Args:
            nip: Numer NIP kontrahenta (bez myślników i spacji)
        
        Returns:
            Dane kontrahenta jeśli znaleziony, None jeśli nie istnieje
        """
        endpoint = "contractors/find"
        
        # Czyszczenie NIP z myślników i spacji
        clean_nip = nip.replace("-", "").replace(" ", "")
        
        search_params = {
            "conditions": {
                "contractor": {
                    "tax_id": clean_nip
                }
            }
        }
        
        try:
            response = self._make_request('GET', endpoint, search_params)
            contractors = response.get('contractors', [])
            
            if contractors and len(contractors) > 0:
                return contractors[0].get('contractor')
            return None
        except Exception:
            # Jeśli nie znaleziono, API może zwrócić błąd
            return None

