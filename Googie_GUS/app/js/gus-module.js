// ============================================================================
// gus-module.js - Obsługa modułu GUS (custom module w Zoho CRM)
// ============================================================================
// Funkcje do tworzenia i aktualizacji rekordów w module GUS
// Każda firma z cechą "Siedziba" ma DOKŁADNIE JEDEN rekord w GUS
// ============================================================================

// Nazwa modułu GUS (API name - pobierana z CONSTANTS)
var GUS_MODULE_NAME = 'GUS'; // Domyślna wartość, może być nadpisana przez CONSTANTS.MODULES.GUS

// Inicjalizacja nazwy modułu (jeśli CONSTANTS jest dostępny)
if (typeof CONSTANTS !== 'undefined' && CONSTANTS.MODULES && CONSTANTS.MODULES.GUS) {
  GUS_MODULE_NAME = CONSTANTS.MODULES.GUS;
}

// Naprawia powiązanie rekordu GUS z firmą macierzystą (Account)
// Użycie: gdy rekord GUS istnieje ale nie ma powiązania z firmą
// Parametry:
//   gusRecordId - ID rekordu w module GUS
//   accountId - ID rekordu w Accounts (firma "matka")
// Zwraca: { success: boolean }
async function fixGusRecordLink(gusRecordId, accountId) {
  try {
    if (!gusRecordId || !accountId) {
      return { success: false, error: 'Brak gusRecordId lub accountId' };
    }
    
    appendLog('[GUS-MODULE] Naprawiam powiązanie lookup: GUS[' + gusRecordId + '] → Accounts[' + accountId + ']');
    
    var updateData = {
      id: gusRecordId,
      Firma: { id: accountId }  // Lookup – pojedyncze powiązanie
    };
    
    var result = await updateRecord(GUS_MODULE_NAME, gusRecordId, updateData);
    
    if (result.success) {
      appendLog('[GUS-MODULE] ✓ Powiązanie naprawione!');
      return { success: true };
    } else {
      appendLog('[GUS-MODULE] ✗ Błąd naprawy powiązania: ' + (result.error || 'Nieznany błąd'));
      return { success: false, error: result.error };
    }
  } catch (err) {
    appendLog('[GUS-MODULE] Wyjątek: ' + (err && err.message ? err.message : String(err)));
    return { success: false, error: err.message };
  }
}

// Szuka istniejący rekord GUS dla danej firmy (Account)
// Parametry:
//   accountId - ID rekordu Accounts
//   nip - numer NIP (opcjonalnie, dla wyszukiwania)
// Zwraca: obiekt rekordu GUS lub null
async function findGusRecordForAccount(accountId, nip) {
  try {
    if (!accountId) {
      appendLog('[GUS-MODULE] Brak accountId - nie mogę szukać rekordu GUS');
      return null;
    }
    
    // Lookup Firma nie jest wyszukiwalny w criteria, dlatego korzystamy z NIP
    // Pole Name w module GUS przechowuje NIP bez separatorów
    // WAŻNE: NIP w module GUS jest BEZ myślników (tylko cyfry)
    if (nip) {
      var nipClean = cleanNIP(nip); // Usuń myślniki i spacje
      var criteria = '(Name:equals:' + sanitizeForCriteria(nipClean) + ')';
      appendLog('[GUS-MODULE] Szukam rekordu GUS po NIP: ' + nipClean);
      
      var results = await searchRecords(GUS_MODULE_NAME, criteria);
      
      if (results.length > 0) {
        appendLog('[GUS-MODULE] Znaleziono ' + results.length + ' rekordów GUS z NIP=' + nip);
        return results[0]; // Zwróć pierwszy (powinien być tylko jeden)
      }
    }
    
    appendLog('[GUS-MODULE] Nie znaleziono rekordu GUS dla firmy ' + accountId);
    return null;
  } catch (err) {
    appendLog('[GUS-MODULE] Błąd szukania: ' + (err && err.message ? err.message : String(err)));
    return null;
  }
}

