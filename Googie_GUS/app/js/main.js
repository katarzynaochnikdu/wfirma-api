// ============================================================================
// main.js - Główna orkiestracja widgetu GUS
// ============================================================================
// PageLoad handler, event listeners, główny flow aplikacji
// ============================================================================

// === GŁÓWNY FLOW: POBIERANIE I ZAPIS DANYCH ===

// Główna funkcja wywoływana po kliknięciu "Pobierz dane z GUS"
async function handleFetchData() {
  console.log('[MAIN] handleFetchData() wywołana');
  appendLog('=== KLIKNIĘTO PRZYCISK POBIERZ DANE ===');
  
  hideDataPreview();
  CONFIG.fetchedData = null;
  
  var nipInput = document.getElementById('nipInput');
  var rawNip = (nipInput && nipInput.value) ? nipInput.value.trim() : '';
  var nip = cleanNIP(rawNip);
  
  console.log('[MAIN] NIP:', nip);
  
  // Walidacja NIP
  if (!nip) {
    appendLog('Błąd: NIP pusty');
    showInfoModal('Uwaga', 'Wprowadź numer NIP');
    return;
  }
  
  if (nip.length !== 10) {
    appendLog('Błąd: NIP ma ' + nip.length + ' znaków (oczekiwane 10)');
    showInfoModal('Błąd walidacji', 'NIP musi składać się z 10 cyfr');
    return;
  }
  
  if (!validateNIP(nip)) {
    appendLog('Błąd: NIP ma nieprawidłową sumę kontrolną');
    showInfoModal('Ostrzeżenie', 'NIP ma nieprawidłową sumę kontrolną. Sprawdź wprowadzone cyfry.');
    return;
  }
  
  showSpinner();
  
  // Sprawdź duplikaty w Accounts (ZAWSZE, nawet dla nowego rekordu)
  var isDuplicate = await checkForDuplicateNIP(nip);
  if (isDuplicate) {
    return; // Modal pokazany przez checkForDuplicateNIP
  }
  
  // Pobierz dane z GUS
  var result = await fetchGusDataByNip(nip);
  
  if (!result.success) {
    hideSpinner();
    appendLog('Błąd: ' + result.error);
    showErrorModal(result.error || 'Nie udało się pobrać danych z GUS');
    return;
  }
  
  if (!result.data || result.data.length === 0) {
    hideSpinner();
    appendLog('Brak wyników dla NIP=' + nip);
    showInfoModal('Brak danych', 'Nie znaleziono podmiotu o podanym numerze NIP w bazie GUS');
    return;
  }
  
  var baseData = result.data[0];
  console.log('[MAIN] Dane z GUS:', baseData);
  appendLog('Pobrano dane: ' + (baseData.nazwa || '(brak nazwy)'));
  
  // Jeśli mamy REGON, pobierz pełny raport (KRS + wszystkie inne dane)
  if (baseData.regon) {
    // WAŻNE: Wykryj typ podmiotu i wybierz odpowiedni raport
    var typPodmiotu = baseData.typ || baseData.silosId || '';
    var reportName = '';
    
    if (typPodmiotu === 'F' || typPodmiotu === '1') {
      // Osoba fizyczna - użyj DaneOgolne (najbardziej uniwersalny raport)
      reportName = 'BIR11OsFizycznaDaneOgolne';
      appendLog('[GUS] Wykryto OSOBĘ FIZYCZNĄ (typ=' + typPodmiotu + ') - użyję raportu BIR11OsFizycznaDaneOgolne');
    } else if (typPodmiotu === 'P' || typPodmiotu === '2' || typPodmiotu === '3' || typPodmiotu === '4') {
      // Osoba prawna
      reportName = 'BIR11OsPrawna';
      appendLog('[GUS] Wykryto OSOBĘ PRAWNĄ (typ=' + typPodmiotu + ') - użyję raportu BIR11OsPrawna');
    } else {
      // Domyślnie osoba prawna (jeśli nie wykryto typu)
      reportName = 'BIR11OsPrawna';
      appendLog('[GUS] Nieznany typ podmiotu (' + typPodmiotu + ') - domyślnie BIR11OsPrawna');
    }
    
    appendLog('Pobieram pełny raport dla REGON=' + baseData.regon + ' (raport: ' + reportName + ')');
    var fullReport = await fetchGusFullReport(baseData.regon, reportName);

    // Fallback dla osób fizycznych: spróbuj BIR12OsFizycznaDaneOgolne gdy BIR11 zwróci ErrorCode
    if ((!fullReport || !fullReport.success) && (typPodmiotu === 'F' || typPodmiotu === '1') && reportName === 'BIR11OsFizycznaDaneOgolne') {
      appendLog('[GUS] Fallback → próbuję BIR12OsFizycznaDaneOgolne');
      fullReport = await fetchGusFullReport(baseData.regon, 'BIR12OsFizycznaDaneOgolne');
    }
    
    // Obsłuż błąd z GUS (niewłaściwy raport dla typu podmiotu)
    if (!fullReport.success && fullReport.gusError) {
      appendLog('[GUS] Błąd pełnego raportu - kontynuuję z podstawowymi danymi (bez KRS)');
    }
    
    if (fullReport.success && fullReport.data) {
      var fullData = fullReport.data;
      
      // WAŻNE: Dla osób fizycznych DaneOgolne często NIE zawiera adresu!
      // Pobierz osobny raport Adresy dla typ=F/CEIDG
      if ((typPodmiotu === 'F' || typPodmiotu === '1')) {
        var hasAddress = fullData.fiz_adSiedzMiejscowosc_Nazwa || fullData.fiz_adSiedzUlica_Nazwa || 
                         fullData.fiz_adDzialalnosciMiejscowosc_Nazwa || fullData.fiz_adDzialalnosciUlica_Nazwa || '';
        
        if (!hasAddress) {
          appendLog('[GUS] DaneOgolne nie zawiera adresu - pobieram raport DzialalnoscCeidg');
          
          // Próba 1: BIR11OsFizycznaDzialalnoscCeidg
          var adresyReport = await fetchGusFullReport(baseData.regon, 'BIR11OsFizycznaDzialalnoscCeidg');
          
          // Fallback: BIR12OsFizycznaDzialalnoscCeidg
          if (!adresyReport.success || (adresyReport.data && adresyReport.data.ErrorCode)) {
            appendLog('[GUS] Fallback → BIR12OsFizycznaDzialalnoscCeidg');
            adresyReport = await fetchGusFullReport(baseData.regon, 'BIR12OsFizycznaDzialalnoscCeidg');
          }
          
          // Zmerguj dane z Adresy do fullData
          if (adresyReport.success && adresyReport.data && !adresyReport.data.ErrorCode) {
            Object.keys(adresyReport.data).forEach(function(key) {
              if (!fullData[key]) {
                fullData[key] = adresyReport.data[key];
              }
            });
            appendLog('[GUS] ✓ Dociągnięto adres z raportu Adresy');
          }
        }
      }
      
      // Backend zwraca WSZYSTKIE pola - loguj dla debugowania
      appendLog('[DEBUG] Pełny raport - liczba pól: ' + Object.keys(fullData).length);
      
      // Ekstraktuj KRS z różnych możliwych pól
      var krs = fullData.krs || 
                fullData.praw_numerWRejestrzeEwidencji || 
                fullData.fiz_numerWRejestrzeEwidencji || 
                fullData.praw_Krs || 
                '';
      
      if (krs) {
        baseData.krs = krs;
        appendLog('[GUS] Uzupełniono KRS: ' + krs);
      }
      
      // NOWE: Dodaj wszystkie dodatkowe pola z pełnego raportu do baseData
      // Formy prawne, kontakt, daty itp.
      if (fullData.praw_podstawowaFormaPrawna_Nazwa) {
        baseData.podstawowaFormaPrawna = fullData.praw_podstawowaFormaPrawna_Nazwa;
        appendLog('[GUS] Forma prawna podstawowa: ' + fullData.praw_podstawowaFormaPrawna_Nazwa);
      }
      if (fullData.praw_szczegolnaFormaPrawna_Nazwa) {
        baseData.szczegolnaFormaPrawna = fullData.praw_szczegolnaFormaPrawna_Nazwa;
        appendLog('[GUS] Forma prawna szczególna: ' + fullData.praw_szczegolnaFormaPrawna_Nazwa);
      }
      if (fullData.praw_adresEmail) {
        baseData.email = fullData.praw_adresEmail;
        appendLog('[GUS] Email: ' + fullData.praw_adresEmail);
      }
      if (fullData.praw_numerTelefonu) {
        baseData.telefon = fullData.praw_numerTelefonu;
        appendLog('[GUS] Telefon: ' + fullData.praw_numerTelefonu);
      }
      if (fullData.praw_adresStronyinternetowej || fullData.fiz_adresStronyinternetowej) {
        baseData.website = fullData.praw_adresStronyinternetowej || fullData.fiz_adresStronyinternetowej;
        appendLog('[GUS] WWW: ' + baseData.website);
      }

      // DEBUG: Pokaż wszystkie klucze adresowe z fullData
      var addrKeys = Object.keys(fullData).filter(function(k) { 
        return k.indexOf('adSiedz') !== -1 || k.indexOf('adDzialalnosci') !== -1; 
      });
      if (addrKeys.length > 0) {
        appendLog('[GUS-DEBUG] Klucze adresowe w fullData: ' + addrKeys.join(', '));
        
        // Pokaż wartości kluczowych pól adresowych
        appendLog('[GUS-DEBUG] WARTOŚCI pól adresowych:');
        appendLog('  fiz_adSiedzUlica_Nazwa: "' + (fullData.fiz_adSiedzUlica_Nazwa || '(puste)') + '"');
        appendLog('  fiz_adSiedzMiejscowosc_Nazwa: "' + (fullData.fiz_adSiedzMiejscowosc_Nazwa || '(puste)') + '"');
        appendLog('  fiz_adSiedzKodPocztowy: "' + (fullData.fiz_adSiedzKodPocztowy || '(puste)') + '"');
        appendLog('  fiz_adSiedzNumerNieruchomosci: "' + (fullData.fiz_adSiedzNumerNieruchomosci || '(puste)') + '"');
      } else {
        appendLog('[GUS-DEBUG] BRAK kluczy adresowych w fullData');
      }
      
      // Adres siedziby: dla CEIDG (fiz) może być w fiz_adSiedz* LUB fiz_adDzialalnosci*
      var adr = {
        ulica: fullData.fiz_adSiedzUlica_Nazwa || fullData.fiz_adDzialalnosciUlica_Nazwa || fullData.praw_adSiedzUlica_Nazwa || '',
        nrDomu: fullData.fiz_adSiedzNumerNieruchomosci || fullData.fiz_adDzialalnosciNumerNieruchomosci || fullData.praw_adSiedzNumerNieruchomosci || '',
        nrLokalu: fullData.fiz_adSiedzNumerLokalu || fullData.fiz_adDzialalnosciNumerLokalu || fullData.praw_adSiedzNumerLokalu || '',
        miejscowosc: fullData.fiz_adSiedzMiejscowosc_Nazwa || fullData.fiz_adDzialalnosciMiejscowosc_Nazwa || fullData.praw_adSiedzMiejscowosc_Nazwa || '',
        kod: fullData.fiz_adSiedzKodPocztowy || fullData.fiz_adDzialalnosciKodPocztowy || fullData.praw_adSiedzKodPocztowy || '',
        woj: fullData.fiz_adSiedzWojewodztwo_Nazwa || fullData.fiz_adDzialalnosciWojewodztwo_Nazwa || fullData.praw_adSiedzWojewodztwo_Nazwa || ''
      };
      
      appendLog('[GUS-DEBUG] Ekstraktowane adr: ulica="' + adr.ulica + '" msc="' + adr.miejscowosc + '" kod="' + adr.kod + '"');
      
      if (adr.ulica || adr.nrDomu || adr.miejscowosc || adr.kod) {
        baseData.ulica = adr.ulica || '';
        baseData.nrNieruchomosci = adr.nrDomu || '';
        baseData.nrLokalu = adr.nrLokalu || '';
        baseData.miejscowosc = adr.miejscowosc || '';
        baseData.kodPocztowy = adr.kod || '';
        baseData.wojewodztwo = (adr.woj || '').toLowerCase();
      appendLog('[GUS] Adres (siedziba): ' + [adr.ulica, adr.nrDomu + (adr.nrLokalu ? ('/' + adr.nrLokalu) : ''), adr.miejscowosc, adr.kod].filter(Boolean).join(', '));
      }
      
      // Zapisz pełne dane dla ewentualnego przyszłego użycia
      baseData.fullReportData = fullData;
      
    } else {
      appendLog('[GUS] Pełny raport: brak danych lub błąd');
    }
    
    // ============================================================================
    // POBIERZ KODY PKD (na razie tylko loguj, nie wyświetlaj w UI)
    // ============================================================================
    appendLog('[GUS] Pobieram kody PKD dla REGON=' + baseData.regon);
    
    var pkdReportName = '';
    if (typPodmiotu === 'F' || typPodmiotu === '1') {
      pkdReportName = 'BIR11OsFizycznaPkd';
    } else {
      pkdReportName = 'BIR11OsPrawnaPkd';
    }
    
    var pkdReport = await fetchGusFullReport(baseData.regon, pkdReportName);
    
    if (pkdReport.success && pkdReport.data && pkdReport.data.pkdList) {
      var pkdList = pkdReport.data.pkdList;
      appendLog('[GUS] ========== KODY PKD POBRANE ==========');
      appendLog('[GUS] Liczba kodów PKD: ' + pkdList.length);
      
      for (var i = 0; i < pkdList.length; i++) {
        var pkd = pkdList[i];
        
        // DEBUG: Zaloguj dostępne klucze w obiekcie PKD
        if (i === 0) {
          appendLog('[GUS-DEBUG] Dostępne klucze w pkd[0]: ' + Object.keys(pkd).join(', '));
        }
        
        // Obsłuż warianty nazw kluczy (z i bez podkreśleń) oraz fiz_/praw_
        // Priorytet: fiz_pkd_* (z podkreśleniem) > fiz_pkd* (bez podkreślenia) > praw_pkd*
        var kod = pkd.fiz_pkd_Kod || pkd.fiz_pkdKod || pkd.praw_pkdKod || '';
        var nazwa = pkd.fiz_pkd_Nazwa || pkd.fiz_pkdNazwa || pkd.praw_pkdNazwa || '';
        var przewazajacy = pkd.fiz_pkd_Przewazajace || pkd.fiz_pkdPrzewazajace || pkd.praw_pkdPrzewazajace || '0';
        
        var prefix = przewazajacy === '1' ? '★ [GŁÓWNY]' : '   ';
        appendLog('[GUS] ' + prefix + ' PKD ' + kod + ': ' + nazwa);
      }
      
      appendLog('[GUS] ========================================');
      
      // Zapisz PKD do baseData (na przyszłość)
      baseData.pkdList = pkdList;
    } else {
      appendLog('[GUS] Brak kodów PKD lub błąd pobierania');
    }
  }
  
  // ============================================================================
  // ZAPISZ LUB AKTUALIZUJ REKORD W MODULE GUS (tylko dla Siedziba!)
  // ============================================================================
  if (CONFIG.adresWRekordzie && CONFIG.adresWRekordzie.indexOf('Siedziba') !== -1 && CONFIG.currentRecordId) {
    appendLog('[GUS-MODULE] Firma ma cechę "Siedziba" - zapisuję dane do modułu GUS');
    
    var gusRecordResult = await createOrUpdateGusRecord(CONFIG.currentRecordId, baseData);
    
    if (gusRecordResult.success) {
      if (gusRecordResult.created) {
        appendLog('[GUS-MODULE] ✓ Utworzono nowy rekord GUS: ' + gusRecordResult.recordId);
      } else {
        appendLog('[GUS-MODULE] ✓ Zaktualizowano rekord GUS: ' + gusRecordResult.recordId);
      }
      
      // Zapisz ID rekordu GUS dla przyszłego użytku
      baseData.gusRecordId = gusRecordResult.recordId;
    } else {
      appendLog('[GUS-MODULE] ✗ Błąd zapisu do modułu GUS: ' + (gusRecordResult.error || 'Nieznany błąd'));
    }
  } else {
    if (!CONFIG.adresWRekordzie || CONFIG.adresWRekordzie.indexOf('Siedziba') === -1) {
      appendLog('[GUS-MODULE] Firma NIE ma cechy "Siedziba" - pomijam zapis do modułu GUS');
    }
  }
  
  // Wyświetl podgląd z tabelą porównania
  console.log('[MAIN] Wywołuję showDataPreview');
  showDataPreview(baseData, CONFIG.currentRecordData);
}

