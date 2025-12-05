// ============================================================================
// ui.js - Komponenty UI (modalne, spinner, logi, tabela)
// ============================================================================
// Wszystkie funkcje odpowiedzialne za wyświetlanie i zarządzanie elementami UI
// ============================================================================

// === MODALNE ===

function showNazwaZwyczajowaModal(existingNazwa) {
  var input = document.getElementById('nazwaZwyczajowaInput');
  var saveBtn = document.getElementById('saveNazwaBtn');
  
  if (input) {
    input.value = existingNazwa || '';
    CONFIG.originalNazwaZwyczajowa = existingNazwa || '';
  }
  
  if (saveBtn) {
    if (existingNazwa) {
      saveBtn.textContent = 'Zakończ bez zmiany nazwy';
    } else {
      saveBtn.textContent = 'Zakończ bez nazwy';
    }
  }
  
  var modal = document.getElementById('nazwaZwyczajowaModal');
  if (modal) modal.classList.remove('d-none');
}

function hideNazwaZwyczajowaModal() {
  var modal = document.getElementById('nazwaZwyczajowaModal');
  if (modal) modal.classList.add('d-none');
}

function showSuccessModal() {
  var modal = document.getElementById('successModal');
  if (modal) modal.classList.remove('d-none');
}

function hideSuccessModal() {
  var modal = document.getElementById('successModal');
  if (modal) modal.classList.add('d-none');
}

function showErrorModal(message) {
  var body = document.getElementById('errorModalBody');
  if (body) body.textContent = message;
  
  var modal = document.getElementById('errorModal');
  if (modal) modal.classList.remove('d-none');
}

function hideErrorModal() {
  var modal = document.getElementById('errorModal');
  if (modal) modal.classList.add('d-none');
}

function showInfoModal(title, message) {
  var titleEl = document.getElementById('infoModalTitle');
  var bodyEl = document.getElementById('infoModalBody');
  
  if (titleEl) titleEl.textContent = title;
  if (bodyEl) bodyEl.textContent = message;
  
  var modal = document.getElementById('infoModal');
  if (modal) modal.classList.remove('d-none');
}

function hideInfoModal() {
  var modal = document.getElementById('infoModal');
  if (modal) modal.classList.add('d-none');
}

// === SPINNER ŁADOWANIA ===

function showSpinner() {
  var spinner = document.getElementById('loadingSpinner');
  if (spinner) spinner.classList.remove('d-none');
  document.body.classList.add('has-data');
}

function hideSpinner() {
  var spinner = document.getElementById('loadingSpinner');
  if (spinner) spinner.classList.add('d-none');
}

// === PANEL LOGÓW ===

function toggleLogPanel() {
  var panel = document.getElementById('logsPanel');
  if (!panel) return;
  
  var isVisible = panel.classList.contains('visible');
  if (isVisible) {
    panel.classList.remove('visible');
    CONFIG.isLogPanelOpen = false;
  } else {
    panel.classList.add('visible');
    CONFIG.isLogPanelOpen = true;
    CONFIG.logCount = 0;
  }
}

function appendLog(message) {
  var container = document.getElementById('logsContent');
  if (!container) return;
  
  var time = new Date().toISOString();
  var div = document.createElement('div');
  div.className = 'log-entry info';
  div.textContent = '[' + time + '] ' + message;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  
  if (!CONFIG.isLogPanelOpen) {
    CONFIG.logCount++;
  }
}

function copyLogs() {
  try {
    var content = document.getElementById('logsContent');
    if (!content) return;
    
    var text = content.innerText || '';
    var ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    
    appendLog('[UI] Logi skopiowane do schowka');
  } catch (e) {
    appendLog('[UI] Błąd kopiowania: ' + (e && e.message ? e.message : String(e)));
  }
}

function clearLogs() {
  var container = document.getElementById('logsContent');
  if (container) {
    container.innerHTML = '';
    CONFIG.logCount = 0;
    appendLog('[UI] Logi wyczyszczone');
  }
}

// === TABELA PORÓWNANIA DANYCH ===

