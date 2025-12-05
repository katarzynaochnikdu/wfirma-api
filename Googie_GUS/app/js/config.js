// ============================================================================
// config.js - Centralna konfiguracja widgetu GUS
// ============================================================================
// Zawiera wszystkie zmienne organizacyjne, stałe i globalny stan aplikacji.
// Parametryzowane przez Zoho Organization Variables (grupa: GOOGIE_GUS)
// ============================================================================

// === GLOBALNE ZMIENNE STANU ===
var CONFIG = {
  // Kontekst rekordu Zoho CRM
  currentRecordId: '',
  currentEntity: '',
  
  // Dane pobrane z GUS
  fetchedData: null,
  currentRecordData: {},
  
  // Cechy rekordu
  adresWRekordzie: '',
  originalNazwaZwyczajowa: '',
  
  // UI State
  logCount: 0,
  isLogPanelOpen: false
};

// === ZMIENNE ORGANIZACYJNE (z Zoho Org Variables - grupa GOOGIE_GUS) ===
var ORG_CONFIG = {
  GUS_API_KEY: '',
  GUS_BACKEND_URL: '',
  ZOHO_CRM_BASE_URL: '',
  ZOHO_ORG_ID: '',
  BRAND_LOGO_URL: 'MD_favicon.png'  // Domyślna wartość
};

// === STAŁE APLIKACJI ===
var CONSTANTS = {
  // Moduły Zoho CRM
  DEFAULT_ENTITY: 'Accounts',
  
  // Nazwy custom fields (API names)
  FIELDS: {
    FIRMA_NIP: 'Firma_NIP',
    FIRMA_REGON: 'Firma_REGON',
    FIRMA_KRS: 'Firma_KRS',
    ADRES_W_REKORDZIE: 'Adres_w_rekordzie',
    NAZWA_ZWYCZAJOWA: 'Nazwa_zwyczajowa',
    ADRES_SIEDZIBY: 'Adres_Siedziby',
    
    // Billing fields
    BILLING_STREET: 'Billing_Street',
    BILLING_STREET_NAME: 'Billing_Street_Name',
    BILLING_BUILDING_NUMBER: 'Billing_Building_Number',
    BILLING_LOCAL_NUMBER: 'Billing_Local_Number',
    BILLING_CITY: 'Billing_City',
    BILLING_CODE: 'Billing_Code',
    BILLING_STATE: 'Billing_State',
    BILLING_POWIAT: 'Billing_Powiat',
    BILLING_GMINA: 'Billing_Gmina',
    BILLING_COUNTRY: 'Billing_Country',
    
    // Shipping fields
    SHIPPING_STREET: 'Shipping_Street',
    SHIPPING_STREET_NAME: 'Shipping_Street_Name',
    SHIPPING_BUILDING_NUMBER: 'Shipping_Building_Number',
    SHIPPING_LOCAL_NUMBER: 'Shipping_Local_Number',
    SHIPPING_CITY: 'Shipping_City',
    SHIPPING_CODE: 'Shipping_Code',
    SHIPPING_STATE: 'Shipping_State',
    SHIPPING_POWIAT: 'Shipping_Powiat',
    SHIPPING_GMINA: 'Shipping_Gmina',
    SHIPPING_COUNTRY: 'Shipping_Country',
    
    // System fields
    ACCOUNT_NAME: 'Account_Name'
  },
  
  // Wartości picklisty Adres_w_rekordzie
  ADRES_TYPES: {
    SIEDZIBA: 'Siedziba',
    SIEDZIBA_I_FILIA: 'Siedziba i Filia',
    FILIA: 'Filia'
  },
  
  // Domyślne wartości
  DEFAULT_COUNTRY: 'Polska',
  
  // Custom module names
  MODULES: {
    GUS: 'GUS',  // Moduł GUS (repozytorium danych z systemu REGON)
    GUS_NAJWAZNIEJSZE: 'GUS_Najwazniejsze'  // Heurystyka, można zmienić
  }
};