// Mapuje dane z GUS API na pola modułu GUS (Zoho CRM)
// Parametr: gusData - pełne dane z GUS (baseData + fullReportData + pkdList)
// Zwraca: obiekt z polami do zapisu w module GUS
function buildGusModuleData(gusData, accountId) {
  if (!gusData) return {};
  
  var data = {};
  var fullData = gusData.fullReportData || {};
  var pkdList = gusData.pkdList || [];
  
  // === POLA PODSTAWOWE ===
  // NIP bez myślników i spacji (tylko cyfry: 1234567890)
  data.Name = gusData.nip ? cleanNIP(gusData.nip) : '';  // GUS - numer NIP (pole główne)
  data.REGON = gusData.regon || '';
  data.KRS = gusData.krs || '';
  data.Nazwa_firmy = gusData.nazwa || '';
  
  // Powiązanie z firmą (Account) - lookup (pojedyncze powiązanie)
  if (accountId) {
    data.Firma = { id: accountId };
    appendLog('[GUS-MODULE] Powiązanie lookup z firmą (Accounts ID): ' + accountId);
  }
  
  // === FORMY PRAWNE ===
  var podstawowaSymbol = fullData.praw_podstawowaFormaPrawna_Symbol || fullData.fiz_podstawowaFormaPrawna_Symbol || '';
  var podstawowaNazwa = fullData.praw_podstawowaFormaPrawna_Nazwa || fullData.fiz_podstawowaFormaPrawna_Nazwa || '';
  var szczegolnaSymbol = fullData.praw_szczegolnaFormaPrawna_Symbol || fullData.fiz_szczegolnaFormaPrawna_Symbol || '';
  var szczegolnaNazwa = fullData.praw_szczegolnaFormaPrawna_Nazwa || fullData.fiz_szczegolnaFormaPrawna_Nazwa || '';
  
  data.Podstawowa_forma_prawna = podstawowaNazwa;
  data.Szczegolna_forma_prawna = szczegolnaNazwa;
  
  // Kod i nazwa (textarea - łączymy symbol + nazwa)
  if (podstawowaSymbol || podstawowaNazwa) {
    data.Kod_i_nazwa_podstawowej_formy_prawnej = podstawowaSymbol + ' - ' + podstawowaNazwa;
  }
  if (szczegolnaSymbol || szczegolnaNazwa) {
    data.Kod_i_nazwa_szczegolnej_formy_prawnej = szczegolnaSymbol + ' - ' + szczegolnaNazwa;
  }
  
  // === FINANSOWANIE I WŁASNOŚĆ ===
  var finansowanieSymbol = fullData.praw_formaFinansowania_Symbol || fullData.fiz_formaFinansowania_Symbol || '';
  var finansowanieNazwa = fullData.praw_formaFinansowania_Nazwa || fullData.fiz_formaFinansowania_Nazwa || '';
  var wlasnosciSymbol = fullData.praw_formaWlasnosci_Symbol || fullData.fiz_formaWlasnosci_Symbol || '';
  var wlasnosciNazwa = fullData.praw_formaWlasnosci_Nazwa || fullData.fiz_formaWlasnosci_Nazwa || '';
  
  data.Forma_finansowania = finansowanieNazwa;
  data.Forma_wlasnosci = wlasnosciNazwa;
  
  if (wlasnosciSymbol || wlasnosciNazwa) {
    data.Kod_i_nazwa_formy_wlasnosci = wlasnosciSymbol + ' - ' + wlasnosciNazwa;
  }
  
  // === ORGANY ===
  var organZalSymbol = fullData.praw_organZalozycielski_Symbol || fullData.fiz_organZalozycielski_Symbol || '';
  var organZalNazwa = fullData.praw_organZalozycielski_Nazwa || fullData.fiz_organZalozycielski_Nazwa || '';
  var organRejSymbol = fullData.praw_organRejestrowy_Symbol || fullData.fiz_organRejestrowy_Symbol || '';
  var organRejNazwa = fullData.praw_organRejestrowy_Nazwa || fullData.fiz_organRejestrowy_Nazwa || '';
  var rodzajRejSymbol = fullData.praw_rodzajRejestruEwidencji_Symbol || fullData.fiz_rodzajRejestruEwidencji_Symbol || '';
  var rodzajRejNazwa = fullData.praw_rodzajRejestruEwidencji_Nazwa || fullData.fiz_rodzajRejestruEwidencji_Nazwa || '';
  
  if (organZalSymbol || organZalNazwa) {
    data.Organ_zalozycielski = organZalSymbol + ' - ' + organZalNazwa;
  }
  if (organRejSymbol || organRejNazwa) {
    data.Organ_rejestrowy = organRejSymbol + ' - ' + organRejNazwa;
  }
  if (rodzajRejSymbol || rodzajRejNazwa) {
    data.Rodzaj_rejestru_lub_ewidencji = rodzajRejSymbol + ' - ' + rodzajRejNazwa;
  }
  
  // === TYP PODMIOTU (checkboxy P/F) ===
  var typPodmiotu = gusData.typ || '';
  if (typPodmiotu === 'P' || podstawowaSymbol === '1') {
    data.P_rodz_dzialalnosci = true;  // Osoba prawna
    data.F_rodz_dzialalnosci = false;
  } else if (typPodmiotu === 'F' || podstawowaSymbol === '9') {
    data.P_rodz_dzialalnosci = false;
    data.F_rodz_dzialalnosci = true;  // Osoba fizyczna
  }
  
  // === DATY ===
  data.Data_powstania = fullData.praw_dataPowstania || fullData.fiz_dataPowstania || '';
  data.data_rozpoczecia_dzialalnosci = fullData.praw_dataRozpoczeciaDzialalnosci || fullData.fiz_dataRozpoczeciaDzialalnosci || '';
  data.data_wpisu_do_REGON = fullData.praw_dataWpisuDoRegon || fullData.fiz_dataWpisuDoRegon || '';
  data.data_wpisu_do_rejestru_lub_ewidencji = fullData.praw_dataWpisuDoRejestruEwidencji || fullData.fiz_dataWpisuDoRejestruEwidencji || '';
  data.data_zawieszenia_dzialalnosci = fullData.praw_dataZawieszeniaDzialalnosci || fullData.fiz_dataZawieszeniaDzialalnosci || '';
  data.data_wznowienia_dzialalnosci = fullData.praw_dataWznowieniaDzialalnosci || fullData.fiz_dataWznowieniaDzialalnosci || '';
  data.data_zakonczenia_dzialalnosci = fullData.praw_dataZakonczeniaDzialalnosci || fullData.fiz_dataZakonczeniaDzialalnosci || '';
  data.data_skreslenia_z_REGON = fullData.praw_dataSkresleniaZRegon || fullData.fiz_dataSkresleniaZRegon || '';
  
  // === KONTAKT ===
  data.REGON_numer_telefonu = fullData.praw_numerTelefonu || fullData.fiz_numerTelefonu || '';
  data.REGON_adres_email = fullData.praw_adresEmail || fullData.fiz_adresEmail || '';
  data.REGON_adres_www = fullData.praw_adresStronyinternetowej || fullData.fiz_adresStronyinternetowej || '';
  
  // === DANE OSOBY FIZYCZNEJ ===
  if (fullData.fiz_nazwisko) {
    data.REGON_Nazwisko = fullData.fiz_nazwisko || '';
    data.REGON_Imie = fullData.fiz_imie1 || '';
    data.REGON_Drugie_imie = fullData.fiz_imie2 || '';
  }
  
  // === ADRES SIEDZIBY ===
  data.Siedziba_Ulica = fullData.praw_adSiedzUlica_Nazwa || fullData.fiz_adSiedzUlica_Nazwa || '';
  data.Siedziba_Nr_domu = fullData.praw_adSiedzNumerNieruchomosci || fullData.fiz_adSiedzNumerNieruchomosci || '';
  data.Siedziba_Nr_lokalu = fullData.praw_adSiedzNumerLokalu || fullData.fiz_adSiedzNumerLokalu || '';
  data.Siedziba_Miejscowosc = fullData.praw_adSiedzMiejscowosc_Nazwa || fullData.fiz_adSiedzMiejscowosc_Nazwa || '';
  data.Siedziba_Kod_pocztowy = fullData.praw_adSiedzKodPocztowy || fullData.fiz_adSiedzKodPocztowy || '';
  data.Siedziba_Gmina = fullData.praw_adSiedzGmina_Nazwa || fullData.fiz_adSiedzGmina_Nazwa || '';
  data.Siedziba_Powiat = fullData.praw_adSiedzPowiat_Nazwa || fullData.fiz_adSiedzPowiat_Nazwa || '';
  
  var wojewodztwo = fullData.praw_adSiedzWojewodztwo_Nazwa || fullData.fiz_adSiedzWojewodztwo_Nazwa || '';
  if (wojewodztwo) {
    data.Siedziba_Wojewodztwo = wojewodztwo.toLowerCase();
  }
  
  // Ulica dom lokal (pełny adres)
  var ulicaParts = [];
  if (data.Siedziba_Ulica) ulicaParts.push(data.Siedziba_Ulica);
  if (data.Siedziba_Nr_domu) {
    var addr = data.Siedziba_Nr_domu;
    if (data.Siedziba_Nr_lokalu) addr += '/' + data.Siedziba_Nr_lokalu;
    ulicaParts.push(addr);
  }
  data.Siedziba_Ulica_dom_lokal = ulicaParts.join(' ');
  
  // === JEDNOSTKI LOKALNE ===
  data.Liczba_jednostek_lokalnych = parseInt(fullData.praw_liczbaJednLokalnych || fullData.fiz_liczbaJednLokalnych || '0');
  
  // === KODY PKD ===
  if (pkdList && pkdList.length > 0) {
    // Pierwszy PKD (główny)
    var pkd1 = pkdList.find(function(p) {
      return (p.praw_pkdPrzewazajace === '1' || p.fiz_pkdPrzewazajace === '1');
    }) || pkdList[0];
    
    data.PKD1_kod = pkd1.praw_pkdKod || pkd1.fiz_pkdKod || '';
    data.PKD1_nazwa = pkd1.praw_pkdNazwa || pkd1.fiz_pkdNazwa || '';
    
    // Wszystkie PKD jako tekst (textarea 32000 znaków)
    var pkdStrings = [];
    for (var i = 0; i < pkdList.length; i++) {
      var pkd = pkdList[i];
      var kod = pkd.praw_pkdKod || pkd.fiz_pkdKod || '';
      var nazwa = pkd.praw_pkdNazwa || pkd.fiz_pkdNazwa || '';
      var przewaz = pkd.praw_pkdPrzewazajace || pkd.fiz_pkdPrzewazajace || '0';
      var prefix = przewaz === '1' ? '★ [GŁÓWNY] ' : '';
      
      pkdStrings.push(prefix + kod + ' - ' + nazwa);
      
      // Checkboxy dla konkretnych PKD (format: PKD_8610Z)
      // TYLKO dla PKD z zakresu 75XX-96XX (zgodnie z GUS_fields.csv linia 2-31)
      var kodClean = kod.replace(/[^0-9A-Z]/g, ''); // Usuń kropki i myślniki: "8622Z" → "8622Z", "86.23.Z" → "8623Z"
      var fieldName = 'PKD_' + kodClean;
      
      // Sprawdź czy to PKD z GUS_fields.csv (zakresy: 7500Z, 8610Z-8699D, 9601Z-9623Z)
      var kodPrefix = kodClean.substring(0, 2); // "86", "47", "96"
      var validRanges = ['75', '86', '96']; // Tylko te prefiksy mają checkboxy w GUS_fields.csv
      
      if (validRanges.indexOf(kodPrefix) !== -1) {
        data[fieldName] = true; // Zaznacz checkbox
      }
    }
    
    data.Wszystkie_kody_PKD = pkdStrings.join('\n');
    
    appendLog('[GUS-MODULE] Zmapowano ' + pkdList.length + ' kodów PKD');
  }
  
  return data;
}

