"""
Skrypt CLI do sprawdzania kontrahenta po NIP w wFirma.

Scenariusz:
1. Pobiera NIP (z argumentu lub z inputu).
2. Loguje się do wFirma na podstawie zewnętrznego pliku konfiguracyjnego JSON.
3. Sprawdza, czy kontrahent o podanym NIP istnieje.

UWAGA:
- Ten skrypt TYLKO SPRAWDZA istnienie kontrahenta.
- Nie dodaje jeszcze nowego kontrahenta ani nie wystawia faktury.
"""

import sys
from typing import Optional

from wfirma_nip_utils import (
    load_config_from_json,
    create_api_from_config,
    check_contractor_by_nip,
)


def main(config_path: str, nip: Optional[str] = None) -> None:
    # 1. Pobierz NIP
    if not nip:
        nip = input("Podaj NIP kontrahenta: ").strip()

    # 2. Wczytaj konfigurację (klucze API) z pliku JSON
    config = load_config_from_json(config_path)

    # 3. Utwórz klienta API (logowanie)
    api = create_api_from_config(config)

    # 4. Sprawdź kontrahenta
    print(f"Sprawdzam kontrahenta o NIP: {nip}...")
    contractor = check_contractor_by_nip(api, nip)

    if contractor:
        print("\n✅ Kontrahent istnieje w wFirma")
        print(f"  ID: {contractor.get('id')}")
        print(f"  Nazwa: {contractor.get('name')}")
        print(f"  NIP: {contractor.get('tax_id')}")
    else:
        print("\n❌ Kontrahent z takim NIP nie istnieje w wFirma")
        print("   (żeby wystawić fakturę, trzeba go będzie najpierw dodać)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Użycie: python check_nip_cli.py ŚCIEŻKA_DO_CONFIG.json [NIP]")
        print("Przykład: python check_nip_cli.py wfirma_config.json 1234567890")
        sys.exit(1)

    config_path = sys.argv[1]
    nip_arg = sys.argv[2] if len(sys.argv) >= 3 else None

    main(config_path, nip_arg)
