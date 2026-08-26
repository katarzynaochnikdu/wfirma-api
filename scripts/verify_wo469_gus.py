"""
Weryfikacja WO-469 / BUG-056 w mikroserwisie GUS (wFirma/APIV1).

Uruchamiana recznie, poza repo: mikroserwis nie ma infrastruktury pytest, a zakladanie
jej w trakcie awarii P0 rozdeloby zakres. Skrypt sprawdza DOKLADNIE to, co zmienil WO-469:

  1. ponowienia logowania przy bledzie transportowym (timeout),
  2. brak ponowien przy 401 (powtorka nic nie zmieni),
  3. sukces za druga proba konczy petle,
  4. awaria lacznosci  -> HTTP 503 + nip_status "niedostepny",
  5. brak firmy w GUS  -> HTTP 200 + nip_status "niepoprawny"  (zachowanie sprzed WO).

Uruchomienie (z katalogu mikroserwisu):
  .venv\\Scripts\\python.exe scripts\\verify_wo469_gus.py

Wymaga REGON_API_KEY_TOKEN w srodowisku — bez niego testy endpointu sa POMIJANE,
a testy samych ponowien i tak sie wykonuja.
"""
import os
import sys
from unittest.mock import patch

import requests

# Skrypt siedzi w scripts/, a app.py w katalogu wyzej — dopisz go do sciezki importu.
APIV1_DIR = os.environ.get("APIV1_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, APIV1_DIR)

import app


FAILURES = []
PASSES = []


def check(name, condition, detail=""):
    if condition:
        PASSES.append(name)
        print(f"  [OK]   {name}")
    else:
        FAILURES.append(f"{name} :: {detail}")
        print(f"  [FAIL] {name} :: {detail}")


class FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


print("\n=== 1. post_soap_gus_retry: ponowienia przy timeoucie ===")
calls = {"n": 0}


def always_timeout(*a, **kw):
    calls["n"] += 1
    raise requests.exceptions.ReadTimeout("read timeout")


with patch.object(app.requests, "post", side_effect=always_timeout):
    with patch.object(app.time, "sleep"):  # nie czekamy naprawde
        raised = None
        try:
            app.post_soap_gus_retry("host.test", "<envelope/>")
        except Exception as e:  # noqa: BLE001
            raised = e

check("proba wykonana GUS_LOGIN_ATTEMPTS razy",
      calls["n"] == app.GUS_LOGIN_ATTEMPTS,
      f"oczekiwano {app.GUS_LOGIN_ATTEMPTS}, bylo {calls['n']}")
check("po wyczerpaniu prob leci wyjatek",
      isinstance(raised, requests.exceptions.ReadTimeout),
      f"dostano {type(raised).__name__ if raised else 'brak wyjatku'}")


print("\n=== 2. post_soap_gus_retry: 401 NIE jest ponawiane ===")
calls_401 = {"n": 0}


def unauthorized(*a, **kw):
    calls_401["n"] += 1
    return FakeResponse(401, "Unauthorized")


with patch.object(app.requests, "post", side_effect=unauthorized):
    with patch.object(app.time, "sleep"):
        resp = app.post_soap_gus_retry("host.test", "<envelope/>")

check("401 zwrocone po JEDNEJ probie", calls_401["n"] == 1, f"prob: {calls_401['n']}")
check("401 zwrocone bez zmian", resp.status_code == 401, f"status {resp.status_code}")


print("\n=== 3. post_soap_gus_retry: sukces za druga proba konczy petle ===")
calls_mix = {"n": 0}


def fail_then_ok(*a, **kw):
    calls_mix["n"] += 1
    if calls_mix["n"] == 1:
        raise requests.exceptions.ConnectionError("zerwane polaczenie")
    return FakeResponse(200, "<ZalogujResult>SID123</ZalogujResult>")


with patch.object(app.requests, "post", side_effect=fail_then_ok):
    with patch.object(app.time, "sleep"):
        resp = app.post_soap_gus_retry("host.test", "<envelope/>")

check("zatrzymano sie na drugiej probie", calls_mix["n"] == 2, f"prob: {calls_mix['n']}")
check("zwrocono udana odpowiedz", resp.status_code == 200, f"status {resp.status_code}")


print("\n=== 4. validate-nip: awaria lacznosci -> 503 niedostepny ===")
app.app.config["TESTING"] = True
client = app.app.test_client()
HEADERS = {"X-API-Key": app.REGON_API_KEY_TOKEN or "brak-tokenu"}
NIP_OK = "1111111111"  # syntetyczny, poprawna suma kontrolna

if not app.REGON_API_KEY_TOKEN:
    print("  [SKIP] brak REGON_API_KEY_TOKEN w srodowisku — pomijam testy endpointu")
else:
    with patch.object(app, "gus_lookup_nip",
                      return_value=(None, "Błąd komunikacji z GUS podczas logowania: timeout")):
        r = client.post("/api/gus/validate-nip", json={"nip": NIP_OK}, headers=HEADERS)
    body = r.get_json() or {}
    check("HTTP 503 przy awarii lacznosci", r.status_code == 503, f"status {r.status_code}")
    check("nip_status == 'niedostepny'", body.get("nip_status") == "niedostepny", str(body)[:160])
    check("gus_data puste", body.get("gus_data") is None, str(body)[:160])

    print("\n=== 5. validate-nip: brak firmy -> 200 niepoprawny (bez zmian) ===")
    with patch.object(app, "gus_lookup_nip", return_value=([], None)):
        r2 = client.post("/api/gus/validate-nip", json={"nip": NIP_OK}, headers=HEADERS)
    body2 = r2.get_json() or {}
    check("HTTP 200 gdy rejestr nie zna NIP-u", r2.status_code == 200, f"status {r2.status_code}")
    check("nip_status == 'niepoprawny'", body2.get("nip_status") == "niepoprawny", str(body2)[:160])

    print("\n=== 6. validate-nip: firma znaleziona -> 200 poprawny ===")
    record = {"nazwa": "FIRMA TESTOWA", "regon": "000000000", "ulica": "Testowa",
              "nrNieruchomosci": "1", "kodPocztowy": "00-001", "miejscowosc": "Warszawa",
              "wojewodztwo": "MAZOWIECKIE"}
    with patch.object(app, "gus_lookup_nip", return_value=([record], None)):
        r3 = client.post("/api/gus/validate-nip", json={"nip": NIP_OK}, headers=HEADERS)
    body3 = r3.get_json() or {}
    check("HTTP 200 przy sukcesie", r3.status_code == 200, f"status {r3.status_code}")
    check("nip_status == 'poprawny'", body3.get("nip_status") == "poprawny", str(body3)[:160])
    check("gus_data niesie nazwe",
          (body3.get("gus_data") or {}).get("name") == "FIRMA TESTOWA", str(body3)[:160])


print("\n" + "=" * 62)
print(f"ZALICZONE: {len(PASSES)}   NIEZALICZONE: {len(FAILURES)}")
for f in FAILURES:
    print("  - " + f)
sys.exit(1 if FAILURES else 0)