// Buduje wpis historii (z datą i opisem zmian)
// Parametry:
//   isNew - czy to nowy rekord (true) czy aktualizacja (false)
//   changedFields - lista nazw pól które się zmieniły (opcjonalnie)
// Zwraca: string HTML z wpisem historii
function buildHistoryEntry(isNew, changedFields) {
  var now = new Date();
  var dateStr = now.toISOString().split('T')[0]; // YYYY-MM-DD
  var timeStr = now.toTimeString().split(' ')[0].substring(0, 5); // HH:MM
  var timestamp = dateStr + ' ' + timeStr;
  
  var entry = '<p><strong>' + timestamp + '</strong><br>';
  
  if (isNew) {
    entry += '✓ Utworzono rekord z danymi z systemu REGON GUS</p>';
  } else {
    entry += '✓ Zaktualizowano dane z systemu REGON GUS';
    if (changedFields && changedFields.length > 0) {
      entry += '<br>Zmienione pola: ' + changedFields.slice(0, 10).join(', ');
      if (changedFields.length > 10) {
        entry += ' (+' + (changedFields.length - 10) + ' więcej)';
      }
    }
    entry += '</p>';
  }
  
  return entry;
}

// Łączy nową historię ze starą (dopisuje na początek)
// Parametry:
//   oldHistory - istniejąca historia (HTML string)
//   newEntry - nowy wpis (HTML string)
// Zwraca: połączona historia
function prependHistory(oldHistory, newEntry) {
  if (!oldHistory) return newEntry;
  
  // Dopisz nową notę na początek (najnowsze na górze)
  return newEntry + '<hr style="margin: 8px 0; border: 0; border-top: 1px solid #e5e7eb;">' + oldHistory;
}

