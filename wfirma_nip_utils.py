"""
Funkcje pomocnicze do logowania do wFirma i sprawdzania kontrahenta po NIP.
Uniwersalne – korzystają z przekazanych kluczy lub z pliku konfiguracyjnego JSON.
"""

from typing import Optional, Dict, Any
import json

from wfirma_api import WFirmaAPI


def load_config_from_json(path: str) -> Dict[str, Any]:
    """
    Wczytaj konfigurację z pliku JSON.

    Pozwala wskazać różne konta w zewnętrznych danych.

    Oczekiwany format pliku (przykład):
    {
        "access_key": "TWÓJ_ACCESS_KEY",
        "secret_key": "TWÓJ_SECRET_KEY",
        "app_key": ""
    }
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def create_api_from_config(config: Dict[str, Any]) -> WFirmaAPI:
    """
    Utwórz obiekt WFirmaAPI na podstawie słownika z kluczami API.

    Dzięki temu funkcja jest uniwersalna – możesz przekazać dowolne konto.
    """
    return WFirmaAPI(
        access_key=config["access_key"],
        secret_key=config["secret_key"],
        app_key=config.get("app_key") or None,
    )


def check_contractor_by_nip(api: WFirmaAPI, nip: str) -> Optional[Dict[str, Any]]:
    """
    Sprawdź, czy kontrahent o podanym NIP istnieje w wFirma.

    Zwraca słownik z danymi kontrahenta lub None, jeśli nie istnieje.
    """
    return api.find_contractor_by_nip(nip)