// Sprawdza czy w systemie istnieje już rekord z danym NIP (w Accounts)
// Zwraca: true jeśli duplikat (i pokazuje modal), false jeśli OK
async function checkForDuplicateNIP(nip) {
  try {
    // BEZPIECZEŃSTWO: Sanityzacja NIP przed użyciem w Query (ochrona przed injection)
    var safeNip = sanitizeForCriteria(nip);
    var criteria = '(' + CONSTANTS.FIELDS.FIRMA_NIP + ':equals:' + safeNip + ')';
    appendLog('Sprawdzanie duplikatów NIP...');
    
    var results = await searchRecords('Accounts', criteria);
    appendLog('Wynik wyszukiwania: ' + results.length + ' rekordów');
    
    for (var i = 0; i < results.length; i++) {
      var rec = results[i];
      
      // ZMIENIONE: NIE pomijamy obecnego rekordu - sprawdzamy wszystkie
      // Widget może aktualizować dane dla rekordu, na którym jest uruchomiony
      
      // Sprawdź czy to INNY rekord z tym samym NIP (duplikat)
      var isCurrentRecord = CONFIG.currentRecordId && rec.id === CONFIG.currentRecordId;
      
      // Sprawdź cechę Adres_w_rekordzie
      var cecha = (rec.Adres_w_rekordzie || '').toLowerCase();
      var hasSiedziba = cecha.indexOf('siedziba') !== -1;
      
      // DUPLIKAT: Inny rekord z NIP i cechą "Siedziba"
      if (!isCurrentRecord && hasSiedziba) {
        hideSpinner();
        appendLog('DUPLIKAT: Rekord ' + rec.id + ' ma NIP=' + nip + ' i cechę "' + rec.Adres_w_rekordzie + '"');
        showDuplicateModal(rec, nip);
        return true;
      }
      
      // Obecny rekord z NIP - kontynuuj pobieranie danych (nie blokuj)
      if (isCurrentRecord) {
        appendLog('Znaleziono obecny rekord z NIP=' + nip + ' - kontynuuję pobieranie danych');
      }
    }
    
    return false;
  } catch (err) {
    appendLog('Błąd sprawdzania duplikatów: ' + (err && err.message ? err.message : String(err)));
    return false; // Kontynuuj mimo błędu
  }
}

