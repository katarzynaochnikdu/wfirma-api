"""
Moduł do komunikacji z API wFirma
Dokumentacja: https://doc.wfirma.pl/
"""

import requests
import json
import base64
from datetime import date
from typing import Dict, Optional, Any, List


class WFirmaAPI:
    """
    Klasa do komunikacji z API wFirma
    """
    
    BASE_URL = "https://api2.wfirma.pl"
    
    def __init__(self, access_key: str, secret_key: str, app_key: Optional[str] = None):
        """
        Inicjalizacja połączenia z API wFirma
        
        Args:
            access_key: Access Key z wFirma (uzyskany w Ustawienia > Bezpieczeństwo > Klucze API)
            secret_key: Secret Key z wFirma (uzyskany w Ustawienia > Bezpieczeństwo > Klucze API)
            app_key: App Key z wFirma (uzyskany przez kontakt z wFirma)
        """
        self.access_key = access_key
        self.secret_key = secret_key
        self.app_key = app_key
        self.session = requests.Session()
        self._setup_authentication()
    
    def _setup_authentication(self):
        """
        Konfiguracja autoryzacji w API wFirma używając kluczy API
        """
        # API wFirma v2 używa Basic Auth z Access Key i Secret Key
        credentials = f"{self.access_key}:{self.secret_key}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        
        self.session.headers.update({
            'Authorization': f'Basic {encoded_credentials}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })
        
        # App Key jest przekazywany jako parametr lub nagłówek (zależnie od wersji API)
        # Sprawdź dokumentację API dla dokładnego formatu
        if self.app_key:
            self.session.headers.update({
                'X-App-Key': self.app_key
            })
    
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
    
    def create_invoice(self, invoice_data: Dict[str, Any], paid: bool = False, 
                      payment_date: Optional[str] = None) -> Dict:
        """
        Wystawienie faktury w wFirma
        
        Args:
            invoice_data: Dane faktury zgodne z formatem API wFirma
                Przykład struktury:
                {
                    "invoice": {
                        "contractor": {
                            "name": "Nazwa kontrahenta",
                            "tax_id": "NIP",
                            "email": "email@example.com"
                        },
                        "invoicecontent": [
                            {
                                "name": "Nazwa pozycji",
                                "count": 1,
                                "price": 100.00,
                                "vat": 23
                            }
                        ],
                        "paymenttype": "transfer",
                        "date": "2024-01-01"
                    }
                }
            paid: Czy faktura jest już opłacona (domyślnie False)
            payment_date: Data płatności w formacie YYYY-MM-DD (wymagane jeśli paid=True)
        
        Returns:
            Odpowiedź z API zawierająca utworzoną fakturę
        """
        # Jeśli faktura ma być oznaczona jako opłacona
        if paid:
            if 'invoice' not in invoice_data:
                invoice_data['invoice'] = {}
            
            invoice_data['invoice']['paid'] = 1
            
            if payment_date:
                invoice_data['invoice']['paymentdate'] = payment_date
            else:
                # Jeśli nie podano daty płatności, użyj daty faktury lub dzisiejszej daty
                invoice_data['invoice']['paymentdate'] = invoice_data.get('invoice', {}).get('date', str(date.today()))
        
        endpoint = "invoices/add"
        return self._make_request('POST', endpoint, invoice_data)
    
    def mark_invoice_as_paid(self, invoice_id: int, payment_date: Optional[str] = None, 
                            payment_method: Optional[str] = None) -> Dict:
        """
        Oznaczenie istniejącej faktury jako opłaconej
        
        Args:
            invoice_id: ID faktury w systemie wFirma
            payment_date: Data płatności w formacie YYYY-MM-DD (domyślnie dzisiejsza data)
            payment_method: Metoda płatności: "cash", "transfer", "compensation" (opcjonalnie)
        
        Returns:
            Odpowiedź z API potwierdzająca zmianę
        """
        update_data = {
            "invoice": {
                "paid": 1
            }
        }
        
        if payment_date:
            update_data["invoice"]["paymentdate"] = payment_date
        else:
            update_data["invoice"]["paymentdate"] = str(date.today())
        
        if payment_method:
            update_data["invoice"]["paymentmethod"] = payment_method
        
        endpoint = f"invoices/{invoice_id}"
        return self._make_request('PUT', endpoint, update_data)
    
    def send_invoice_email(self, invoice_id: int, email: str, subject: Optional[str] = None, 
                          message: Optional[str] = None) -> Dict:
        """
        Wysyłka faktury e-mailem do klienta
        
        Args:
            invoice_id: ID faktury w systemie wFirma
            email: Adres e-mail odbiorcy
            subject: Temat wiadomości (opcjonalnie)
            message: Treść wiadomości (opcjonalnie)
        
        Returns:
            Odpowiedź z API potwierdzająca wysyłkę
        """
        endpoint = f"invoices/{invoice_id}/send"
        
        send_data = {
            "invoice": {
                "send": {
                    "email": email
                }
            }
        }
        
        if subject:
            send_data["invoice"]["send"]["subject"] = subject
        if message:
            send_data["invoice"]["send"]["message"] = message
        
        return self._make_request('POST', endpoint, send_data)
    
    def get_invoice(self, invoice_id: int) -> Dict:
        """
        Pobranie danych faktury
        
        Args:
            invoice_id: ID faktury w systemie wFirma
        
        Returns:
            Dane faktury
        """
        endpoint = f"invoices/{invoice_id}"
        return self._make_request('GET', endpoint)
    
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
    
    def create_contractor(self, contractor_data: Dict[str, Any]) -> Dict:
        """
        Dodanie nowego kontrahenta do systemu
        
        Args:
            contractor_data: Dane kontrahenta zgodne z formatem API wFirma
                Przykład struktury:
                {
                    "contractor": {
                        "name": "Nazwa firmy",
                        "tax_id": "1234567890",
                        "email": "email@example.com",
                        "street": "ul. Przykładowa 1",
                        "zip": "00-000",
                        "city": "Warszawa"
                    }
                }
        
        Returns:
            Odpowiedź z API zawierająca utworzonego kontrahenta
        """
        endpoint = "contractors/add"
        return self._make_request('POST', endpoint, contractor_data)
    
    def find_or_create_contractor(self, nip: str, contractor_data: Dict[str, Any]) -> Dict:
        """
        Wyszukanie kontrahenta po NIPie lub utworzenie nowego jeśli nie istnieje
        
        Args:
            nip: Numer NIP kontrahenta
            contractor_data: Dane kontrahenta do utworzenia (jeśli nie istnieje)
                Musi zawierać klucz "contractor" z danymi
        
        Returns:
            Dane kontrahenta (istniejącego lub nowo utworzonego)
        """
        # Próba znalezienia kontrahenta
        existing = self.find_contractor_by_nip(nip)
        
        if existing:
            return existing
        
        # Jeśli nie znaleziono, utwórz nowego
        create_response = self.create_contractor(contractor_data)
        contractor = create_response.get('contractors', [{}])[0].get('contractor', {})
        
        return contractor


def create_and_send_invoice(api: WFirmaAPI, contractor_data: Dict, items: list, 
                            recipient_email: str) -> Dict:
    """
    Funkcja pomocnicza do utworzenia i wysłania faktury w jednym kroku
    
    Args:
        api: Instancja WFirmaAPI
        contractor_data: Dane kontrahenta
        items: Lista pozycji na fakturze
        recipient_email: Adres e-mail odbiorcy faktury
    
    Returns:
        Odpowiedź z API zawierająca informacje o utworzonej i wysłanej fakturze
    """
    # Przygotowanie danych faktury
    invoice_data = {
        "invoice": {
            "contractor": contractor_data,
            "invoicecontent": items,
            "paymenttype": "transfer",
            "date": None  # Będzie ustawiona na dzisiejszą datę przez system
        }
    }
    
    # Utworzenie faktury
    create_response = api.create_invoice(invoice_data)
    
    # Pobranie ID utworzonej faktury
    invoice_id = create_response.get('invoices', [{}])[0].get('invoice', {}).get('id')
    
    if not invoice_id:
        raise ValueError("Nie udało się utworzyć faktury lub pobrać jej ID")
    
    # Wysłanie faktury e-mailem
    send_response = api.send_invoice_email(invoice_id, recipient_email)
    
    return {
        "created": create_response,
        "sent": send_response,
        "invoice_id": invoice_id
    }