// Tworzy lub aktualizuje rekord w module GUS
// Parametry:
//   accountId - ID rekordu Accounts (powiązanie)
//   gusData - pełne dane z GUS
// Zwraca: { success: boolean, recordId?: string, created?: boolean }
async function createOrUpdateGusRecord(accountId, gusData) {
  try {
    if (!accountId) {
      return { success: false, error: 'Brak accountId' };
    }
    
    if (!gusData || !gusData.nip) {
      return { success: false, error: 'Brak danych GUS' };
    }
    
    appendLog('[GUS-MODULE] === ZAPIS DO MODUŁU GUS ===');
    
    // Szukaj istniejący rekord
    var existingRecord = await findGusRecordForAccount(accountId, gusData.nip);
    
    // Przygotuj dane do zapisu
    var apiData = buildGusModuleData(gusData, accountId);
    
    // Usuń pola systemowe i read-only (nie mogą być aktualizowane)
    var systemFields = ['Created_Time', 'Modified_Time', 'Created_By', 'Modified_By', 'Owner', 'Last_Activity_Time', 
                        'Unsubscribed_Time', 'Unsubscribed_Mode', 'Locked__s', 'Record_Image', 'Tag'];
    systemFields.forEach(function(field) {
      if (apiData[field] !== undefined) {
        delete apiData[field];
      }
    });
    
    appendLog('[GUS-MODULE] Przygotowano ' + Object.keys(apiData).length + ' pól do zapisu');
    appendLog('[GUS-MODULE] Przykładowe pola: ' + Object.keys(apiData).slice(0, 10).join(', '));
    
    if (existingRecord && existingRecord.id) {
      // AKTUALIZUJ istniejący rekord
      appendLog('[GUS-MODULE] Znaleziono istniejący rekord GUS: ' + existingRecord.id);
      
      if (accountId) {
        apiData.Firma = { id: accountId };
        appendLog('[GUS-MODULE] Ustawiam powiązanie lookup z firmą: ' + accountId);
      }
      
      appendLog('[GUS-MODULE] Aktualizuję rekord...');
      
      // Porównaj dane i znajdź zmienione pola (dla historii)
      var changedFields = [];
      Object.keys(apiData).forEach(function(key) {
        if (key === 'id' || key === 'Historia_rekordu') return;
        
        var oldVal = existingRecord[key];
        var newVal = apiData[key];
        
        if (Array.isArray(newVal)) {
          var oldValStr = JSON.stringify(oldVal || []);
          var newValStr = JSON.stringify(newVal);
          if (oldValStr !== newValStr) {
            changedFields.push(key);
          }
        } else if (newVal && typeof newVal === 'object') {
          var oldId = '';
          if (oldVal && typeof oldVal === 'object') {
            oldId = oldVal.id || oldVal.lookup_value || '';
          } else if (oldVal) {
            oldId = String(oldVal);
          }
          var newId = newVal.id || '';
          if (oldId !== newId) {
            changedFields.push(key);
          }
        } else if (String(oldVal || '') !== String(newVal || '')) {
          changedFields.push(key);
        }
      });
      
      appendLog('[GUS-MODULE] Wykryto ' + changedFields.length + ' zmienionych pól');
      if (changedFields.length > 0 && changedFields.length <= 15) {
        appendLog('[GUS-MODULE] Zmienione: ' + changedFields.join(', '));
      }
      
      // Dodaj wpis do historii (AKTUALIZACJA)
      var oldHistory = existingRecord.Historia_rekordu || '';
      var newHistoryEntry = buildHistoryEntry(false, changedFields);
      apiData.Historia_rekordu = prependHistory(oldHistory, newHistoryEntry);
      
      apiData.id = existingRecord.id;
      
      var updateResp = await updateRecord(GUS_MODULE_NAME, existingRecord.id, apiData);
      
      if (updateResp.success) {
        appendLog('[GUS-MODULE] ✓ Rekord GUS zaktualizowany pomyślnie!');
        return { success: true, recordId: existingRecord.id, created: false };
      } else {
        appendLog('[GUS-MODULE] ✗ Błąd aktualizacji: ' + (updateResp.error || JSON.stringify(updateResp.response)));
        return { success: false, error: updateResp.error || 'Błąd aktualizacji rekordu GUS' };
      }
    } else {
      // UTWÓRZ nowy rekord
      appendLog('[GUS-MODULE] Brak istniejącego rekordu - tworzę nowy');
      
      // Dodaj wpis do historii (UTWORZENIE)
      var newHistoryEntry = buildHistoryEntry(true);
      apiData.Historia_rekordu = newHistoryEntry;
      
      if (!window.ZOHO || !ZOHO.CRM || !ZOHO.CRM.API || typeof ZOHO.CRM.API.insertRecord !== 'function') {
        return { success: false, error: 'API insertRecord niedostępne' };
      }
      
      var insertResp = await ZOHO.CRM.API.insertRecord({
        Entity: GUS_MODULE_NAME,
        APIData: apiData,
        Trigger: ['workflow']
      });
      
      if (insertResp && insertResp.data && insertResp.data[0] && insertResp.data[0].code === 'SUCCESS') {
        var newId = insertResp.data[0].details.id;
        appendLog('[GUS-MODULE] ✓ Utworzono nowy rekord GUS: ' + newId);
        return { success: true, recordId: newId, created: true };
      } else {
        appendLog('[GUS-MODULE] ✗ Błąd tworzenia: ' + JSON.stringify(insertResp));
        return { success: false, error: 'Błąd tworzenia rekordu GUS', response: insertResp };
      }
    }
  } catch (err) {
    var errorMsg = (err && err.message) ? err.message : String(err);
    appendLog('[GUS-MODULE] Wyjątek: ' + errorMsg);
    return { success: false, error: errorMsg };
  }
}