// Główna funkcja zapisu danych
async function handleSaveData() {
  console.log('========================================');
  console.log('[MAIN] handleSaveData() WYWOŁANA');
  console.log('[MAIN] CONFIG.currentRecordId:', CONFIG.currentRecordId);
  console.log('[MAIN] CONFIG.fetchedData:', CONFIG.fetchedData);
  console.log('========================================');
  
  appendLog('[MAIN] === handleSaveData() WYWOŁANA ===');
  
  if (!CONFIG.fetchedData) {
    console.error('[MAIN] BŁĄD: brak CONFIG.fetchedData');
    appendLog('[MAIN] Błąd: brak danych do zapisu');
    return;
  }
  
  // Sprawdź czy zaznaczono jakieś pola
  var checkboxes = document.querySelectorAll('[data-field]');
  console.log('[MAIN] Znaleziono checkboxów:', checkboxes.length);
  
  var hasChecked = false;
  for (var i = 0; i < checkboxes.length; i++) {
    if (checkboxes[i].checked) {
      hasChecked = true;
      break;
    }
  }
  
  console.log('[MAIN] Zaznaczone checkboxy:', hasChecked);
  
  if (!hasChecked) {
    appendLog('[MAIN] Nie zaznaczono żadnych pól');
    showInfoModal('Uwaga', 'Zaznacz przynajmniej jedno pole do zapisu');
    return;
  }
  
  // Wykryj czy to nowy rekord czy istniejący
  var isNewRecord = !CONFIG.currentRecordId;
  console.log('[MAIN] isNewRecord:', isNewRecord);
  appendLog('[MAIN] Typ rekordu: ' + (isNewRecord ? 'NOWY' : 'ISTNIEJĄCY (ID=' + CONFIG.currentRecordId + ')'));
  
  if (isNewRecord) {
    // Nowy rekord - od razu wypełnij pola i zamknij widget (bez modala)
    console.log('[MAIN] Ścieżka: NOWY REKORD - wypełniam pola');
    appendLog('[MAIN] Nowy rekord - wypełniam pola i zamykam widget');
    await performActualSave();
  } else {
    // Istniejący rekord - pytaj o nazwę zwyczajową
    console.log('[MAIN] Ścieżka: ISTNIEJĄCY REKORD - modal z nazwą');
    appendLog('[MAIN] Istniejący rekord - pokazuję modal z nazwą zwyczajową');
    var record = await getRecord(CONFIG.currentEntity, CONFIG.currentRecordId);
    var existingNazwa = (record && record.Nazwa_zwyczajowa) ? record.Nazwa_zwyczajowa : '';
    showNazwaZwyczajowaModal(existingNazwa);
  }
}

