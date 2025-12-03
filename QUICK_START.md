# Szybki start - Klucze API vs OAuth 2.0

## ✅ Masz już klucze API? Możesz działać OD RAZU!

Jeśli masz już **Access Key** i **Secret Key** (zwykłe klucze API), **NIE POTRZEBUJESZ** weryfikacji firmy ani OAuth 2.0!

### Co możesz zrobić OD RAZU z kluczami API:

✅ Wyszukać kontrahenta po NIP  
✅ Dodać nowego kontrahenta  
✅ Wystawić fakturę  
✅ Wysłać fakturę e-mailem  
✅ Oznaczyć fakturę jako opłaconą  

### Jak użyć:

1. **Masz już klucze w `example_usage.py`:**
   ```python
   ACCESS_KEY = "bc7696aa5d1b68faf5aa36f6b5d6e632"
   SECRET_KEY = "b3b1df3eb40b161088f0b6cb7bca9486"
   ```

2. **APP_KEY jest opcjonalne** - możesz zostawić puste:
   ```python
   APP_KEY = ""  # Opcjonalne
   ```

3. **Odkomentuj linię `main()` w `example_usage.py`** i uruchom!

4. **Pamiętaj:** Testy zaczynamy od 1 rekordu!

---

## Kiedy potrzebujesz OAuth 2.0?

OAuth 2.0 jest potrzebne TYLKO jeśli:

- ❌ Nie masz jeszcze kluczy API
- ❌ Potrzebujesz bardziej zaawansowanego zarządzania uprawnieniami
- ❌ Tworzysz aplikację produkcyjną dla innych firm
- ❌ Potrzebujesz pełnego dostępu do wszystkich zasobów API

### Jeśli potrzebujesz OAuth 2.0:

1. **Zweryfikuj firmę** (przelew weryfikacyjny - kilka dni)
2. **Zarejestruj aplikację OAuth 2.0** w panelu
3. **Zaimplementuj flow OAuth 2.0** w kodzie

---

## Podsumowanie:

| Masz | Możesz działać? | Weryfikacja potrzebna? |
|------|----------------|------------------------|
| ✅ Access Key + Secret Key | ✅ **TAK - OD RAZU!** | ❌ NIE |
| ❌ Tylko OAuth 2.0 | ⚠️ Po weryfikacji | ✅ TAK (przelew) |

---

## Rekomendacja:

**Jeśli masz już klucze API:**
- ✅ Używaj ich do testów i rozwoju
- ✅ Nie potrzebujesz weryfikacji firmy
- ✅ Możesz działać od razu
- ⚠️ OAuth 2.0 rozważ dopiero gdy będziesz potrzebować zaawansowanych funkcji

**Jeśli nie masz kluczy API:**
- Najpierw wygeneruj klucze API (szybko, bez weryfikacji)
- Albo przejdź przez weryfikację i OAuth 2.0 (dłużej, ale bardziej profesjonalnie)

