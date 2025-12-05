// ============================================================================
// data-mapper.js - Mapowanie danych GUS → Zoho CRM
// ============================================================================
// Transformacja danych z API GUS do formatu pól Zoho CRM
// Obsługa logiki Billing/Shipping w zależności od cechy "Adres_w_rekordzie"
// ============================================================================

// Buduje pełny adres ulicy z części (ulica + nr budynku + nr lokalu)
// Parametr: gusData - obiekt z danymi z GUS
// Zwraca: string z pełnym adresem lub '-'
function buildFullAddress(gusData) {
  if (!gusData) return '-';
  
  var parts = [];
  if (gusData.ulica) parts.push(gusData.ulica);
  if (gusData.nrNieruchomosci) {
    var addr = gusData.nrNieruchomosci;
    if (gusData.nrLokalu) addr += '/' + gusData.nrLokalu;
    parts.push(addr);
  }
  
  return parts.join(' ') || '-';
}

// Mapuje dane z GUS do struktury pól Zoho CRM (Billing_*)
// Parametry:
//   gusData - obiekt z danymi pobranymi z GUS
// Zwraca: obiekt z kluczami = API names pól CRM, wartości = dane do zapisu
function buildFieldMap(gusData) {
  if (!gusData) return {};
  
  var fieldMap = {};
  
  // Nazwa firmy (uppercase)
  fieldMap[CONSTANTS.FIELDS.ACCOUNT_NAME] = (gusData.nazwa || '').toUpperCase();
  
  // Numery identyfikacyjne (NIP BEZ myślników - czysty ciąg cyfr)
  fieldMap[CONSTANTS.FIELDS.FIRMA_NIP] = gusData.nip ? cleanNIP(gusData.nip) : '';
  fieldMap[CONSTANTS.FIELDS.FIRMA_REGON] = gusData.regon || '';
  fieldMap[CONSTANTS.FIELDS.FIRMA_KRS] = gusData.krs || '';
  
  // Adres Billing (zawsze)
  fieldMap[CONSTANTS.FIELDS.BILLING_STREET] = buildFullAddress(gusData);
  fieldMap[CONSTANTS.FIELDS.BILLING_STREET_NAME] = gusData.ulica || '';
  fieldMap[CONSTANTS.FIELDS.BILLING_BUILDING_NUMBER] = gusData.nrNieruchomosci || '';
  fieldMap[CONSTANTS.FIELDS.BILLING_LOCAL_NUMBER] = gusData.nrLokalu || '';
  fieldMap[CONSTANTS.FIELDS.BILLING_CITY] = gusData.miejscowosc || '';
  fieldMap[CONSTANTS.FIELDS.BILLING_CODE] = gusData.kodPocztowy ? formatZipCode(gusData.kodPocztowy) : '';
  fieldMap[CONSTANTS.FIELDS.BILLING_STATE] = (gusData.wojewodztwo || '').toLowerCase();
  fieldMap[CONSTANTS.FIELDS.BILLING_POWIAT] = gusData.powiat || '';
  fieldMap[CONSTANTS.FIELDS.BILLING_GMINA] = gusData.gmina || '';
  fieldMap[CONSTANTS.FIELDS.BILLING_COUNTRY] = CONSTANTS.DEFAULT_COUNTRY;
  
  return fieldMap;
}

// Kopiuje pola Billing_* do Shipping_* (dla "Siedziba i Filia")
// Parametr: apiData - obiekt z danymi do zapisu (modyfikowany in-place)
// Zwraca: apiData (z dodanymi polami Shipping_*)
function mirrorBillingToShipping(apiData) {
  if (!apiData) return apiData;
  
  var mirrorPairs = {
    'Billing_Street': 'Shipping_Street',
    'Billing_Street_Name': 'Shipping_Street_Name',
    'Billing_Building_Number': 'Shipping_Building_Number',
    'Billing_Local_Number': 'Shipping_Local_Number',
    'Billing_City': 'Shipping_City',
    'Billing_Code': 'Shipping_Code',
    'Billing_State': 'Shipping_State',
    'Billing_Powiat': 'Shipping_Powiat',
    'Billing_Gmina': 'Shipping_Gmina',
    'Billing_Country': 'Shipping_Country'
  };
  
  Object.keys(mirrorPairs).forEach(function(billingKey) {
    if (apiData.hasOwnProperty(billingKey)) {
      var shippingKey = mirrorPairs[billingKey];
      apiData[shippingKey] = apiData[billingKey];
    }
  });
  
  return apiData;
}

// Zbiera zaznaczone pola z formularza (checkboxy)
// Parametr: fieldMap - mapa wszystkich możliwych pól (klucz = API name, wartość = dane)
// Zwraca: obiekt zawierający tylko pola zaznaczone przez użytkownika
function getSelectedFields(fieldMap) {
  if (!fieldMap) return {};
  
  var apiData = {};
  var checkboxes = document.querySelectorAll('[data-field]');
  
  for (var i = 0; i < checkboxes.length; i++) {
    var checkbox = checkboxes[i];
    if (checkbox.checked) {
      var fieldName = checkbox.getAttribute('data-field');
      if (fieldMap.hasOwnProperty(fieldName)) {
        apiData[fieldName] = fieldMap[fieldName];
      }
    }
  }
  
  return apiData;
}

// Przygotowuje dane do zapisu w Zoho CRM
// Parametry:
//   gusData - dane pobrane z GUS
//   adresType - typ adresu z picklisty (Siedziba, Siedziba i Filia, Filia)
// Zwraca: { apiData: object, selectedCount: number }
function prepareDataForSave(gusData, adresType) {
  // Buduj mapę wszystkich dostępnych pól
  var fieldMap = buildFieldMap(gusData);
  
  // Dodaj pola Shipping jeśli "Siedziba i Filia"
  if (adresType === CONSTANTS.ADRES_TYPES.SIEDZIBA_I_FILIA) {
    fieldMap = Object.assign(fieldMap, {
      'Shipping_Street': buildFullAddress(gusData),
      'Shipping_Street_Name': gusData.ulica || '',
      'Shipping_Building_Number': gusData.nrNieruchomosci || '',
      'Shipping_Local_Number': gusData.nrLokalu || '',
      'Shipping_City': gusData.miejscowosc || '',
      'Shipping_Code': gusData.kodPocztowy ? formatZipCode(gusData.kodPocztowy) : '',
      'Shipping_State': (gusData.wojewodztwo || '').toLowerCase(),
      'Shipping_Powiat': gusData.powiat || '',
      'Shipping_Gmina': gusData.gmina || '',
      'Shipping_Country': CONSTANTS.DEFAULT_COUNTRY
    });
  }
  
  // Zbierz tylko zaznaczone pola
  var apiData = getSelectedFields(fieldMap);
  
  // Jeśli "Siedziba i Filia" - upewnij się, że Shipping jest zsynchronizowane
  if (adresType === CONSTANTS.ADRES_TYPES.SIEDZIBA_I_FILIA) {
    apiData = mirrorBillingToShipping(apiData);
  }
  
  return {
    apiData: apiData,
    selectedCount: Object.keys(apiData).length,
    fieldMap: fieldMap  // Zwracamy też pełną mapę (dla UI)
  };
}