// Wykonuje faktyczny zapis danych do CRM
async function performActualSave() {
  console.log('========================================');
  console.log('[MAIN] performActualSave() WYWOŁANA');
  console.log('========================================');
  
  try {
    var isNewRecord = !CONFIG.currentRecordId;
    
    console.log('[MAIN] isNewRecord:', isNewRecord);
    console.log('[MAIN] CONFIG.adresWRekordzie:', CONFIG.adresWRekordzie);
    console.log('[MAIN] CONFIG.fetchedData:', CONFIG.fetchedData);
    
    if (isNewRecord) {
      appendLog('[MAIN] Wypełniam pola w nowym rekordzie...');
    } else {
      appendLog('[MAIN] Zapisuję dane do istniejącego rekordu ' + CONFIG.currentEntity + ' [' + CONFIG.currentRecordId + ']');
    }
    
    // Przygotuj dane do zapisu
    console.log('[MAIN] Wywołuję prepareDataForSave...');
    var prepared = prepareDataForSave(CONFIG.fetchedData, CONFIG.adresWRekordzie);
    console.log('[MAIN] prepared:', prepared);
    
    var apiData = prepared.apiData;
    var selectedCount = prepared.selectedCount;
    
    console.log('[MAIN] apiData:', apiData);
    console.log('[MAIN] selectedCount:', selectedCount);
    
    if (selectedCount === 0) {
      appendLog('[MAIN] Brak zaznaczonych pól');
      showInfoModal('Uwaga', 'Zaznacz przynajmniej jedno pole');
      return;
    }
    
    appendLog('[MAIN] Przygotowano ' + selectedCount + ' pól: ' + Object.keys(apiData).join(', '));
    
    if (isNewRecord) {
      // Nowy rekord - wypełnij pola formularza i zamknij widget (formularz pozostaje otwarty)
      console.log('[MAIN] Wywołuję populateAndClose z danymi:', apiData);
      appendLog('[MAIN] Wywołuję populateAndClose...');
      
      var result = await populateAndClose(apiData);
      
      console.log('[MAIN] populateAndClose result:', result);
      
      if (result.success) {
        appendLog('[MAIN] ✓ Pola wypełnione - widget zamknięty');
        console.log('[MAIN] SUKCES - widget powinien być zamknięty, pola wypełnione');
      } else {
        console.error('[MAIN] BŁĄD populateAndClose:', result.error);
        appendLog('[MAIN] Błąd wypełniania pól: ' + (result.error || 'Nieznany błąd'));
        showErrorModal('Nie udało się wypełnić pól. Sprawdź logi.');
      }
    } else {
      // Istniejący rekord - zapisz przez API
      console.log('[MAIN] Wywołuję updateRecord...');
      appendLog('[MAIN] Wywołuję updateRecord...');
      
      var result = await updateRecord(CONFIG.currentEntity, CONFIG.currentRecordId, apiData);
      
      console.log('[MAIN] updateRecord result:', result);
      
      if (result.success) {
        appendLog('[MAIN] ✓ Dane zapisane pomyślnie!');
        showSuccessModal();
      } else {
        console.error('[MAIN] Błąd updateRecord:', result);
        appendLog('[MAIN] Błąd zapisu: ' + (result.error || JSON.stringify(result.response)));
        showErrorModal('Błąd podczas zapisu danych. Sprawdź logi.');
      }
    }
  } catch (e) {
    var errorMsg = (e && e.message) ? e.message : String(e);
    console.error('[MAIN] WYJĄTEK w performActualSave:', e);
    appendLog('[MAIN] Wyjątek podczas zapisu: ' + errorMsg);
    showErrorModal('Wystąpił błąd: ' + errorMsg);
  }
}

