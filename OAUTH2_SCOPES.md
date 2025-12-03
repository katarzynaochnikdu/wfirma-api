# OAuth 2.0 - Wymagane Scopes dla operacji na fakturach i kontrahentach

## Scopes potrzebne do Twojego przypadku użycia

Aby wykonać następujące operacje:
1. ✅ Wyszukać kontrahenta po NIPie
2. ✅ Dodać kontrahenta jeśli nie istnieje
3. ✅ Wygenerować fakturę
4. ✅ Wysłać fakturę do klienta

**Potrzebujesz następujących scopes:**

```
invoices-read,invoices-write,contractors-read,contractors-write
```

## Szczegółowy opis scopes

### `invoices-read`
- **Co umożliwia:** Odczyt faktur z systemu
- **Potrzebne do:** Sprawdzania statusu faktur, pobierania danych faktur

### `invoices-write`
- **Co umożliwia:** Tworzenie i modyfikacja faktur
- **Potrzebne do:** 
  - Wystawiania nowych faktur
  - Wysyłania faktur e-mailem
  - Modyfikacji istniejących faktur

### `contractors-read`
- **Co umożliwia:** Wyszukiwanie i odczyt danych kontrahentów
- **Potrzebne do:**
  - Wyszukiwania kontrahenta po NIPie
  - Sprawdzania czy kontrahent istnieje w systemie
  - Pobierania danych kontrahenta

### `contractors-write`
- **Co umożliwia:** Tworzenie i modyfikacja kontrahentów
- **Potrzebne do:**
  - Dodawania nowych kontrahentów
  - Aktualizacji danych kontrahentów

## Konfiguracja w panelu wFirma

Podczas rejestracji aplikacji OAuth 2.0 w panelu wFirma:

1. Przejdź do: **Ustawienia → Bezpieczeństwo → Aplikacje OAuth 2.0**
2. Kliknij **"Dodaj"**
3. W polu **"Zakres dostępu"** (Scopes) wprowadź:
   ```
   invoices-read,invoices-write,contractors-read,contractors-write
   ```
4. Wypełnij pozostałe wymagane pola:
   - Nazwa aplikacji
   - Redirect URI
   - **Adres IP klienta** (wymagane - zobacz sekcję poniżej)

## Przykład użycia w kodzie

```python
# Podczas autoryzacji OAuth 2.0
scopes = "invoices-read,invoices-write,contractors-read,contractors-write"

# URL autoryzacji
auth_url = f"https://api2.wfirma.pl/oauth2/authorize?client_id={client_id}&redirect_uri={redirect_uri}&scope={scopes}&response_type=code"
```

## Minimalne scopes (jeśli potrzebujesz tylko podstawowych operacji)

Jeśli chcesz ograniczyć uprawnienia do minimum:

- **Tylko odczyt:** `invoices-read,contractors-read`
- **Tylko zapis:** `invoices-write,contractors-write`
- **Pełny dostęp (zalecany dla Twojego przypadku):** `invoices-read,invoices-write,contractors-read,contractors-write`

## Adres IP klienta - jak wypełnić?

Pole **"Adres IP klienta"** jest **wymagane** w formularzu OAuth 2.0. To adres IP serwera/aplikacji, z którego będą przychodzić żądania do API wFirma.

### Dla testów lokalnych (development):

Jeśli testujesz aplikację na lokalnym komputerze:

1. **Sprawdź swój publiczny adres IP:**
   - Otwórz w przeglądarce: https://whatismyipaddress.com/ lub https://ipinfo.io/
   - Skopiuj wyświetlony adres IP (np. `185.123.45.67`)

2. **Wpisz ten adres IP w formularzu wFirma**

⚠️ **Uwaga:** Jeśli Twój adres IP się zmienia (dynamiczne IP), będziesz musiał aktualizować to pole w panelu wFirma.

### Dla aplikacji produkcyjnej (na serwerze):

1. **Sprawdź adres IP serwera:**
   - W panelu administracyjnym hostingu/serwera
   - Lub skontaktuj się z dostawcą hostingu

2. **Wpisz adres IP serwera w formularzu**

### Alternatywy (jeśli dostępne):

- Niektóre systemy pozwalają na użycie `0.0.0.0` (dowolne IP) - **sprawdź w dokumentacji wFirma**
- Możesz też spróbować `127.0.0.1` dla testów lokalnych (ale może nie działać)

### Przykład:

```
Adres IP klienta: 185.123.45.67
```

### Co jeśli nie masz stałego IP?

- Jeśli masz dynamiczne IP, będziesz musiał aktualizować to pole za każdym razem gdy IP się zmieni
- Rozważ użycie serwera ze stałym IP dla aplikacji produkcyjnej
- Skontaktuj się z wFirma, czy można użyć zakresu IP lub wildcard

## Uwagi

- ⚠️ **Zasada najmniejszych uprawnień:** Używaj tylko tych scopes, które są rzeczywiście potrzebne
- ✅ **Dla Twojego przypadku:** Wszystkie 4 scopes są wymagane, aby wykonać pełny proces (wyszukanie → dodanie → faktura → wysyłka)
- 🔒 **Bezpieczeństwo:** OAuth 2.0 pozwala użytkownikowi zobaczyć, do jakich zasobów aplikacja będzie miała dostęp przed autoryzacją
- 🌐 **Adres IP:** Jest używany do dodatkowej weryfikacji bezpieczeństwa - żądania z innych IP mogą być odrzucone

