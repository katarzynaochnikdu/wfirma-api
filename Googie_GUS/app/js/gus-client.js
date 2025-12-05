// ============================================================================
// gus-client.js - Klient API GUS (backend GCP Cloud Run)
// ============================================================================
// Wywołania do backendu Node.js, który komunikuje się z API GUS/REGON
// Wymaga: ORG_CONFIG.GUS_BACKEND_URL i ORG_CONFIG.GUS_API_KEY
// ============================================================================

// Pobiera dane firmy z GUS po numerze NIP
// Parametr: nip (string) - numer NIP (10 cyfr, z lub bez separatorów)
// Zwraca: { success: boolean, data?: array, error?: string }
async function fetchGusDataByNip(nip) {
  try {
    var cleanNip = cleanNIP(nip);
    
    if (cleanNip.length !== 10) {
      return { success: false, error: 'NIP musi składać się z 10 cyfr' };
    }
    
    if (!ORG_CONFIG.GUS_BACKEND_URL) {
      return { success: false, error: 'GUS_BACKEND_URL nie został skonfigurowany. Ustaw zmienną organizacyjną w Zoho.' };
    }
    
    if (!ORG_CONFIG.GUS_API_KEY) {
      return { success: false, error: 'GUS_API_KEY nie został skonfigurowany. Ustaw zmienną organizacyjną w Zoho.' };
    }
    
    if (typeof appendLog === 'function') {
      appendLog('[GUS] Wywołuję /api/gus/name-by-nip dla NIP=' + cleanNip);
    }
    
    // BEZPIECZEŃSTWO: Timeout 30s dla requestu (zapobiega zawieszeniu UI)
    var controller = new AbortController();
    var timeoutId = setTimeout(function() { 
      controller.abort(); 
    }, 30000); // 30 sekund
    
    var resp = await fetch(ORG_CONFIG.GUS_BACKEND_URL + '/api/gus/name-by-nip', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-gus-api-key': ORG_CONFIG.GUS_API_KEY
      },
      body: JSON.stringify({ nip: cleanNip }),
      signal: controller.signal
    });
    
    clearTimeout(timeoutId);
    
    var text = await resp.text();
    
    if (typeof appendLog === 'function') {
      appendLog('[GUS] HTTP ' + resp.status + ' — długość odpowiedzi: ' + text.length + ' znaków');
    }
    
    var data;
    try {
      data = JSON.parse(text);
    } catch (parseErr) {
      return { success: false, error: 'Błąd parsowania odpowiedzi backendu', raw: text };
    }
    
    if (!resp.ok) {
      var errorMsg = (data && data.error) ? data.error : 'Żądanie nie powiodło się';
      if (typeof appendLog === 'function' && data && data.debug) {
        appendLog('[GUS] DEBUG: ' + JSON.stringify(data.debug, null, 2));
      }
      return { success: false, error: errorMsg, httpStatus: resp.status, raw: data };
    }
    
    if (data && Array.isArray(data.data) && data.data.length > 0) {
      if (typeof appendLog === 'function') {
        appendLog('[GUS] Pobrano ' + data.data.length + ' rekordów');
      }
      return { success: true, data: data.data };
    }
    
    return { success: false, error: 'Brak wyników dla podanego NIP' };
  } catch (err) {
    var errorMsg = (err && err.message) ? err.message : String(err);
    
    // Specjalna obsługa timeout (AbortError)
    if (err && err.name === 'AbortError') {
      if (typeof appendLog === 'function') {
        appendLog('[GUS] Timeout: przekroczono limit 30 sekund');
      }
      return { success: false, error: 'Przekroczono limit czasu oczekiwania na odpowiedź z serwera (30s)' };
    }
    
    if (typeof appendLog === 'function') {
      appendLog('[GUS] Wyjątek: ' + errorMsg);
      if (err && err.stack) {
        appendLog('[GUS] Stack: ' + err.stack);
      }
    }
    return { success: false, error: 'Błąd połączenia: ' + errorMsg };
  }
}

