// ============================================================================
// zoho-sdk.js - Abstrakcja nad Zoho Embedded App SDK
// ============================================================================
// Wrapper functions dla Zoho SDK z defensywnym error handling
// Multi-fallback strategy dla pobierania kontekstu i zmiennych organizacyjnych
// ============================================================================

// === POMOCNICZE FUNKCJE ===

// Wyciąga pierwszy element jeśli tablica, inaczej zwraca wartość jako string
function pickFirst(value) {
  if (Array.isArray(value)) {
    return value.length > 0 ? value[0] : '';
  }
  if (value === 0) return '0';
  return value ? String(value) : '';
}

// Ekstrakcja wartości zmiennej organizacyjnej z różnych formatów odpowiedzi SDK
function extractOrgVarValue(resp) {
  if (!resp) return '';
  if (typeof resp.value === 'string') return resp.value;
  if (resp.data && typeof resp.data.value === 'string') return resp.data.value;
  if (resp.Success && typeof resp.Success.Content === 'string') return resp.Success.Content;
  if (resp.Success && typeof resp.Success.content === 'string') return resp.Success.content;
  return '';
}

// === ZMIENNE ORGANIZACYJNE ===

// Uniwersalna funkcja do pobierania zmiennych organizacyjnych z Zoho
// Próbuje różnych metod SDK (API.getOrgVariable i CONFIG.getOrgVariable)
async function loadOrgVariable(varName) {
  var value = '';
  
  // Próba 1: ZOHO.CRM.API.getOrgVariable
  try {
    if (window.ZOHO && ZOHO.CRM && ZOHO.CRM.API && typeof ZOHO.CRM.API.getOrgVariable === 'function') {
      var r1 = await ZOHO.CRM.API.getOrgVariable(varName);
      value = extractOrgVarValue(r1);
      if (value) {
        return value;
      }
    }
  } catch (e1) {
    if (typeof appendLog === 'function') {
      appendLog('[SDK] getOrgVariable(API) błąd dla ' + varName + ': ' + (e1 && e1.message ? e1.message : String(e1)));
    }
  }
  
  // Próba 2: ZOHO.CRM.CONFIG.getOrgVariable
  try {
    if (window.ZOHO && ZOHO.CRM && ZOHO.CRM.CONFIG && typeof ZOHO.CRM.CONFIG.getOrgVariable === 'function') {
      var r2 = await ZOHO.CRM.CONFIG.getOrgVariable(varName);
      value = extractOrgVarValue(r2);
      if (value) {
        return value;
      }
    }
  } catch (e2) {
    if (typeof appendLog === 'function') {
      appendLog('[SDK] getOrgVariable(CONFIG) błąd dla ' + varName + ': ' + (e2 && e2.message ? e2.message : String(e2)));
    }
  }
  
  return value;
}

// === KONTEKST REKORDU ===

