// ============================================================================
// validators.js - Walidacja i formatowanie danych
// ============================================================================
// Uniwersalne funkcje walidacji NIP - można użyć dla dowolnego pola input
// ============================================================================

// Walidacja NIP - algorytm kontrolny (cyfra kontrolna)
// Zwraca: true jeśli NIP poprawny, false jeśli błędny
function validateNIP(nip) {
  var clean = cleanNIP(nip);
  if (clean.length !== 10) return false;
  
  var weights = [6, 5, 7, 2, 3, 4, 5, 6, 7];
  var sum = 0;
  
  for (var i = 0; i < 9; i++) {
    sum += parseInt(clean[i]) * weights[i];
  }
  
  var checksum = sum % 11;
  if (checksum === 10) checksum = 0;
  
  return checksum === parseInt(clean[9]);
}

// Formatowanie NIP - dodaje myślniki w formacie XXX-XXX-XX-XX
// Zwraca: sformatowany NIP jako string
function formatNIP(nip) {
  var clean = cleanNIP(nip);
  if (clean.length <= 3) return clean;
  if (clean.length <= 6) return clean.slice(0, 3) + '-' + clean.slice(3);
  if (clean.length <= 8) return clean.slice(0, 3) + '-' + clean.slice(3, 6) + '-' + clean.slice(6);
  return clean.slice(0, 3) + '-' + clean.slice(3, 6) + '-' + clean.slice(6, 8) + '-' + clean.slice(8, 10);
}

// Czyszczenie NIP - usuwa wszystkie znaki niebędące cyframi
// Zwraca: same cyfry jako string
function cleanNIP(nip) {
  return String(nip || '').replace(/[^0-9]/g, '');
}

// Formatowanie kodu pocztowego (dodaje myślnik jeśli brak)
// Parametr: zipCode (string) - kod pocztowy (z lub bez myślnika)
// Zwraca: string w formacie XX-XXX
function formatZipCode(zipCode) {
  if (!zipCode) return '';
  var clean = String(zipCode).replace(/[^0-9]/g, '');
  if (clean.length !== 5) return zipCode; // Jeśli nie 5 cyfr, zwróć bez zmian
  return clean.slice(0, 2) + '-' + clean.slice(2, 5);
}

// Aktualizacja statusu walidacji NIP w UI
// Parametry:
//   inputElement - element <input> z NIPem
//   statusElement - element wyświetlający status (np. <span>)
function updateNipStatus(inputElement, statusElement) {
  if (!statusElement) return;
  
  var nip = inputElement ? inputElement.value : '';
  var clean = cleanNIP(nip);
  
  if (!clean) {
    statusElement.textContent = '';
    statusElement.style.color = '#666';
    return;
  }
  
  if (clean.length !== 10) {
    statusElement.textContent = '(niepełny)';
    statusElement.style.color = '#ff6600';
    return;
  }
  
  if (validateNIP(clean)) {
    statusElement.textContent = '✓ prawidłowy';
    statusElement.style.color = '#28a745';
  } else {
    statusElement.textContent = '✗ błędna suma kontrolna';
    statusElement.style.color = '#dc3545';
  }
}

// Auto-formatowanie NIP podczas wpisywania (event handler)
// Użycie: nipInput.addEventListener('input', autoFormatNIP);
function autoFormatNIP(event) {
  var input = event.target;
  var cursorPos = input.selectionStart;
  var oldValue = input.value;
  var newValue = formatNIP(oldValue);
  
  if (newValue !== oldValue) {
    input.value = newValue;
    // Przywróć pozycję kursora (uwzględniając dodane myślniki)
    var diff = newValue.length - oldValue.length;
    input.setSelectionRange(cursorPos + diff, cursorPos + diff);
  }
}

// ============================================================================
// OCHRONA PRZED XSS (Cross-Site Scripting)
// ============================================================================

// Escape HTML - zapobiega wykonaniu złośliwego kodu JavaScript
// Konwertuje znaki specjalne na encje HTML
// Parametr: unsafe - nieoczyszczony tekst (może zawierać tagi HTML/JS)
// Zwraca: bezpieczny string z zaescapowanymi znakami specjalnymi
function escapeHtml(unsafe) {
  if (!unsafe) return '';
  return String(unsafe)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// Sanityzacja dla Zoho CRM search criteria
// Usuwa znaki specjalne, które mogą być użyte do injection w Query
// Parametr: value - wartość do użycia w searchRecord criteria
// Zwraca: bezpieczny string (tylko cyfry i litery)
function sanitizeForCriteria(value) {
  if (!value) return '';
  // Usuń wszystko oprócz cyfr, liter i bezpiecznych znaków
  return String(value).replace(/[^a-zA-Z0-9]/g, '');
}