// Renderuje wiersz porównania (Posiadane dane | Dane z GUS | Checkbox)
// UWAGA: Wszystkie wartości są sanityzowane przez escapeHtml() (ochrona przed XSS)
function renderComparisonRow(label, fieldName, currentVal, newVal, checkedDefault) {
  var isEmpty = !currentVal;
  var checked = (checkedDefault === true || (checkedDefault === undefined && isEmpty)) ? ' checked' : '';
  
  // Sanityzacja wszystkich wartości wyświetlanych użytkownikowi
  var safeLabel = escapeHtml(label);
  var safeFieldName = escapeHtml(fieldName);
  var safeCurrentVal = escapeHtml(currentVal || '-');
  var safeNewVal = escapeHtml(newVal || '-');
  
  return '<div class="comparison-row">' +
    '<div>' + safeLabel + '</div>' +
    '<div>' + safeCurrentVal + '</div>' +
    '<div><label class="checkbox-item"><input type="checkbox" data-field="' + safeFieldName + '"' + checked + '> ' + safeNewVal + '</label></div>' +
  '</div>';
}

// Renderuje wiersz z kolorowaną wartością (np. dla nazwy firmy)
// UWAGA: Wszystkie wartości są sanityzowane przez escapeHtml() (ochrona przed XSS)
function renderComparisonRowWithColor(label, fieldName, currentVal, newVal, checkedDefault, newValColor) {
  var isEmpty = !currentVal;
  var checked = (checkedDefault === true || (checkedDefault === undefined && isEmpty)) ? ' checked' : '';
  
  // Sanityzacja wszystkich wartości wyświetlanych użytkownikowi
  var safeLabel = escapeHtml(label);
  var safeFieldName = escapeHtml(fieldName);
  var safeCurrentVal = escapeHtml(currentVal || '-');
  var safeNewVal = escapeHtml(newVal || '-');
  var safeColor = escapeHtml(newValColor); // Nawet kolor - na wypadek injection
  
  return '<div class="comparison-row">' +
    '<div>' + safeLabel + '</div>' +
    '<div>' + safeCurrentVal + '</div>' +
    '<div><label class="checkbox-item"><input type="checkbox" data-field="' + safeFieldName + '"' + checked + '> <span style="color: ' + safeColor + ';">' + safeNewVal + '</span></label></div>' +
  '</div>';
}