// Pobiera kontekst rekordu (ID, Entity) - multi-fallback strategy
// Zwraca: { id: string, entity: string }
async function getRecordContext(pageLoadData) {
  var context = { id: '', entity: '' };
  
  // Wariant 1: Z eventu PageLoad (najbardziej niezawodny)
  if (pageLoadData && (pageLoadData.EntityId || pageLoadData.Entity)) {
    context.id = pickFirst(pageLoadData.EntityId);
    context.entity = pageLoadData.Entity || pageLoadData.Module || pageLoadData.module || CONSTANTS.DEFAULT_ENTITY;
    if (typeof appendLog === 'function') {
      appendLog('[SDK] Kontekst z PageLoad: ' + context.entity + ' ID=' + context.id);
    }
    return context;
  }
  
  // Wariant 2: ZOHO.CRM.UTIL.getQueryParams (Web Tab)
  try {
    if (ZOHO && ZOHO.CRM && ZOHO.CRM.UTIL && typeof ZOHO.CRM.UTIL.getQueryParams === 'function') {
      var qp = await ZOHO.CRM.UTIL.getQueryParams();
      var qId = qp.recId || qp.recordId || qp.id || qp.rid || qp.record_id || '';
      var qEnt = qp.entity || qp.module || qp.m || qp.mod || '';
      if (qId) {
        context.id = qId;
        context.entity = qEnt || CONSTANTS.DEFAULT_ENTITY;
        if (typeof appendLog === 'function') {
          appendLog('[SDK] Kontekst z UTIL.getQueryParams: ' + context.entity + ' ID=' + context.id);
        }
        return context;
      }
    }
  } catch (e) {
    if (typeof appendLog === 'function') {
      appendLog('[SDK] UTIL.getQueryParams błąd: ' + (e && e.message ? e.message : String(e)));
    }
  }
  
  // Wariant 3: ZOHO.CRM.UI.getPageInfo
  try {
    if (ZOHO && ZOHO.CRM && ZOHO.CRM.UI && typeof ZOHO.CRM.UI.getPageInfo === 'function') {
      var pInfo = await ZOHO.CRM.UI.getPageInfo();
      var pId = pickFirst(pInfo && pInfo.EntityId);
      var pEnt = (pInfo && (pInfo.Entity || pInfo.Module || pInfo.module)) || '';
      if (pId) {
        context.id = pId;
        context.entity = pEnt || CONSTANTS.DEFAULT_ENTITY;
        if (typeof appendLog === 'function') {
          appendLog('[SDK] Kontekst z UI.getPageInfo: ' + context.entity + ' ID=' + context.id);
        }
        return context;
      }
    }
  } catch (e2) {
    if (typeof appendLog === 'function') {
      appendLog('[SDK] UI.getPageInfo błąd: ' + (e2 && e2.message ? e2.message : String(e2)));
    }
  }
  
  // Wariant 4: Natywne URLSearchParams (ostateczny fallback)
  try {
    var params = new URLSearchParams(window.location.search || '');
    var urlId = params.get('recId') || params.get('recordId') || params.get('id') || params.get('rid') || params.get('record_id') || '';
    var urlEnt = params.get('entity') || params.get('module') || params.get('m') || params.get('mod') || '';
    if (urlId) {
      context.id = urlId;
      context.entity = urlEnt || CONSTANTS.DEFAULT_ENTITY;
      if (typeof appendLog === 'function') {
        appendLog('[SDK] Kontekst z URL: ' + context.entity + ' ID=' + context.id);
      }
    }
  } catch (e3) {
    if (typeof appendLog === 'function') {
      appendLog('[SDK] URL fallback błąd: ' + (e3 && e3.message ? e3.message : String(e3)));
    }
  }
  
  return context;
}

// === OPERACJE CRUD ===

// Pobiera rekord z Zoho CRM
// Zwraca: obiekt rekordu lub null w przypadku błędu
async function getRecord(entity, recordId) {
  try {
    if (!recordId) return null;
    
    if (!window.ZOHO || !ZOHO.CRM || !ZOHO.CRM.API || typeof ZOHO.CRM.API.getRecord !== 'function') {
      if (typeof appendLog === 'function') {
        appendLog('[SDK] API getRecord niedostępne');
      }
      return null;
    }
    
    var resp = await ZOHO.CRM.API.getRecord({
      Entity: entity,
      RecordID: recordId
    });
    
    if (resp && resp.data && resp.data[0]) {
      return resp.data[0];
    }
    
    return null;
  } catch (e) {
    if (typeof appendLog === 'function') {
      appendLog('[SDK] getRecord błąd: ' + (e && e.message ? e.message : String(e)));
    }
    return null;
  }
}

// Aktualizuje rekord w Zoho CRM (tylko dla istniejących rekordów)
// Zwraca: { success: boolean, response: object }
async function updateRecord(entity, recordId, data) {
  try {
    if (!recordId) {
      return { success: false, error: 'Brak ID rekordu (nie można zaktualizować nowego rekordu)' };
    }
    
    if (!window.ZOHO || !ZOHO.CRM || !ZOHO.CRM.API || typeof ZOHO.CRM.API.updateRecord !== 'function') {
      return { success: false, error: 'API updateRecord niedostępne' };
    }
    
    // API Zoho wymaga pola 'id' w danych
    var apiData = Object.assign({}, data);
    apiData.id = recordId;
    
    var resp = await ZOHO.CRM.API.updateRecord({
      Entity: entity,
      APIData: apiData
    });
    
    if (resp && resp.data && resp.data[0] && resp.data[0].code === 'SUCCESS') {
      return { success: true, response: resp };
    }
    
    // SZCZEGÓŁOWE LOGOWANIE BŁĘDU
    if (typeof appendLog === 'function') {
      appendLog('[SDK] updateRecord BŁĄD - szczegóły:');
      appendLog('[SDK] Entity: ' + entity);
      appendLog('[SDK] RecordID: ' + recordId);
      
      if (resp && resp.data && resp.data[0]) {
        var errData = resp.data[0];
        appendLog('[SDK] Code: ' + (errData.code || '?'));
        appendLog('[SDK] Message: ' + (errData.message || '?'));
        appendLog('[SDK] Status: ' + (errData.status || '?'));
        
        if (errData.details) {
          appendLog('[SDK] Details: ' + JSON.stringify(errData.details, null, 2));
        }
      } else {
        appendLog('[SDK] Pełna odpowiedź: ' + JSON.stringify(resp, null, 2).substring(0, 1000));
      }
    }
    
    return { success: false, response: resp, error: 'Zoho zwrócił błąd - sprawdź logi' };
  } catch (e) {
    if (typeof appendLog === 'function') {
      appendLog('[SDK] updateRecord WYJĄTEK: ' + (e && e.message ? e.message : String(e)));
      
      // Próba serializacji pełnego obiektu błędu
      try {
        var errStr = JSON.stringify(e, Object.getOwnPropertyNames(e), 2);
        appendLog('[SDK] Pełny błąd JSON: ' + errStr.substring(0, 500));
      } catch (serErr) {
        appendLog('[SDK] Nie mogę zserializować błędu');
      }
      
      if (e && e.stack) {
        appendLog('[SDK] Stack: ' + e.stack.substring(0, 500));
      }
    }
    return { success: false, error: (e && e.message ? e.message : String(e)), exception: e };
  }
}