// === INICJALIZACJA WIDGETU (PageLoad) ===

// Główny handler eventu PageLoad
async function onPageLoad(data) {
  console.log('========================================');
  console.log('[MAIN] onPageLoad wywołany');
  console.log('[MAIN] data:', data);
  console.log('========================================');
  
  appendLog('Widget załadowany. Ctx: ' + JSON.stringify(data || {}));
  
  // Loguj URL (debugging)
  logUrlContext();
  
  // Pobierz kontekst rekordu
  var context = await getRecordContext(data);
  CONFIG.currentRecordId = context.id;
  CONFIG.currentEntity = context.entity;
  
  console.log('[MAIN] Kontekst po getRecordContext:', context);
  
  if (CONFIG.currentRecordId) {
    appendLog('Kontekst: ' + CONFIG.currentEntity + ' ID=' + CONFIG.currentRecordId);
  } else {
    appendLog('Uwaga: nie wykryto kontekstu rekordu (może to być nowy rekord)');
  }
  
  // Załaduj konfigurację organizacyjną
  await initConfig();
  
  // Pobierz dane rekordu (jeśli istniejący)
  if (CONFIG.currentRecordId && CONFIG.currentEntity === 'Accounts') {
    var record = await getRecord(CONFIG.currentEntity, CONFIG.currentRecordId);
    
    if (record) {
      appendLog('Rekord pobrany (JSON length: ' + JSON.stringify(record).length + ')');
      
      // Zapisz pełne dane dla porównania
      CONFIG.currentRecordData = {
        Account_Name: record.Account_Name || '',
        Firma_NIP: record.Firma_NIP || '',
        Firma_REGON: record.Firma_REGON || '',
        Firma_KRS: record.Firma_KRS || '',
        Billing_Street: record.Billing_Street || '',
        Billing_Street_Name: record.Billing_Street_Name || '',
        Billing_Building_Number: record.Billing_Building_Number || '',
        Billing_Local_Number: record.Billing_Local_Number || '',
        Billing_City: record.Billing_City || '',
        Billing_Code: record.Billing_Code || '',
        Billing_State: record.Billing_State || '',
        Billing_Powiat: record.Billing_Powiat || '',
        Billing_Gmina: record.Billing_Gmina || '',
        Billing_Country: record.Billing_Country || '',
        Shipping_Street: record.Shipping_Street || '',
        Shipping_Street_Name: record.Shipping_Street_Name || '',
        Shipping_Building_Number: record.Shipping_Building_Number || '',
        Shipping_Local_Number: record.Shipping_Local_Number || '',
        Shipping_City: record.Shipping_City || '',
        Shipping_Code: record.Shipping_Code || '',
        Shipping_State: record.Shipping_State || '',
        Shipping_Powiat: record.Shipping_Powiat || '',
        Shipping_Gmina: record.Shipping_Gmina || '',
        Shipping_Country: record.Shipping_Country || ''
      };
      
      // Odczytaj Firma_NIP (auto-fill input)
      var nipFromRecord = record.Firma_NIP || '';
      if (nipFromRecord) {
        appendLog('Znaleziono Firma_NIP: ' + nipFromRecord);
        var nipInput = document.getElementById('nipInput');
        var nipStatus = document.getElementById('nipStatus');
        if (nipInput) {
          nipInput.value = nipFromRecord;
          updateNipStatus(nipInput, nipStatus);
        }
      } else {
        appendLog('Pole Firma_NIP puste - oczekuję ręcznego wprowadzenia');
      }
      
      // Odczytaj Adres_w_rekordzie
      CONFIG.adresWRekordzie = record.Adres_w_rekordzie || '';
      appendLog('Adres_w_rekordzie: "' + CONFIG.adresWRekordzie + '"');
      
      if (CONFIG.adresWRekordzie === CONSTANTS.ADRES_TYPES.SIEDZIBA_I_FILIA) {
        appendLog('→ Dane będą zapisane do Billing_* i Shipping_*');
      } else if (CONFIG.adresWRekordzie === CONSTANTS.ADRES_TYPES.SIEDZIBA) {
        appendLog('→ Dane będą zapisane tylko do Billing_*');
      } else {
        appendLog('→ Wartość nierozpoznana, domyślnie tylko Billing_*');
      }
    }
  } else {
    // Nowy rekord - odczytaj Adres_w_rekordzie z PageLoad data
    if (data && data.Data && data.Data.Adres_w_rekordzie) {
      CONFIG.adresWRekordzie = data.Data.Adres_w_rekordzie;
      console.log('[MAIN] Adres_w_rekordzie dla nowego rekordu:', CONFIG.adresWRekordzie);
      appendLog('Adres_w_rekordzie (nowy rekord): "' + CONFIG.adresWRekordzie + '"');
    }
  }
  
  // Inicjalizuj UI
  initializeUI();
}