// Pobiera pełny raport GUS po numerze REGON (zawiera m.in. KRS + wszystkie inne dane)
// Parametry: 
//   regon (string) - numer REGON (9 lub 14 cyfr)
//   reportName (string, opcjonalny) - nazwa raportu (np. BIR11OsPrawna, BIR11OsFizyczna)
// Zwraca: { success: boolean, data?: object, error?: string }
async function fetchGusFullReport(regon, reportName) {
  try {
    if (!regon || regon.length < 9) {
      return { success: false, error: 'REGON niepoprawny (min. 9 cyfr)' };
    }
    
    if (!ORG_CONFIG.GUS_BACKEND_URL) {
      return { success: false, error: 'GUS_BACKEND_URL nie skonfigurowany' };
    }
    
    if (!ORG_CONFIG.GUS_API_KEY) {
      return { success: false, error: 'GUS_API_KEY nie skonfigurowany' };
    }
    
    if (typeof appendLog === 'function') {
      appendLog('[GUS] Pobieram pełny raport dla REGON=' + regon + (reportName ? ' (raport: ' + reportName + ')' : ''));
    }
    
    // BEZPIECZEŃSTWO: Timeout 30s dla requestu
    var controller = new AbortController();
    var timeoutId = setTimeout(function() { 
      controller.abort(); 
    }, 30000);
    
    // Przygotuj body - dodaj reportName jeśli został przekazany
    var requestBody = { regon: regon };
    if (reportName) {
      requestBody.reportName = reportName;
    }
    
    var resp = await fetch(ORG_CONFIG.GUS_BACKEND_URL + '/api/gus/full-report', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-gus-api-key': ORG_CONFIG.GUS_API_KEY
      },
      body: JSON.stringify(requestBody),
      signal: controller.signal
    });
    
    clearTimeout(timeoutId);
    
    var text = await resp.text();
    var data;
    
    try {
      data = JSON.parse(text);
    } catch (parseErr) {
      return { success: false, error: 'Błąd parsowania odpowiedzi pełnego raportu' };
    }
    
    if (!resp.ok) {
      var errorMsg = (data && data.error) ? data.error : 'Pełny raport nie powiódł się';
      return { success: false, error: errorMsg, httpStatus: resp.status };
    }
    
    if (data && data.data) {
      // SPRAWDŹ CZY GUS ZWRÓCIŁ BŁĄD (ErrorCode)
      if (data.data.ErrorCode) {
        var errorCode = data.data.ErrorCode;
        var errorMsg = data.data.ErrorMessagePl || data.data.ErrorMessageEn || 'Błąd GUS';
        
        if (typeof appendLog === 'function') {
          appendLog('[GUS] ❌ BŁĄD z GUS (kod ' + errorCode + '): ' + errorMsg);
          appendLog('[GUS] Typ podmiotu: ' + (data.data.Typ_podmiotu || '?'));
          appendLog('[GUS] Użyty raport: ' + (data.data.Raport || data.reportName || '?'));
          
          if (data.data.Typ_podmiotu === 'F' && data.data.Raport && data.data.Raport.indexOf('OsPrawna') !== -1) {
            appendLog('[GUS] ⚠️  UWAGA: Użyto raportu dla OSÓB PRAWNYCH, ale to OSOBA FIZYCZNA!');
          }
          if (data.data.Typ_podmiotu === 'P' && data.data.Raport && data.data.Raport.indexOf('OsFizyczna') !== -1) {
            appendLog('[GUS] ⚠️  UWAGA: Użyto raportu dla OSÓB FIZYCZNYCH, ale to OSOBA PRAWNA!');
          }
        }
        
        return { success: false, error: errorMsg, errorCode: errorCode, gusError: true };
      }
      
      // SZCZEGÓŁOWE LOGOWANIE: Co backend zwrócił
      if (typeof appendLog === 'function') {
        appendLog('[GUS] ========== PEŁNY RAPORT POBRANY ==========');
        appendLog('[GUS] Raport: ' + (data.reportName || 'nieznany'));
        appendLog('[GUS] Liczba pól/wpisów: ' + (data.fieldsCount || 0));
        
        // Loguj pierwsze 10 kluczy dla weryfikacji
        var keys = Object.keys(data.data || {});
        if (keys.length > 0) {
          appendLog('[GUS] Pierwsze pola: ' + keys.slice(0, 10).join(', '));
        }
        
        // Loguj pełną strukturę (pierwsze 500 znaków) dla debugowania
        var jsonStr = JSON.stringify(data.data, null, 2);
        appendLog('[GUS] Struktura danych (pierwsze 500 znaków):');
        appendLog(jsonStr.substring(0, 500) + (jsonStr.length > 500 ? '...' : ''));
        
        // Ekstraktuj i loguj kluczowe pola
        var krs = data.data.krs || 
                  data.data.praw_numerWRejestrzeEwidencji || 
                  data.data.fiz_numerWRejestrzeEwidencji || 
                  data.data.fiz_numerwRejestrzeEwidencji || '';
        if (krs) {
          appendLog('[GUS] ✓ KRS: ' + krs);
        }
        
        if (data.data.praw_podstawowaFormaPrawna_Nazwa) {
          appendLog('[GUS] ✓ Forma prawna: ' + data.data.praw_podstawowaFormaPrawna_Nazwa);
        }
        if (data.data.praw_szczegolnaFormaPrawna_Nazwa) {
          appendLog('[GUS] ✓ Szczególna forma: ' + data.data.praw_szczegolnaFormaPrawna_Nazwa);
        }
        if (data.data.praw_adresEmail || data.data.fiz_adresEmail) {
          appendLog('[GUS] ✓ Email: ' + (data.data.praw_adresEmail || data.data.fiz_adresEmail));
        }
        if (data.data.praw_numerTelefonu || data.data.fiz_numerTelefonu) {
          appendLog('[GUS] ✓ Telefon: ' + (data.data.praw_numerTelefonu || data.data.fiz_numerTelefonu));
        }
        
        appendLog('[GUS] ========================================');
      }
      
      return { success: true, data: data.data, reportName: data.reportName, fieldsCount: data.fieldsCount };
    }
    
    return { success: false, error: 'Brak danych w pełnym raporcie' };
  } catch (err) {
    var errorMsg = (err && err.message) ? err.message : String(err);
    
    // Specjalna obsługa timeout
    if (err && err.name === 'AbortError') {
      if (typeof appendLog === 'function') {
        appendLog('[GUS] Timeout pełnego raportu: przekroczono 30 sekund');
      }
      return { success: false, error: 'Timeout pobierania pełnego raportu' };
    }
    
    if (typeof appendLog === 'function') {
      appendLog('[GUS] Błąd pełnego raportu: ' + errorMsg);
    }
    return { success: false, error: errorMsg };
  }
}