// Wypełnia pola w formularzu tworzenia nowego rekordu
// UWAGA: closeReload() w CreateOrCloneView może nie działać dla custom fields!
// Alternatywa: kopiuj dane do schowka i pokaż instrukcję
async function populateAndClose(data) {
  console.log('========================================');
  console.log('[SDK] populateAndClose() WYWOŁANA');
  console.log('[SDK] Dane do wklejenia:', data);
  console.log('[SDK] Ilość pól:', Object.keys(data).length);
  console.log('========================================');
  
  try {
    if (!window.ZOHO || !ZOHO.CRM || !ZOHO.CRM.UI || !ZOHO.CRM.UI.Popup) {
      console.error('[SDK] BŁĄD: UI.Popup niedostępne');
      if (typeof appendLog === 'function') {
        appendLog('[SDK] UI.Popup niedostępne');
      }
      return { success: false, error: 'UI.Popup niedostępne' };
    }
    
    if (typeof appendLog === 'function') {
      appendLog('[SDK] Wypełniam pola: ' + Object.keys(data).join(', '));
    }
    
    console.log('[SDK] Wywołuję ZOHO.CRM.UI.Popup.closeReload({ data: ... })');
    console.log('[SDK] Format danych:', JSON.stringify(data, null, 2).substring(0, 500));
    
    // Próba 1: closeReload() - standard dla button widgets
    try {
      var result = await ZOHO.CRM.UI.Popup.closeReload({ data: data });
      console.log('[SDK] closeReload() zwróciło:', result);
      
      if (typeof appendLog === 'function') {
        appendLog('[SDK] Widget zamknięty - pola wypełnione przez closeReload()');
      }
      
      return { success: true, result: result, method: 'closeReload' };
    } catch (closeReloadErr) {
      console.error('[SDK] closeReload() BŁĄD:', closeReloadErr);
      
      if (typeof appendLog === 'function') {
        appendLog('[SDK] closeReload() nie zadziałało: ' + (closeReloadErr && closeReloadErr.message ? closeReloadErr.message : String(closeReloadErr)));
      }
      
      // Próba 2: close() bez parametrów (widget się zamyka, pola NIE wypełnione)
      console.log('[SDK] Fallback: zamykam widget bez wypełnienia pól');
      await ZOHO.CRM.UI.Popup.close();
      
      return { success: false, error: 'closeReload() nie działa w CreateOrCloneView', method: 'close_only' };
    }
  } catch (e) {
    console.error('[SDK] populateAndClose WYJĄTEK:', e);
    if (typeof appendLog === 'function') {
      appendLog('[SDK] populateAndClose błąd: ' + (e && e.message ? e.message : String(e)));
    }
    return { success: false, error: (e && e.message ? e.message : String(e)) };
  }
}

// Wyszukuje rekordy według kryteriów
// Zwraca: tablica rekordów (pusta jeśli brak wyników)
async function searchRecords(entity, criteria, page, perPage) {
  try {
    if (!window.ZOHO || !ZOHO.CRM || !ZOHO.CRM.API || typeof ZOHO.CRM.API.searchRecord !== 'function') {
      return [];
    }
    
    var resp = await ZOHO.CRM.API.searchRecord({
      Entity: entity,
      Type: 'criteria',
      Query: criteria,
      page: page || 1,
      per_page: perPage || 200
    });
    
    return (resp && resp.data) ? resp.data : [];
  } catch (e) {
    if (typeof appendLog === 'function') {
      appendLog('[SDK] searchRecord błąd: ' + (e && e.message ? e.message : String(e)));
    }
    return [];
  }
}

