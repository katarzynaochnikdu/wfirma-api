# Różnice między Kluczami API a OAuth 2.0 w wFirma

## Porównanie metod autoryzacji

### Klucze API (Access Key + Secret Key)

#### Zalety:
- ✅ **Szybkie uzyskanie dostępu** - dostępne natychmiast po zalogowaniu
- ✅ **Brak weryfikacji firmy** - nie wymaga dodatkowych kroków weryfikacyjnych
- ✅ **Prosta konfiguracja** - wystarczy wygenerować klucze w panelu wFirma
- ✅ **Dobre do testów** - idealne do szybkiego prototypowania
- ✅ **Wystarczające dla prostych integracji** - dla większości podstawowych przypadków użycia

#### Wady:
- ⚠️ **Ograniczony zakres dostępu** - mogą mieć mniej uprawnień niż OAuth 2.0
- ⚠️ **Mniej elastyczne zarządzanie** - trudniejsze precyzyjne określenie uprawnień
- ⚠️ **Mniej bezpieczne** - klucze są statyczne i długoterminowe
- ⚠️ **Trudniejsze zarządzanie** - w przypadku wycieku trzeba wygenerować nowe klucze

#### Jak uzyskać:
1. Zaloguj się do wFirma
2. Przejdź do: **Ustawienia → Bezpieczeństwo → Klucze API**
3. Kliknij **"Dodaj"** i wygeneruj klucze
4. Zapisz **Access Key** i **Secret Key** (Secret Key wyświetlany tylko raz!)

---

### OAuth 2.0

#### Zalety:
- ✅ **Bardziej bezpieczne** - standardowy protokół autoryzacji używany przez większość API
- ✅ **Elastyczne zarządzanie uprawnieniami** - możesz precyzyjnie określić zakres dostępu (scopes)
- ✅ **Lepsze dla aplikacji produkcyjnych** - profesjonalne podejście do integracji
- ✅ **Szerszy zakres dostępu** - dostęp do większej liczby zasobów i funkcji
- ✅ **Możliwość odwołania dostępu** - łatwiejsze zarządzanie uprawnieniami
- ✅ **Tokeny czasowe** - automatyczne wygasanie tokenów zwiększa bezpieczeństwo

#### Wady:
- ⚠️ **Wymaga weryfikacji firmy** - konieczny jednorazowy przelew weryfikacyjny
- ⚠️ **Bardziej skomplikowana konfiguracja** - wymaga:
  - Rejestracji aplikacji w panelu
  - Określenia redirect_uri (adres zwrotny)
  - Określenia zakresów dostępu (scopes)
  - Określenia adresu IP klienta (opcjonalnie)
- ⚠️ **Dłuższy proces wdrożenia** - więcej kroków do konfiguracji
- ⚠️ **Wymaga implementacji flow OAuth** - redirect, token exchange itp.

#### Jak uzyskać:
1. **Weryfikacja firmy** (jednorazowo):
   - Wykonaj przelew weryfikacyjny w celu potwierdzenia danych firmy
   - Czekaj na potwierdzenie weryfikacji

2. **Rejestracja aplikacji OAuth 2.0**:
   - Zaloguj się do wFirma
   - Przejdź do: **Ustawienia → Bezpieczeństwo → Aplikacje OAuth 2.0**
   - Kliknij **"Dodaj"** i wypełnij formularz:
     - Nazwa aplikacji
     - Zakres dostępu (scopes) - określ, do czego aplikacja ma dostęp
     - Redirect URI - adres, na który wFirma przekieruje użytkownika po autoryzacji
     - Adres IP klienta (opcjonalnie)
   - Otrzymasz **Client ID** i **Client Secret**

3. **Implementacja flow OAuth 2.0**:
   - Przekieruj użytkownika do strony autoryzacji wFirma
   - Użytkownik autoryzuje aplikację
   - Otrzymujesz kod autoryzacyjny
   - Wymień kod na token dostępu
   - Używaj tokenu do żądań API

---

## Tabela porównawcza

| Cecha | Klucze API | OAuth 2.0 |
|-------|------------|-----------|
| **Czas uzyskania dostępu** | Natychmiastowy | Wymaga weryfikacji firmy |
| **Weryfikacja firmy** | ❌ Nie wymagana | ✅ Wymagana (przelew) |
| **Złożoność konfiguracji** | ⭐ Prosta | ⭐⭐⭐ Zaawansowana |
| **Zakres dostępu** | Ograniczony | Pełny |
| **Zarządzanie uprawnieniami** | Podstawowe | Zaawansowane (scopes) |
| **Bezpieczeństwo** | Podstawowe | Wysokie |
| **Dla aplikacji produkcyjnych** | ⚠️ Może być niewystarczające | ✅ Zalecane |
| **Dla testów/prototypów** | ✅ Idealne | ⚠️ Zbyt skomplikowane |

---

## Którą metodę wybrać?

### Wybierz **Klucze API**, jeśli:
- ✅ Tworzysz prostą integrację wewnętrzną
- ✅ Potrzebujesz szybkiego dostępu do testów
- ✅ Nie potrzebujesz zaawansowanego zarządzania uprawnieniami
- ✅ Twoja firma nie jest jeszcze zweryfikowana w wFirma
- ✅ Tworzysz prototyp lub MVP

### Wybierz **OAuth 2.0**, jeśli:
- ✅ Tworzysz aplikację produkcyjną
- ✅ Integracja jest zewnętrzna (dla innych firm)
- ✅ Potrzebujesz precyzyjnego zarządzania uprawnieniami
- ✅ Zależy Ci na wysokim poziomie bezpieczeństwa
- ✅ Twoja firma jest zweryfikowana w wFirma
- ✅ Potrzebujesz pełnego dostępu do zasobów API

---

## Obecna implementacja

Obecny kod w tym projekcie używa **Kluczy API** (Access Key + Secret Key), co jest odpowiednie dla:
- Szybkiego startu
- Testów i prototypów
- Prostych integracji wewnętrznych

Jeśli potrzebujesz OAuth 2.0, kod będzie wymagał rozszerzenia o implementację flow OAuth 2.0.