// === INICJALIZACJA KONFIGURACJI ===
// Funkcja asynchroniczna - ładuje wszystkie zmienne organizacyjne z Zoho
async function initConfig() {
  try {
    // Importuj funkcję loadOrgVariable z zoho-sdk.js (będzie dostępna globalnie)
    if (typeof loadOrgVariable === 'function') {
      // Ładuj zmienne z grupy GOOGIE_GUS
      ORG_CONFIG.GUS_API_KEY = await loadOrgVariable('GUS_API_KEY');
      ORG_CONFIG.GUS_BACKEND_URL = await loadOrgVariable('GUS_BACKEND_URL');
      ORG_CONFIG.ZOHO_CRM_BASE_URL = await loadOrgVariable('ZOHO_CRM_BASE_URL');
      ORG_CONFIG.ZOHO_ORG_ID = await loadOrgVariable('ZOHO_ORG_ID');
      ORG_CONFIG.BRAND_LOGO_URL = await loadOrgVariable('BRAND_LOGO_URL') || 'MD_favicon.png';
      
      // Fallback dla ZOHO_CRM_BASE_URL - wykryj z URL widgetu
      if (!ORG_CONFIG.ZOHO_CRM_BASE_URL) {
        var href = window.location.href || '';
        if (href.indexOf('crm.zoho.eu') > -1) {
          ORG_CONFIG.ZOHO_CRM_BASE_URL = 'https://crm.zoho.eu';
        } else if (href.indexOf('crm.zoho.com') > -1) {
          ORG_CONFIG.ZOHO_CRM_BASE_URL = 'https://crm.zoho.com';
        } else if (href.indexOf('crm.zoho.in') > -1) {
          ORG_CONFIG.ZOHO_CRM_BASE_URL = 'https://crm.zoho.in';
        }
      }
      
      // Fallback dla GUS_BACKEND_URL - sprawdź parametr URL lub window.*
      if (!ORG_CONFIG.GUS_BACKEND_URL) {
        ORG_CONFIG.GUS_BACKEND_URL = getQueryParam('backend') || window.GOOGIE_GUS_BACKEND_URL || '';
      }
      
      // Loguj załadowaną konfigurację (z maskowaniem wrażliwych danych)
      if (typeof appendLog === 'function') {
        appendLog('[CONFIG] GUS_API_KEY: ' + (ORG_CONFIG.GUS_API_KEY ? maskKey(ORG_CONFIG.GUS_API_KEY) : '(brak)'));
        appendLog('[CONFIG] GUS_BACKEND_URL: ' + (ORG_CONFIG.GUS_BACKEND_URL || '(brak)'));
        appendLog('[CONFIG] ZOHO_CRM_BASE_URL: ' + (ORG_CONFIG.ZOHO_CRM_BASE_URL || '(auto-detect)'));
        appendLog('[CONFIG] ZOHO_ORG_ID: ' + (ORG_CONFIG.ZOHO_ORG_ID || '(brak)'));
        appendLog('[CONFIG] BRAND_LOGO_URL: ' + ORG_CONFIG.BRAND_LOGO_URL);
      }
      
      return true;
    }
  } catch (e) {
    if (typeof appendLog === 'function') {
      appendLog('[CONFIG] Błąd inicjalizacji: ' + (e && e.message ? e.message : String(e)));
    }
    return false;
  }
}

// Pomocnicza funkcja maskowania kluczy (będzie też w utils, ale tutaj dla niezależności)
function maskKey(key) {
  if (!key) return '';
  try {
    var s = String(key);
    if (s.length <= 8) return '****';
    return s.slice(0, 4) + '...' + s.slice(-4);
  } catch (_) { return '****'; }
}

// Funkcja pomocnicza do parametrów URL (będzie też dostępna z utils)
function getQueryParam(name) {
  try {
    var params = new URLSearchParams(window.location.search || '');
    var v = params.get(name) || '';
    if (v) return v;
    var hash = (window.location.hash || '').replace(/^#/, '');
    if (hash) {
      var h = new URLSearchParams(hash);
      return h.get(name) || '';
    }
  } catch(_) {}
  return '';
}