// === METADANE ===

// Rozwiązuje API name modułu po etykiecie (singular/plural label)
async function resolveModuleApiName(preferredLabel) {
  try {
    if (!window.ZOHO || !ZOHO.CRM || !ZOHO.CRM.META || typeof ZOHO.CRM.META.getModules !== 'function') {
      if (typeof appendLog === 'function') {
        appendLog('[SDK] API getModules niedostępne');
      }
      return '';
    }
    
    var mods = await ZOHO.CRM.META.getModules();
    var items = (mods && mods.modules) ? mods.modules : [];
    var lower = String(preferredLabel || '').toLowerCase();
    
    for (var i = 0; i < items.length; i++) {
      var m = items[i];
      var sing = (m.singular_label || '').toLowerCase();
      var plur = (m.plural_label || '').toLowerCase();
      
      if (sing === lower || plur === lower) {
        if (typeof appendLog === 'function') {
          appendLog('[SDK] Moduł "' + preferredLabel + '" → ' + m.api_name);
        }
        return m.api_name;
      }
    }
    
    // Fallback heurystyczny (jeśli etykieta nie pasuje)
    var guess = CONSTANTS.MODULES.GUS_NAJWAZNIEJSZE;
    for (var j = 0; j < items.length; j++) {
      if (items[j].api_name === guess) {
        if (typeof appendLog === 'function') {
          appendLog('[SDK] Używam heurystyki: ' + guess);
        }
        return guess;
      }
    }
    
    if (typeof appendLog === 'function') {
      appendLog('[SDK] Nie znaleziono modułu: ' + preferredLabel);
    }
    return '';
  } catch (e) {
    if (typeof appendLog === 'function') {
      appendLog('[SDK] getModules błąd: ' + (e && e.message ? e.message : String(e)));
    }
    return '';
  }
}

// === UI ===

// Zamyka widget (popup)
async function closeWidget() {
  try {
    if (!window.ZOHO || !ZOHO.CRM || !ZOHO.CRM.UI || !ZOHO.CRM.UI.Popup) {
      if (typeof appendLog === 'function') {
        appendLog('[SDK] UI.Popup niedostępne');
      }
      return false;
    }
    
    await ZOHO.CRM.UI.Popup.close();
    if (typeof appendLog === 'function') {
      appendLog('[SDK] Widget zamknięty');
    }
    return true;
  } catch (e) {
    if (typeof appendLog === 'function') {
      appendLog('[SDK] Błąd zamykania: ' + (e && e.message ? e.message : String(e)));
    }
    return false;
  }
}

// Buduje URL do rekordu w Zoho CRM
// Używa zmiennych z ORG_CONFIG (ZOHO_CRM_BASE_URL, ZOHO_ORG_ID)
function buildRecordUrl(recordId, moduleName) {
  if (!ORG_CONFIG.ZOHO_CRM_BASE_URL || !ORG_CONFIG.ZOHO_ORG_ID) {
    if (typeof appendLog === 'function') {
      appendLog('[SDK] Brak konfiguracji URL - ustaw ZOHO_CRM_BASE_URL i ZOHO_ORG_ID');
    }
    return '';
  }
  
  var module = moduleName || CONFIG.currentEntity || CONSTANTS.DEFAULT_ENTITY;
  return ORG_CONFIG.ZOHO_CRM_BASE_URL + '/crm/' + ORG_CONFIG.ZOHO_ORG_ID + '/tab/' + module + '/' + recordId;
}

// === LOGOWANIE URL (DEBUGGING) ===

// Loguje pełny kontekst URL (query params, hash) - pomocne przy debugowaniu
function logUrlContext() {
  try {
    if (typeof appendLog !== 'function') return;
    
    appendLog('[URL] href=' + window.location.href);
    
    var q = new URLSearchParams(window.location.search || '');
    var keys = [];
    q.forEach(function(_, k) { keys.push(k + '=' + q.get(k)); });
    appendLog('[URL] query params: ' + (keys.join('&') || '(brak)'));
    
    var h = (window.location.hash || '').replace(/^#/, '');
    if (h) {
      var hs = new URLSearchParams(h);
      var hkeys = [];
      hs.forEach(function(_, k) { hkeys.push(k + '=' + hs.get(k)); });
      appendLog('[URL] hash params: ' + hkeys.join('&'));
    }
  } catch (e) {
    if (typeof appendLog === 'function') {
      appendLog('[URL] log error: ' + (e && e.message ? e.message : String(e)));
    }
  }
}