// === INICJALIZACJA UI (Event Handlers) ===

function initializeUI() {
  console.log('[MAIN] initializeUI() wywołana');
  
  // Przycisk "Pobierz dane z GUS"
  var fetchBtn = document.getElementById('fetchBtn');
  if (fetchBtn) {
    fetchBtn.addEventListener('click', function() {
      handleFetchData();
    });
  }
  
  // Auto-formatowanie NIP podczas wpisywania
  var nipInput = document.getElementById('nipInput');
  if (nipInput) {
    nipInput.addEventListener('input', function(e) {
      autoFormatNIP(e);
      var nipStatus = document.getElementById('nipStatus');
      updateNipStatus(nipInput, nipStatus);
    });
  }
  
  // Toggle panelu logów
  var logsToggle = document.getElementById('logsToggle');
  if (logsToggle) {
    logsToggle.addEventListener('click', toggleLogPanel);
  }
  
  // Kopiuj logi
  var logsCopy = document.getElementById('logsCopy');
  if (logsCopy) {
    logsCopy.addEventListener('click', copyLogs);
  }
  
  // Wyczyść logi
  var logsClear = document.getElementById('logsClear');
  if (logsClear) {
    logsClear.addEventListener('click', clearLogs);
  }
  
  // Modal: Nazwa zwyczajowa - dynamiczna zmiana tekstu przycisku
  var nazwaInput = document.getElementById('nazwaZwyczajowaInput');
  if (nazwaInput) {
    nazwaInput.addEventListener('input', function() {
      var val = (nazwaInput.value || '').trim();
      var original = (CONFIG.originalNazwaZwyczajowa || '').trim();
      var saveBtn = document.getElementById('saveNazwaBtn');
      
      if (!saveBtn) return;
      
      if (!val) {
        saveBtn.textContent = 'Zakończ bez nazwy';
      } else if (val === original) {
        saveBtn.textContent = 'Zakończ bez zmiany nazwy';
      } else {
        saveBtn.textContent = 'Zapisz nazwę i Zakończ';
      }
    });
  }
  
  // Modal: Nazwa zwyczajowa - przycisk zapisu (TYLKO dla istniejących rekordów)
  var saveNazwaBtn = document.getElementById('saveNazwaBtn');
  if (saveNazwaBtn) {
    saveNazwaBtn.addEventListener('click', async function() {
      console.log('[MAIN] Kliknięto przycisk w modalu nazwy');
      appendLog('[MAIN] Kliknięto przycisk w modalu nazwy zwyczajowej');
      
      var nazwaValue = (nazwaInput && nazwaInput.value) ? nazwaInput.value.trim() : '';
      var originalValue = (CONFIG.originalNazwaZwyczajowa || '').trim();
      
      // Jeśli zmieniono nazwę i to istniejący rekord, zapisz ją
      if (nazwaValue && nazwaValue !== originalValue && CONFIG.currentRecordId) {
        var nazwaUpper = nazwaValue.toUpperCase();
        appendLog('[MAIN] Zapisuję nazwę zwyczajową: ' + nazwaUpper);
        
        var updateData = {};
        updateData[CONSTANTS.FIELDS.NAZWA_ZWYCZAJOWA] = nazwaUpper;
        
        var result = await updateRecord(CONFIG.currentEntity, CONFIG.currentRecordId, updateData);
        
        if (result.success) {
          appendLog('[MAIN] ✓ Nazwa zwyczajowa zapisana');
        } else {
          appendLog('[MAIN] Błąd zapisu nazwy: ' + (result.error || JSON.stringify(result.response)));
          showErrorModal('Nie udało się zapisać nazwy zwyczajowej');
          return;
        }
      } else if (nazwaValue && nazwaValue === originalValue) {
        appendLog('[MAIN] Nazwa bez zmian, pomijam zapis');
      }
      
      // Ukryj modal
      hideNazwaZwyczajowaModal();
      
      // TERAZ zapisz dane GUS
      await performActualSave();
    });
  }
  
  // Modal: Sukces - przycisk "Zamknij"
  var closeWidgetBtn = document.getElementById('closeWidgetBtn');
  if (closeWidgetBtn) {
    closeWidgetBtn.addEventListener('click', function() {
      hideSuccessModal();
      closeWidget();
    });
  }
  
  // Modal: Sukces - przycisk "Kopiuj logi"
  var copyLogsFromSuccess = document.getElementById('copyLogsFromSuccess');
  if (copyLogsFromSuccess) {
    copyLogsFromSuccess.addEventListener('click', function() {
      copyLogs();
      appendLog('[UI] Logi skopiowane z modala sukcesu');
      
      // Zmień tekst przycisku na chwilę (feedback dla użytkownika)
      var originalText = copyLogsFromSuccess.innerHTML;
      copyLogsFromSuccess.innerHTML = '<svg style="width: 14px; height: 14px; vertical-align: middle; margin-right: 4px;" viewBox="0 0 24 24" fill="currentColor"><path d="M9 16.2L4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4L9 16.2z"/></svg> Skopiowano!';
      copyLogsFromSuccess.style.backgroundColor = '#22c55e';
      
      setTimeout(function() {
        copyLogsFromSuccess.innerHTML = originalText;
        copyLogsFromSuccess.style.backgroundColor = '';
      }, 2000);
    });
  }
  
  // Modalne: przyciski zamykania (X)
  var errorClose = document.getElementById('errorModalClose');
  if (errorClose) errorClose.addEventListener('click', hideErrorModal);
  
  var infoClose = document.getElementById('infoModalClose');
  if (infoClose) infoClose.addEventListener('click', hideInfoModal);
  
  var infoOk = document.getElementById('infoModalOk');
  if (infoOk) infoOk.addEventListener('click', hideInfoModal);
  
  console.log('[MAIN] UI zainicjalizowane');
  appendLog('UI zainicjalizowane - gotowe do pracy');
}

// === REJESTRACJA ZOHO SDK ===

// Rejestruj handler PageLoad PRZED init (best practice SDK 1.2)
ZOHO.embeddedApp.on('PageLoad', onPageLoad);

// Inicjalizacja SDK
try {
  ZOHO.embeddedApp.init();
} catch (e) {
  console.error('[MAIN] SDK init error:', e);
  appendLog('Uwaga: SDK nie zainicjalizowane (tryb lokalny?)');
}
