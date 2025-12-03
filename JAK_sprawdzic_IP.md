# Jak sprawdzić adres IP klienta dla OAuth 2.0 w wFirma

## Szybki sposób - sprawdź swoje IP

### Metoda 1: Strony internetowe

1. Otwórz w przeglądarce jedną z tych stron:
   - https://whatismyipaddress.com/
   - https://ipinfo.io/
   - https://www.whatismyip.com/
   - https://ifconfig.me/

2. Skopiuj wyświetlony adres IP (np. `185.123.45.67`)

3. Wklej ten adres IP w pole **"Adres IP klienta"** w formularzu wFirma

### Metoda 2: Z linii poleceń (Windows PowerShell)

```powershell
(Invoke-WebRequest -Uri "https://ifconfig.me/ip").Content
```

### Metoda 3: Z linii poleceń (Linux/Mac)

```bash
curl ifconfig.me
```

lub

```bash
curl ipinfo.io/ip
```

## Dla testów lokalnych

Jeśli testujesz aplikację na swoim komputerze (`localhost:8000`):

1. **Sprawdź swój publiczny adres IP** (używając jednej z metod powyżej)
2. **Wpisz ten adres IP** w formularzu wFirma

⚠️ **Uwaga:** 
- Jeśli masz dynamiczne IP (większość domowych połączeń), adres IP może się zmieniać
- Za każdym razem gdy IP się zmieni, będziesz musiał zaktualizować to pole w panelu wFirma
- Dla aplikacji produkcyjnej lepiej użyć serwera ze stałym IP

## Dla aplikacji na serwerze

Jeśli Twoja aplikacja działa na serwerze:

1. **Sprawdź adres IP serwera:**
   - W panelu administracyjnym hostingu (cPanel, Plesk, itp.)
   - Lub skontaktuj się z dostawcą hostingu

2. **Wpisz adres IP serwera** w formularzu wFirma

## Przykład wypełnienia formularza

```
Nazwa aplikacji: API_V1
Zakres (scope): invoices-read,invoices-write,contractors-read,contractors-write
Adres zwrotny (redirect_uri): http://localhost:8000
Adres IP klienta: 185.123.45.67  ← Twój publiczny adres IP
```

## Co jeśli nie działa?

1. **Sprawdź czy IP jest poprawne:**
   - Upewnij się, że wpisałeś pełny adres IP (4 liczby oddzielone kropkami)
   - Nie używaj `localhost` ani `127.0.0.1` - musisz użyć publicznego IP

2. **Jeśli masz dynamiczne IP:**
   - Skontaktuj się z wFirma, czy można użyć zakresu IP
   - Rozważ użycie serwera ze stałym IP dla aplikacji produkcyjnej

3. **Dla testów:**
   - Możesz spróbować użyć `0.0.0.0` (jeśli wFirma to pozwala) - oznacza "dowolne IP"
   - Ale lepiej użyć konkretnego IP dla bezpieczeństwa

## Ważne uwagi

- ✅ Adres IP jest używany do dodatkowej weryfikacji bezpieczeństwa
- ⚠️ Żądania z innych IP mogą być odrzucone przez wFirma
- 🔄 Jeśli IP się zmienia, musisz aktualizować to pole w panelu
- 🌐 Dla aplikacji produkcyjnej użyj serwera ze stałym IP