// Wyświetla podgląd danych z GUS w formie tabeli porównania
// Parametry:
//   gusData - dane pobrane z GUS
//   currentData - obecne dane w rekordzie CRM
function showDataPreview(gusData, currentData) {
  hideSpinner();
  
  CONFIG.fetchedData = gusData;
  
  var preview = document.getElementById('dataPreview');
  var content = document.getElementById('previewContent');
  if (!preview || !content) {
    appendLog('[UI] BŁĄD: Nie znaleziono elementów dataPreview lub previewContent');
    return;
  }
  
  var firmName = (gusData.nazwa || '').toUpperCase();
  
  var html = '';
  html += '<div class="comparison-table">';
  html += '  <div class="comparison-header">';
  html += '    <div></div><div>Posiadane dane</div><div>Dane z systemu REGON</div>';
  html += '  </div>';
  html += '  <div id="cmp-table-body">';
  html += '  </div>';
  html += '</div>';
  
  content.innerHTML = html;
  
  // Generuj wiersze tabeli
  var rowsHtml = '';
  rowsHtml += renderComparisonRowWithColor('Nazwa firmy', CONSTANTS.FIELDS.ACCOUNT_NAME, currentData.Account_Name, firmName, true, '#0b1f4c');
  
  // Formatuj NIP z myślnikami (XXX-XXX-XX-XX)
  var nipFormatted = gusData.nip ? formatNIP(gusData.nip) : '';
  rowsHtml += renderComparisonRow('NIP', CONSTANTS.FIELDS.FIRMA_NIP, currentData.Firma_NIP, nipFormatted);
  
  rowsHtml += renderComparisonRow('REGON', CONSTANTS.FIELDS.FIRMA_REGON, currentData.Firma_REGON, gusData.regon);
  rowsHtml += renderComparisonRow('KRS', CONSTANTS.FIELDS.FIRMA_KRS, currentData.Firma_KRS, gusData.krs);
  rowsHtml += renderComparisonRow('Ulica (pełny adres)', CONSTANTS.FIELDS.BILLING_STREET, currentData.Billing_Street, buildFullAddress(gusData));
  rowsHtml += renderComparisonRow('Nazwa ulicy', CONSTANTS.FIELDS.BILLING_STREET_NAME, currentData.Billing_Street_Name, gusData.ulica || '');
  rowsHtml += renderComparisonRow('Nr budynku', CONSTANTS.FIELDS.BILLING_BUILDING_NUMBER, currentData.Billing_Building_Number, gusData.nrNieruchomosci);
  rowsHtml += renderComparisonRow('Nr lokalu', CONSTANTS.FIELDS.BILLING_LOCAL_NUMBER, currentData.Billing_Local_Number, gusData.nrLokalu);
  rowsHtml += renderComparisonRow('Miasto', CONSTANTS.FIELDS.BILLING_CITY, currentData.Billing_City, gusData.miejscowosc);
  rowsHtml += renderComparisonRow('Kod pocztowy', CONSTANTS.FIELDS.BILLING_CODE, currentData.Billing_Code, gusData.kodPocztowy ? formatZipCode(gusData.kodPocztowy) : '');
  rowsHtml += renderComparisonRow(
    'Województwo',
    CONSTANTS.FIELDS.BILLING_STATE,
    String(currentData.Billing_State || '').toLowerCase(),
    (gusData.wojewodztwo || '').toLowerCase()
  );
  rowsHtml += renderComparisonRow('Powiat', CONSTANTS.FIELDS.BILLING_POWIAT, currentData.Billing_Powiat, gusData.powiat);
  rowsHtml += renderComparisonRow('Gmina', CONSTANTS.FIELDS.BILLING_GMINA, currentData.Billing_Gmina, gusData.gmina);
  rowsHtml += renderComparisonRow('Kraj', CONSTANTS.FIELDS.BILLING_COUNTRY, currentData.Billing_Country, CONSTANTS.DEFAULT_COUNTRY, currentData.Billing_Country ? false : true);
  
  var bodyEl = document.getElementById('cmp-table-body');
  if (bodyEl) {
    bodyEl.innerHTML = rowsHtml;
  } else {
    appendLog('[UI] BŁĄD: Nie znaleziono elementu cmp-table-body');
  }
  
  // Usuń stare przyciski akcji
  var oldActions = document.getElementById('cmp-actions');
  if (oldActions && oldActions.parentNode) {
    oldActions.parentNode.removeChild(oldActions);
  }
  
  // Dodaj przyciski akcji
  var actions = document.createElement('div');
  actions.className = 'other-actions';
  actions.id = 'cmp-actions';
  actions.innerHTML = '<button type="button" class="btn-secondary" id="closeNoSaveBtn" style="margin-right: auto;">Zamknij bez zapisu</button> ' +
    '<button type="button" class="btn-secondary" id="unselAll">Odznacz wszystkie</button> ' +
    '<button type="button" class="btn-secondary" id="selAll">Zaznacz wszystkie</button> ' +
    '<button type="button" class="btn-primary" id="saveBtnDup">Zapisz dane</button>';
  preview.appendChild(actions);
  
  // Pokaż podgląd
  preview.classList.remove('d-none');
  preview.style.display = 'block';
  
  appendLog('[UI] Tabela porównania wyświetlona');
  
  // WAŻNE: Podłącz handlery TUTAJ w showDataPreview
  // Nie używamy osobnej funkcji attachPreviewActionHandlers (bo może być problem z timing)
  setTimeout(function() {
    attachPreviewActionHandlers();
  }, 100);
}

// Podłącza event handlery do przycisków w podglądzie danych
// UWAGA: Ta funkcja jest wywoływana PRZEZ showDataPreview (z timeoutem)
function attachPreviewActionHandlers() {
  appendLog('[UI] Podłączam event handlery do przycisków...');
  
  var closeNoSave = document.getElementById('closeNoSaveBtn');
  if (closeNoSave) {
    appendLog('[UI] Przycisk "Zamknij bez zapisu" znaleziony');
    closeNoSave.addEventListener('click', function() {
      appendLog('[UI] Kliknięto "Zamknij bez zapisu"');
      closeWidget();
    });
  }
  
  var selAll = document.getElementById('selAll');
  if (selAll) {
    appendLog('[UI] Przycisk "Zaznacz wszystkie" znaleziony');
    selAll.addEventListener('click', function() {
      appendLog('[UI] Kliknięto "Zaznacz wszystkie"');
      selectAllFields(true);
    });
  }
  
  var unselAll = document.getElementById('unselAll');
  if (unselAll) {
    appendLog('[UI] Przycisk "Odznacz wszystkie" znaleziony');
    unselAll.addEventListener('click', function() {
      appendLog('[UI] Kliknięto "Odznacz wszystkie"');
      selectAllFields(false);
    });
  }
  
  var saveDup = document.getElementById('saveBtnDup');
  if (saveDup) {
    appendLog('[UI] Przycisk "Zapisz dane" znaleziony');
    appendLog('[UI] Sprawdzam czy handleSaveData istnieje: ' + (typeof handleSaveData));
    
    saveDup.addEventListener('click', function() {
      appendLog('[UI] === KLIKNIĘTO "ZAPISZ DANE" ===');
      
      if (typeof handleSaveData === 'function') {
        appendLog('[UI] Wywołuję handleSaveData()');
        handleSaveData();
      } else {
        appendLog('[UI] BŁĄD: handleSaveData nie jest funkcją! Typ: ' + (typeof handleSaveData));
        showErrorModal('Błąd wewnętrzny: funkcja zapisu nie została załadowana. Odśwież stronę.');
      }
    });
  } else {
    appendLog('[UI] BŁĄD: Przycisk "Zapisz dane" NIE znaleziony!');
  }
  
  appendLog('[UI] Event handlery podłączone');
}

// Zaznacza/odznacza wszystkie checkboxy w tabeli porównania
function selectAllFields(checked) {
  var checkboxes = document.querySelectorAll('[data-field]');
  appendLog('[UI] selectAllFields(' + checked + ') - znaleziono ' + checkboxes.length + ' checkboxów');
  for (var i = 0; i < checkboxes.length; i++) {
    checkboxes[i].checked = checked;
  }
}

// Ukrywa podgląd danych
function hideDataPreview() {
  var preview = document.getElementById('dataPreview');
  if (preview) {
    preview.style.display = 'none';
    preview.classList.add('d-none');
  }
}

// === MODAL DUPLIKATU (z dynamicznym linkiem) ===

// Pokazuje modal z informacją o duplikacie NIP
// Parametry:
//   duplicateRecord - obiekt z danymi duplikatu
//   nip - numer NIP (dla wyświetlenia)
// UWAGA: Wszystkie dane są sanityzowane przez escapeHtml() (ochrona przed XSS)
function showDuplicateModal(duplicateRecord, nip) {
  var errorModal = document.getElementById('errorModal');
  var errorBody = document.getElementById('errorModalBody');
  if (!errorModal || !errorBody) return;
  
  // Sanityzacja wszystkich danych przed wyświetleniem
  var safeNip = escapeHtml(nip);
  var safeName = escapeHtml(duplicateRecord.Account_Name || 'brak');
  var safeAddress = escapeHtml(duplicateRecord.Adres_Siedziby || '');
  
  var adresSiedzibyHtml = '';
  if (safeAddress) {
    adresSiedzibyHtml = '<p style="margin-bottom: 12px; color: #000;"><strong>Adres siedziby:</strong> ' + safeAddress + '</p>';
  }
  
  errorBody.innerHTML = '<p style="margin-bottom: 12px; color: #000;">Nie mogę zapisać danych, ponieważ w systemie istnieje już rekord o takim samym numerze NIP <strong>' + safeNip + '</strong>.</p>' +
    '<p style="margin-bottom: 8px; color: #000;"><strong>Nazwa:</strong> ' + safeName + '</p>' +
    adresSiedzibyHtml +
    '<div style="display: flex; justify-content: space-between; align-items: center;">' +
    '<button type="button" id="openDuplicateRecord" class="btn-primary" style="background: linear-gradient(135deg, #00e09f 0%, #0065d7 100%); flex: 0 0 auto;">Otwórz rekord</button>' +
    '<button type="button" id="closeDuplicateWidget" class="btn-secondary" style="margin-left: auto;">Zamknij widget</button>' +
    '</div>';
  
  errorModal.classList.remove('d-none');
  
  // Podłącz event handlery
  var openBtn = document.getElementById('openDuplicateRecord');
  if (openBtn) {
    openBtn.addEventListener('click', function() {
      var recUrl = buildRecordUrl(duplicateRecord.id, 'Accounts');
      if (recUrl) {
        window.open(recUrl, '_blank');
        appendLog('[UI] Otwarto duplikat: ' + duplicateRecord.id);
      } else {
        appendLog('[UI] Błąd: nie mogę otworzyć rekordu - brak konfiguracji URL');
      }
      errorModal.classList.add('d-none');
      closeWidget();
    });
  }
  
  var closeBtn = document.getElementById('closeDuplicateWidget');
  if (closeBtn) {
    closeBtn.addEventListener('click', function() {
      errorModal.classList.add('d-none');
      closeWidget();
    });
  }
}
