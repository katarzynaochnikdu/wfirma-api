/*
Copyright (c) 2017, ZOHO CORPORATION
License: MIT
*/
var fs = require('fs');
var path = require('path');
var express = require('express');
var bodyParser = require('body-parser');
var errorHandler = require('errorhandler');
var morgan = require('morgan');
var serveIndex = require('serve-index');
var https = require('https');
var chalk = require('chalk');
var xml2js = require('xml2js');
var rateLimit = require('express-rate-limit');

// ============================================================================
// BEZPIECZEŃSTWO: Sanityzacja XML (ochrona przed SOAP injection)
// ============================================================================

// Escape XML - zapobiega SOAP injection
// Konwertuje znaki specjalne na encje XML przed wstawieniem do SOAP envelope
function escapeXml(unsafe) {
  if (typeof unsafe !== 'string') return '';
  return unsafe
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

// Dekoduje wewnętrzny XML z GUS (przychodzi jako tekst z encjami HTML)
function decodeBirInnerXml(encoded) {
  if (typeof encoded !== 'string') {
    return '';
  }
  return encoded
    .replace(/^\ufeff/, '')
    .replace(/&amp;amp;/g, '&amp;')
    .replace(/&#xD;/gi, '\r')
    .replace(/&#xA;/gi, '\n')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&amp;/g, '&')
    .trim();
}

process.env.PWD = process.env.PWD || process.cwd();

// Ustaw domyślnie produkcję (jeśli nie określono inaczej)
process.env.NODE_ENV = process.env.NODE_ENV || 'production';

var expressApp = express();
var port = 5000;

expressApp.set('port', port);

// PRODUKCJA: mniej verbose logging, tylko błędy i warningi
// DEVELOPMENT: pełne logi każdego requesta
if (process.env.NODE_ENV === 'production') {
  expressApp.use(morgan('combined')); // Standard Apache format
} else {
  expressApp.use(morgan('dev')); // Kolorowe, szczegółowe logi
}
expressApp.use(bodyParser.json());
expressApp.use(bodyParser.urlencoded({ extended: false }));
expressApp.use(errorHandler());


// ============================================================================
// BEZPIECZEŃSTWO: Rate Limiting - ochrona przed DDoS i brute-force
// ============================================================================
var apiLimiter = rateLimit({
  windowMs: 15 * 60 * 1000, // 15 minut
  max: 100, // max 100 requestów na IP w oknie czasowym
  message: { error: 'Zbyt wiele zapytań z tego adresu IP. Spróbuj ponownie za chwilę.' },
  standardHeaders: true,
  legacyHeaders: false,
  // Dla GCP Cloud Run / proxy
  trustProxy: true
});

// Zastosuj rate limiting tylko dla API endpointów (nie dla statycznych plików)
expressApp.use('/api/gus/', apiLimiter);

// ============================================================================
// BEZPIECZEŃSTWO: HTTPS redirect (tylko produkcja)
// ============================================================================
expressApp.use(function(req, res, next) {
  if (process.env.NODE_ENV === 'production' && req.headers['x-forwarded-proto'] !== 'https') {
    return res.redirect(301, 'https://' + req.headers.host + req.url);
  }
  next();
});

// ============================================================================
// BEZPIECZEŃSTWO: Walidacja Content-Type dla POST (tylko JSON)
// ============================================================================
expressApp.use('/api/gus/', function(req, res, next) {
  if (req.method === 'POST') {
    var contentType = req.headers['content-type'] || '';
    if (contentType.indexOf('application/json') === -1) {
      return res.status(415).json({ error: 'Tylko Content-Type: application/json jest obsługiwany' });
    }
  }
  next();
});

// ============================================================================
// BEZPIECZEŃSTWO: Ograniczenie CORS do Zoho CRM domen
// ============================================================================
expressApp.use('/', function (req, res, next) {
  var allowedOrigins = [
    'https://crm.zoho.eu',
    'https://crm.zoho.com',
    'https://crm.zoho.in',
    'https://crm.zoho.com.au',
    'https://crm.zoho.jp',
    'http://127.0.0.1:5000',      // Lokalny dev (HTTP)
    'http://localhost:5000',      // Lokalny dev (HTTP)
    'https://127.0.0.1:5000',     // Lokalny dev (HTTPS)
    'https://localhost:5000'      // Lokalny dev (HTTPS)
  ];
  
  // Dodatkowe pattern-based origins (dla Zoho widget hosting)
  var allowedPatterns = [
    /^https:\/\/[a-z0-9-]+\.zappsusercontent\.eu$/,  // Zoho widget hosting EU
    /^https:\/\/[a-z0-9-]+\.zappsusercontent\.com$/  // Zoho widget hosting COM
  ];
  
  var origin = req.headers.origin || '';
  var allowed = false;
  
  // Sprawdź czy origin jest na liście dozwolonych (exact match)
  for (var i = 0; i < allowedOrigins.length; i++) {
    if (origin === allowedOrigins[i] || origin.indexOf(allowedOrigins[i]) === 0) {
      allowed = true;
      break;
    }
  }
  
  // Sprawdź czy origin pasuje do wzorca (pattern match)
  if (!allowed) {
    for (var j = 0; j < allowedPatterns.length; j++) {
      if (allowedPatterns[j].test(origin)) {
        allowed = true;
        break;
      }
    }
  }
  
  if (allowed) {
    res.setHeader('Access-Control-Allow-Origin', origin);
  }
  
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, x-gus-api-key');
  
  if (req.method === 'OPTIONS') {
    return res.status(204).send('');
  }
  
  next();
});

expressApp.get('/plugin-manifest.json', function (req, res) {
  res.sendfile('plugin-manifest.json');
});

expressApp.use('/app', express.static('app'));
expressApp.use('/app', serveIndex('app'));


expressApp.get('/', function (req, res) {
  res.redirect('/app');
});

// Globalna funkcja pomocnicza do wysyłania SOAP do BIR
// BEZPIECZEŃSTWO: Timeout z abort request (zapobiega wyciekowi pamięci)
function postSoap(birHost, envelope, sid, timeoutMs) {
      return new Promise(function(resolve, reject) {
        var body = Buffer.from(envelope, 'utf8');
        var reqOptions = {
          host: birHost,
          path: '/wsBIR/UslugaBIRzewnPubl.svc',
          method: 'POST',
          headers: {
            'Content-Type': 'application/soap+xml; charset=utf-8',
            'Accept': 'application/soap+xml',
            'User-Agent': 'Googie_GUS Widget/0.0.1',
            'Content-Length': body.length
          }
        };
        if (sid) { reqOptions.headers.sid = String(sid); }

        var timedOut = false;
        var r = https.request(reqOptions, function(resp) {
          var chunks = [];
          resp.on('data', function(d) { chunks.push(d); });
          resp.on('end', function() {
            clearTimeout(timer);
            if (timedOut) return;
            var text = Buffer.concat(chunks).toString('utf8');
            resolve({ statusCode: resp.statusCode, headers: resp.headers, text: text });
          });
        });
        
        // BEZPIECZEŃSTWO: Timeout który przerywa request i zwalnia zasoby
        var timer = setTimeout(function() {
          timedOut = true;
          r.abort(); // DODANE: Przerywa request, zwalnia socket
          reject(new Error('SOAP request timeout'));
        }, typeof timeoutMs === 'number' ? timeoutMs : 10000);
        
        r.on('error', function(err) {
          clearTimeout(timer);
          if (timedOut) return;
          reject(err);
        });
        r.write(body);
        r.end();
      });
    }

// Minimalny endpoint do integracji z GUS (BIR/REGON)
// UWAGA: Docelowe wywołania SOAP zostaną podłączone po potwierdzeniu wersji API i nazw metod.
expressApp.post('/api/gus/name-by-nip', function (req, res) {
  try {
    // BEZPIECZEŃSTWO: Walidacja długości i sanityzacja input
    var nipRaw = (req.body && req.body.nip ? String(req.body.nip).substring(0, 20) : ''); // Max 20 znaków
    var nip = nipRaw.replace(/[^0-9]/g, '');
    var fromHeaderKey = req.headers['x-gus-api-key'] ? String(req.headers['x-gus-api-key']).substring(0, 100) : '';
    var apiKey = fromHeaderKey || process.env.GUS_API_KEY || '';

    // Loguj tylko w development lub przy błędach
    if (process.env.NODE_ENV !== 'production') {
      console.log(chalk.cyan('[GUS] name-by-nip called'), { nip: nip, hasApiKey: Boolean(apiKey) });
    }

    if (!nip) {
      return res.status(400).json({ error: 'Brak NIP' });
    }
    
    if (nip.length !== 10) {
      return res.status(400).json({ error: 'NIP musi składać się z dokładnie 10 cyfr' });
    }

    if (!apiKey) {
      return res.status(400).json({
        error: 'Brak klucza GUS_API_KEY',
        hint: 'Ustaw zmienną środowiskową GUS_API_KEY lub przekaż nagłówek x-gus-api-key.'
      });
    }

    // Przełącznik TEST/PROD - domyślnie PROD (chyba że testowy klucz)
    var USE_TEST_ENV = apiKey === 'abcde12345abcde12345' || process.env.GUS_USE_TEST === 'true';
    var birHost = USE_TEST_ENV ? 'wyszukiwarkaregontest.stat.gov.pl' : 'wyszukiwarkaregon.stat.gov.pl';
    
    if (process.env.NODE_ENV !== 'production') {
      console.log(chalk.cyan('[GUS] Środowisko:'), USE_TEST_ENV ? 'TEST' : 'PROD', '(' + birHost + ')');
    }

    // 1) Zaloguj (pobierz SID) — BIR1.1 wymaga WS-Addressing
    var birUrl = 'https://' + birHost + '/wsBIR/UslugaBIRzewnPubl.svc';
    
    // BEZPIECZEŃSTWO: Escape XML dla apiKey (ochrona przed SOAP injection)
    var safeApiKey = escapeXml(apiKey);
    
    var loginEnvelope = '' +
      '<?xml version="1.0" encoding="utf-8"?>' +
      '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:ns="http://CIS/BIR/PUBL/2014/07">' +
        '<soap:Header xmlns:wsa="http://www.w3.org/2005/08/addressing">' +
          '<wsa:To>' + birUrl + '</wsa:To>' +
          '<wsa:Action>http://CIS/BIR/PUBL/2014/07/IUslugaBIRzewnPubl/Zaloguj</wsa:Action>' +
        '</soap:Header>' +
        '<soap:Body>' +
          '<ns:Zaloguj>' +
            '<ns:pKluczUzytkownika>' + safeApiKey + '</ns:pKluczUzytkownika>' +
          '</ns:Zaloguj>' +
        '</soap:Body>' +
      '</soap:Envelope>';

    postSoap(birHost, loginEnvelope, null, 10000).then(function(loginResp) {
      if (process.env.NODE_ENV !== 'production') {
        console.log(chalk.gray('[GUS] Login status'), loginResp.statusCode);
        console.log(chalk.gray('[GUS] Login response (first 800 chars)'), loginResp.text ? loginResp.text.substring(0, 800) : '');
      }
      var sidMatch = loginResp.text && loginResp.text.match(/<ZalogujResult>([^<]*)<\/ZalogujResult>/);
      var sid = sidMatch && sidMatch[1] ? sidMatch[1] : '';
      if (process.env.NODE_ENV !== 'production') {
        console.log(chalk.cyan('[GUS] Extracted SID:'), sid ? (sid.substring(0, 8) + '...') : '(empty)');
      }
      if (!sid) {
        console.error(chalk.red('[GUS] Brak SID w odpowiedzi Zaloguj'), { responseSnippet: loginResp.text ? loginResp.text.substring(0, 300) : '' });
        return res.status(502).json({ error: 'Logowanie do GUS nie powiodło się (brak SID)', debug: loginResp.text ? loginResp.text.substring(0, 300) : '' });
      }

      // Próba z przestrzeniami nazw wg WSDL: q1=http://CIS/BIR/PUBL/2014/07/DataContract
      var birUrl = 'https://' + birHost + '/wsBIR/UslugaBIRzewnPubl.svc';
      
      // BEZPIECZEŃSTWO: Escape XML dla NIP (ochrona przed SOAP injection)
      var safeNip = escapeXml(nip);
      
      var searchEnvelope = '' +
        '<?xml version="1.0" encoding="utf-8"?>' +
        '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:ns="http://CIS/BIR/PUBL/2014/07" xmlns:q1="http://CIS/BIR/PUBL/2014/07/DataContract" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">' +
          '<soap:Header xmlns:wsa="http://www.w3.org/2005/08/addressing">' +
            '<wsa:To>' + birUrl + '</wsa:To>' +
            '<wsa:Action>http://CIS/BIR/PUBL/2014/07/IUslugaBIRzewnPubl/DaneSzukajPodmioty</wsa:Action>' +
          '</soap:Header>' +
          '<soap:Body>' +
            '<ns:DaneSzukajPodmioty>' +
              '<ns:pParametryWyszukiwania>' +
                '<q1:Krs xsi:nil="true"/>' +
                '<q1:Krsy xsi:nil="true"/>' +
                '<q1:Nip>' + safeNip + '</q1:Nip>' +
                '<q1:Nipy xsi:nil="true"/>' +
                '<q1:Regon xsi:nil="true"/>' +
                '<q1:Regony14zn xsi:nil="true"/>' +
                '<q1:Regony9zn xsi:nil="true"/>' +
              '</ns:pParametryWyszukiwania>' +
            '</ns:DaneSzukajPodmioty>' +
          '</soap:Body>' +
        '</soap:Envelope>';
      
      if (process.env.NODE_ENV !== 'production') {
        console.log(chalk.gray('[GUS] Search envelope snippet:'), searchEnvelope.substring(0, 700));
      }

        return postSoap(birHost, searchEnvelope, sid, 10000).then(function(searchResp) {
        if (process.env.NODE_ENV !== 'production') {
          console.log(chalk.gray('[GUS] Search status'), searchResp.statusCode);
          console.log(chalk.gray('[GUS] Search full response length:'), searchResp.text ? searchResp.text.length : 0);
          console.log(chalk.gray('[GUS] Search response (full or first 2000 chars):'), searchResp.text ? searchResp.text.substring(0, 2000) : '');
        }
        
        // Obsługa MTOM/XOP: jeśli odpowiedź zawiera multipart, wyciągnij część SOAP
        var soapPart = searchResp.text || '';
        if (soapPart.indexOf('Content-Type: application/xop+xml') > -1) {
          // Multipart — wyciągnij część między pierwszym boundary a ostatnim
          var match = soapPart.match(/Content-Type: application\/xop\+xml[^\r\n]*\r?\n\r?\n([\s\S]*?)\r?\n--uuid:/);
          if (match && match[1]) {
            soapPart = match[1];
          }
        }
        
        // Sprawdź, czy element DaneSzukajResult istnieje i czy nie jest pusty
        if (process.env.NODE_ENV !== 'production') {
          console.log(chalk.gray('[GUS] Sprawdzam DaneSzukajResult w:'), soapPart);
        }
        var emptyResultMatch = soapPart.match(/<DaneSzukajResult\s*\/>/);
        if (process.env.NODE_ENV !== 'production') {
          console.log(chalk.gray('[GUS] Empty match:'), emptyResultMatch);
        }
        if (emptyResultMatch) {
          if (process.env.NODE_ENV !== 'production') {
            console.log(chalk.yellow('[GUS] DaneSzukajResult pusty — GUS nie znalazł podmiotu dla tego NIP'));
          }
          // Diagnostyka: pobierz KomunikatKod i KomunikatTresc
          var birUrlDiag = 'https://' + birHost + '/wsBIR/UslugaBIRzewnPubl.svc';
          var getValue = function(paramName) {
            var env = '' +
              '<?xml version="1.0" encoding="utf-8"?>' +
              '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:ns="http://CIS/BIR/2014/07">' +
                '<soap:Header xmlns:wsa="http://www.w3.org/2005/08/addressing">' +
                  '<wsa:To>' + birUrlDiag + '</wsa:To>' +
                  '<wsa:Action>http://CIS/BIR/2014/07/IUslugaBIR/GetValue</wsa:Action>' +
                '</soap:Header>' +
                '<soap:Body>' +
                  '<ns:GetValue>' +
                    '<ns:pNazwaParametru>' + paramName + '</ns:pNazwaParametru>' +
                  '</ns:GetValue>' +
                '</soap:Body>' +
              '</soap:Envelope>';
            return postSoap(birHost, env, sid, 5000).then(function(resp){
              var m = resp.text && resp.text.match(/<GetValueResult>([\s\S]*?)<\/GetValueResult>/);
              return (m && m[1]) ? m[1] : '';
            }).catch(function(){ return ''; });
          };
          return Promise.all([getValue('KomunikatKod'), getValue('KomunikatTresc')]).then(function(vals){
            if (process.env.NODE_ENV !== 'production') {
              console.log(chalk.gray('[GUS] Diagnostyka zakończona:'), { komunikatKod: vals[0] || null, komunikatTresc: vals[1] || null });
            }
            return res.status(404).json({
              error: 'GUS nie znalazł podmiotu dla podanego NIP',
              diag: { komunikatKod: vals[0] || null, komunikatTresc: vals[1] || null }
            });
          });
        }
        
        var resultMatch = soapPart.match(/<DaneSzukajPodmiotyResult>([\s\S]*?)<\/DaneSzukajPodmiotyResult>/);
        var innerXml = resultMatch && resultMatch[1] ? resultMatch[1] : '';
        if (process.env.NODE_ENV !== 'production') {
          console.log(chalk.cyan('[GUS] innerXml length:'), innerXml ? innerXml.length : 0);
          console.log(chalk.cyan('[GUS] innerXml snippet:'), innerXml ? innerXml.substring(0, 600) : '(empty)');
        }
        if (!innerXml) {
          console.error(chalk.red('[GUS] Brak danych w DaneSzukajPodmiotyResult'));
          // Diagnostyka jak wyżej
          var birUrlDiag2 = 'https://' + birHost + '/wsBIR/UslugaBIRzewnPubl.svc';
          var getValue2 = function(paramName) {
            var env2 = '' +
              '<?xml version="1.0" encoding="utf-8"?>' +
              '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:ns="http://CIS/BIR/2014/07">' +
                '<soap:Header xmlns:wsa="http://www.w3.org/2005/08/addressing">' +
                  '<wsa:To>' + birUrlDiag2 + '</wsa:To>' +
                  '<wsa:Action>http://CIS/BIR/2014/07/IUslugaBIR/GetValue</wsa:Action>' +
                '</soap:Header>' +
                '<soap:Body>' +
                  '<ns:GetValue>' +
                    '<ns:pNazwaParametru>' + paramName + '</ns:pNazwaParametru>' +
                  '</ns:GetValue>' +
                '</soap:Body>' +
              '</soap:Envelope>';
            return postSoap(birHost, env2, sid, 5000).then(function(resp){
              var m2 = resp.text && resp.text.match(/<GetValueResult>([\s\S]*?)<\/GetValueResult>/);
              return (m2 && m2[1]) ? m2[1] : '';
            }).catch(function(){ return ''; });
          };
          return Promise.all([getValue2('KomunikatKod'), getValue2('KomunikatTresc')]).then(function(vals2){
            return res.status(404).json({ 
              error: 'Brak danych dla podanego NIP',
              diag: { komunikatKod: vals2[0] || null, komunikatTresc: vals2[1] || null }
            });
          });
        }

        // Dekodujemy encje HTML zwrócone przez GUS przed parsowaniem XML
        var decodedXml = decodeBirInnerXml(innerXml);
        if (!decodedXml) {
          console.error(chalk.red('[GUS] Dekodowanie innerXml zwróciło pusty tekst'));
          return res.status(502).json({ error: 'Brak danych po dekodowaniu odpowiedzi GUS' });
        }

        // Parsuj dane (format root->dane)
        return xml2js.parseStringPromise(decodedXml).then(function(parsed) {
          var dane = parsed && parsed.root && parsed.root.dane ? parsed.root.dane : [];
          var mapped = dane.map(function(entry) {
            return {
              regon: entry.Regon ? entry.Regon[0] : null,
              nip: entry.Nip ? entry.Nip[0] : null,
              nazwa: entry.Nazwa ? entry.Nazwa[0] : null,
              wojewodztwo: entry.Wojewodztwo ? entry.Wojewodztwo[0] : null,
              powiat: entry.Powiat ? entry.Powiat[0] : null,
              gmina: entry.Gmina ? entry.Gmina[0] : null,
              miejscowosc: entry.Miejscowosc ? entry.Miejscowosc[0] : null,
              kodPocztowy: entry.KodPocztowy ? entry.KodPocztowy[0] : null,
              ulica: entry.Ulica ? entry.Ulica[0] : null,
              nrNieruchomosci: entry.NrNieruchomosci ? entry.NrNieruchomosci[0] : null,
              nrLokalu: entry.NrLokalu ? entry.NrLokalu[0] : null,
              typ: entry.Typ ? entry.Typ[0] : null,
              silosId: entry.SilosID ? entry.SilosID[0] : null,
              miejscowoscPoczty: entry.MiejscowoscPoczty ? entry.MiejscowoscPoczty[0] : null,
              krs: entry.Krs ? entry.Krs[0] : null
            };
          });
          return res.status(200).json({ data: mapped });
        }).catch(function(parseErr) {
          console.error(chalk.red('[GUS] Problem z parsowaniem XML'), parseErr);
          return res.status(502).json({ error: 'Nie udało się sparsować danych GUS', message: parseErr && parseErr.message ? parseErr.message : String(parseErr) });
        });
      });
    }).catch(function(err) {
      console.error(chalk.red('[GUS] błąd'), err && err.stack ? err.stack : err);
      return res.status(502).json({ error: 'Błąd komunikacji z GUS', message: String(err && err.message ? err.message : err) });
    });
  } catch (e) {
    console.error(chalk.red('[GUS] błąd endpointu'), e && e.stack ? e.stack : e);
    return res.status(500).json({ error: 'Błąd serwera', message: String(e && e.message ? e.message : e) });
  }
});

// Endpoint: pobierz pełny raport GUS po REGON (WSZYSTKIE DANE - nie tylko KRS!)
expressApp.post('/api/gus/full-report', function(req, res) {
  try {
    // BEZPIECZEŃSTWO: Walidacja długości i sanityzacja
    var regonRaw = (req.body && req.body.regon) ? String(req.body.regon).substring(0, 20) : '';
    var regon = regonRaw.replace(/[^0-9]/g, '');
    var fromHeaderKey = req.headers['x-gus-api-key'] ? String(req.headers['x-gus-api-key']).substring(0, 100) : '';
    var apiKey = fromHeaderKey || process.env.GUS_API_KEY || '';
    
    // NOWE: Obsługa custom reportName z frontendu
    var customReportName = (req.body && req.body.reportName) ? String(req.body.reportName).substring(0, 50) : '';
    
    if (!regon || (regon.length !== 9 && regon.length !== 14)) {
      return res.status(400).json({ error: 'REGON musi składać się z 9 lub 14 cyfr' });
    }
    
    if (!apiKey) {
      return res.status(400).json({ error: 'Brak klucza GUS_API_KEY' });
    }

    // LOG: ZAWSZE loguj żądanie (nawet w produkcji) dla debugowania
    console.log(chalk.cyan('[GUS full-report REQUEST]'), 'REGON:', regon, 'reportName:', customReportName || '(default)');
    
    if (process.env.NODE_ENV !== 'production') {
      console.log(chalk.cyan('[GUS] Pełny raport dla REGON:'), regon, 'apiKey len:', apiKey.length);
    }
    var USE_TEST_ENV = apiKey === 'abcde12345abcde12345' || process.env.GUS_USE_TEST === 'true';
    var birHost = USE_TEST_ENV ? 'wyszukiwarkaregontest.stat.gov.pl' : 'wyszukiwarkaregon.stat.gov.pl';
    if (process.env.NODE_ENV !== 'production') {
      console.log(chalk.cyan('[GUS] Środowisko (full-report):'), USE_TEST_ENV ? 'TEST' : 'PROD', '(' + birHost + ')');
    }
    
    // Zaloguj się do GUS
    var loginUrl = 'https://' + birHost + '/wsBIR/UslugaBIRzewnPubl.svc';
    
    // BEZPIECZEŃSTWO: Escape XML
    var safeApiKey = escapeXml(apiKey);
    
    var loginEnvelope = 
      '<?xml version="1.0" encoding="utf-8"?>' +
      '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:ns="http://CIS/BIR/PUBL/2014/07">' +
        '<soap:Header xmlns:wsa="http://www.w3.org/2005/08/addressing">' +
          '<wsa:To>' + loginUrl + '</wsa:To>' +
          '<wsa:Action>http://CIS/BIR/PUBL/2014/07/IUslugaBIRzewnPubl/Zaloguj</wsa:Action>' +
        '</soap:Header>' +
        '<soap:Body><ns:Zaloguj><ns:pKluczUzytkownika>' + safeApiKey + '</ns:pKluczUzytkownika></ns:Zaloguj></soap:Body>' +
      '</soap:Envelope>';

    postSoap(birHost, loginEnvelope, null, 8000).then(function(loginResp) {
      if (process.env.NODE_ENV !== 'production') {
        console.log(chalk.gray('[GUS full-report] Login status'), loginResp.statusCode);
        console.log(chalk.gray('[GUS full-report] Login response snippet:'), loginResp.text ? loginResp.text.substring(0, 500) : '');
      }
      var sidMatch = loginResp.text && loginResp.text.match(/<ZalogujResult>([\s\S]*?)<\/ZalogujResult>/);
      var sid = sidMatch && sidMatch[1] ? sidMatch[1].trim() : '';
      if (process.env.NODE_ENV !== 'production') {
        console.log(chalk.cyan('[GUS full-report] Extracted SID:'), sid ? (sid.substring(0, 8) + '...') : '(empty)');
      }
      if (!sid) {
        console.error(chalk.red('[GUS] Brak SID w odpowiedzi logowania full-report'));
        return res.status(502).json({ error: 'Logowanie do GUS nie powiodło się', debug: loginResp.text ? loginResp.text.substring(0, 300) : '' });
      }

      // ============================================================================
      // NOWE: Wsparcie dla WSZYSTKICH typów raportów GUS
      // ============================================================================
      
      // ============================================================================
      // Lista WSZYSTKICH dozwolonych raportów (whitelist dla bezpieczeństwa)
      // Źródło: Documents/GUS-Regon-UslugaBIRver1.2-dokumentacjaVer1.35/BIR11_StrukturyDanych
      // ============================================================================
      var allowedCustomReports = [
        // BIR11 - Osoby prawne (podstawowe)
        'BIR11OsPrawna',
        'BIR11OsPrawnaPkd',
        'BIR11OsPrawnaListaJednLokalnych',
        'BIR11OsPrawnaSpCywilnaWspolnicy',  // ✨ DODANE: Wspólnicy spółki cywilnej
        
        // BIR11 - Jednostki lokalne osób prawnych
        'BIR11JednLokalnaOsPrawnej',
        'BIR11JednLokalnaOsPrawnejPkd',
        
        // BIR11 - Osoby fizyczne (podstawowe)
        'BIR11OsFizycznaDaneOgolne',                      // Dane ogólne osoby fizycznej
        'BIR11OsFizycznaAdresy',                          // ✨ ADRES SIEDZIBY osoby fizycznej
        'BIR11OsFizycznaPkd',                             // PKD osoby fizycznej
        'BIR11OsFizycznaListaJednLokalnych',              // Lista jednostek lokalnych
        'BIR11OsFizycznaDzialalnoscCeidg',                // Działalność CEIDG
        'BIR11OsFizycznaDzialalnoscPozostala',            // Działalność pozostała
        'BIR11OsFizycznaDzialalnoscRolnicza',             // Działalność rolnicza
        'BIR11OsFizycznaDzialalnoscSkreslonaDo20141108',  // Działalność skreślona (historyczna)
        // UWAGA: BIR11OsFizyczna NIE ISTNIEJE w dokumentacji GUS!
        
        // BIR11 - Jednostki lokalne osób fizycznych
        'BIR11JednLokalnaOsFizycznej',
        'BIR11JednLokalnaOsFizycznejPkd',
        
        // BIR12 - Osoby prawne (nowsze wersje 2025+)
        'BIR12OsPrawna',
        'BIR12OsPrawnaPkd',
        'BIR12OsPrawnaListaJednLokalnych',
        'BIR12OsPrawnaSpCywilnaWspolnicy',  // ✨ DODANE
        
        // BIR12 - Jednostki lokalne osób prawnych
        'BIR12JednLokalnaOsPrawnej',
        'BIR12JednLokalnaOsPrawnejPkd',
        
        // BIR12 - Osoby fizyczne
        'BIR12OsFizycznaDaneOgolne',                      // Dane ogólne
        'BIR12OsFizycznaAdresy',                          // ✨ ADRES SIEDZIBY osoby fizycznej
        'BIR12OsFizycznaPkd',                             // PKD
        'BIR12OsFizycznaListaJednLokalnych',              // Lista jednostek lokalnych
        'BIR12OsFizycznaDzialalnoscCeidg',                // Działalność CEIDG
        'BIR12OsFizycznaDzialalnoscPozostala',            // Działalność pozostała
        'BIR12OsFizycznaDzialalnoscRolnicza',             // Działalność rolnicza
        'BIR12OsFizycznaDzialalnoscSkreslonaDo20141108',  // Działalność skreślona
        // UWAGA: BIR12OsFizyczna NIE ISTNIEJE w dokumentacji GUS!
        
        // BIR12 - Jednostki lokalne osób fizycznych
        'BIR12JednLokalnaOsFizycznej',
        'BIR12JednLokalnaOsFizycznejPkd'
      ];
      
      var reportName;
      
      // Jeśli frontend przekazał custom reportName i jest na whiteliście, użyj go
      if (customReportName && allowedCustomReports.indexOf(customReportName) !== -1) {
        reportName = customReportName;
        console.log(chalk.green('[GUS] Używam custom reportName:'), reportName);
      } else {
        // Domyślnie: określ typ raportu na podstawie długości REGON
        reportName = regon.length === 9 ? 'BIR11OsPrawna' : 'BIR11JednLokalnaOsPrawnej';
        if (process.env.NODE_ENV !== 'production') {
          console.log(chalk.gray('[GUS] Domyślny reportName:'), reportName);
        }
      }
      
      // BEZPIECZEŃSTWO: Escape XML dla REGON i reportName
      var safeRegon = escapeXml(regon);
      var safeReportName = escapeXml(reportName);
      
      var birUrl = 'https://' + birHost + '/wsBIR/UslugaBIRzewnPubl.svc';
      var reportEnvelope =
        '<?xml version="1.0" encoding="utf-8"?>' +
        '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:ns="http://CIS/BIR/PUBL/2014/07">' +
          '<soap:Header xmlns:wsa="http://www.w3.org/2005/08/addressing">' +
            '<wsa:To>' + birUrl + '</wsa:To>' +
            '<wsa:Action>http://CIS/BIR/PUBL/2014/07/IUslugaBIRzewnPubl/DanePobierzPelnyRaport</wsa:Action>' +
          '</soap:Header>' +
          '<soap:Body>' +
            '<ns:DanePobierzPelnyRaport>' +
              '<ns:pRegon>' + safeRegon + '</ns:pRegon>' +
              '<ns:pNazwaRaportu>' + safeReportName + '</ns:pNazwaRaportu>' +
            '</ns:DanePobierzPelnyRaport>' +
          '</soap:Body>' +
        '</soap:Envelope>';

      if (process.env.NODE_ENV !== 'production') {
        console.log(chalk.gray('[GUS full-report] Envelope dla raportu:'), reportEnvelope.substring(0, 500));
      }
      return postSoap(birHost, reportEnvelope, sid, 10000).then(function(reportResp) {
        if (process.env.NODE_ENV !== 'production') {
          console.log(chalk.gray('[GUS full-report] Report status'), reportResp.statusCode);
          console.log(chalk.gray('[GUS full-report] Report response length:'), reportResp.text ? reportResp.text.length : 0);
          console.log(chalk.gray('[GUS full-report] Report response snippet:'), reportResp.text ? reportResp.text.substring(0, 1000) : '');
        }
        
        var soapPart = reportResp.text || '';
        if (soapPart.indexOf('Content-Type: application/xop+xml') > -1) {
          var match = soapPart.match(/Content-Type: application\/xop\+xml[^\r\n]*\r?\n\r?\n([\s\S]*?)\r?\n--uuid:/);
          if (match && match[1]) soapPart = match[1];
        }

        var resultMatch = soapPart.match(/<DanePobierzPelnyRaportResult>([\s\S]*?)<\/DanePobierzPelnyRaportResult>/);
        var innerXml = resultMatch && resultMatch[1] ? resultMatch[1] : '';
        if (process.env.NODE_ENV !== 'production') {
          console.log(chalk.cyan('[GUS full-report] innerXml length:'), innerXml ? innerXml.length : 0);
          console.log(chalk.cyan('[GUS full-report] innerXml snippet:'), innerXml ? innerXml.substring(0, 800) : '(empty)');
        }
        
        if (!innerXml) {
          console.error(chalk.red('[GUS] Brak danych w DanePobierzPelnyRaportResult'));
          return res.status(404).json({ error: 'Brak danych w pełnym raporcie GUS', debug: soapPart.substring(0, 500) });
        }

        var decodedXml = decodeBirInnerXml(innerXml);
        if (process.env.NODE_ENV !== 'production') {
          console.log(chalk.cyan('[GUS full-report] decodedXml snippet:'), decodedXml ? decodedXml.substring(0, 800) : '(empty)');
        }
        
        return xml2js.parseStringPromise(decodedXml).then(function(parsed) {
          if (process.env.NODE_ENV !== 'production') {
            console.log(chalk.cyan('[GUS full-report] parsed structure:'), JSON.stringify(parsed, null, 2).substring(0, 1000));
          }
          
          // ============================================================================
          // OBSŁUGA RÓŻNYCH TYPÓW RAPORTÓW: PKD (tablica), JednLokalne (tablica), podstawowy (obiekt)
          // ============================================================================
          
          var daneArray = parsed && parsed.root && parsed.root.dane ? parsed.root.dane : [];
          
          if (process.env.NODE_ENV !== 'production') {
            console.log(chalk.cyan('[GUS full-report] dane array length:'), daneArray.length);
          }
          
          // ============================================================================
          // Sprawdź typ raportu (różne raporty zwracają różne struktury)
          // ============================================================================
          var isPkdReport = reportName && reportName.toLowerCase().indexOf('pkd') !== -1;
          var isJednLokalneReport = reportName && reportName.toLowerCase().indexOf('listajed') !== -1;
          var isWspolnicyReport = reportName && reportName.toLowerCase().indexOf('wspolnicy') !== -1;
          var isDzialalnoscReport = reportName && (
            reportName.indexOf('Dzialal') !== -1 || 
            reportName.indexOf('DaneOgolne') !== -1
          );
          
          var result = {};
          
          // ============================================================================
          // PRZYPADEK 1: Raporty PKD - zwracają TABLICĘ kodów PKD
          // ============================================================================
          if (isPkdReport) {
            console.log(chalk.magenta('[GUS DEBUG] PKD Report:'), reportName);
            console.log(chalk.magenta('[GUS DEBUG] PKD - liczba wpisów w tablicy dane:'), daneArray.length);
            
            var pkdArray = [];
            for (var idx = 0; idx < daneArray.length; idx++) {
              var pkdEntry = daneArray[idx];
              var pkdItem = {};
              
              // Konwertuj wszystkie pola z XML arrays do prostych wartości
              Object.keys(pkdEntry || {}).forEach(function(k) {
                var v = pkdEntry[k];
                pkdItem[k] = (Array.isArray(v) && v.length > 0) ? v[0] : v;
              });
              
              pkdArray.push(pkdItem);
            }
            
            console.log(chalk.magenta('[GUS DEBUG] PKD - sparsowano'), pkdArray.length, 'kodów PKD');
            if (pkdArray.length > 0) {
              console.log(chalk.magenta('[GUS DEBUG] PKD - dane (pierwsze 2000 znaków):'), JSON.stringify(pkdArray, null, 2).substring(0, 2000));
            }
            
            result.pkdList = pkdArray;
            result.pkdCount = pkdArray.length;
          }
          // ============================================================================
          // PRZYPADEK 2: Wspólnicy spółki cywilnej - zwracają TABLICĘ wspólników
          // ============================================================================
          else if (isWspolnicyReport) {
            console.log(chalk.magenta('[GUS DEBUG] Wspólnicy Report:'), reportName);
            console.log(chalk.magenta('[GUS DEBUG] Wspólnicy - liczba wpisów w tablicy dane:'), daneArray.length);
            
            var wspolnicyArray = [];
            for (var wdx = 0; wdx < daneArray.length; wdx++) {
              var wspolnikEntry = daneArray[wdx];
              var wspolnikItem = {};
              
              // Konwertuj wszystkie pola wspólnika
              Object.keys(wspolnikEntry || {}).forEach(function(k) {
                var v = wspolnikEntry[k];
                wspolnikItem[k] = (Array.isArray(v) && v.length > 0) ? v[0] : v;
              });
              
              wspolnicyArray.push(wspolnikItem);
            }
            
            console.log(chalk.magenta('[GUS DEBUG] Wspólnicy - sparsowano'), wspolnicyArray.length, 'wspólników');
            if (wspolnicyArray.length > 0) {
              console.log(chalk.magenta('[GUS DEBUG] Wspólnicy - dane (pierwsze 2000 znaków):'), JSON.stringify(wspolnicyArray, null, 2).substring(0, 2000));
            }
            
            result.wspolnicy = wspolnicyArray;
            result.wspolnicyCount = wspolnicyArray.length;
          }
          // ============================================================================
          // PRZYPADEK 3: Jednostki lokalne - zwracają TABLICĘ jednostek
          // ============================================================================
          else if (isJednLokalneReport) {
            console.log(chalk.magenta('[GUS DEBUG] Jednostki lokalne Report:'), reportName);
            console.log(chalk.magenta('[GUS DEBUG] Jednostki - liczba wpisów w tablicy dane:'), daneArray.length);
            
            var jednostkiArray = [];
            for (var jdx = 0; jdx < daneArray.length; jdx++) {
              var jednostkaEntry = daneArray[jdx];
              var jednostkaItem = {};
              
              // Konwertuj wszystkie pola
              Object.keys(jednostkaEntry || {}).forEach(function(k) {
                var v = jednostkaEntry[k];
                jednostkaItem[k] = (Array.isArray(v) && v.length > 0) ? v[0] : v;
              });
              
              jednostkiArray.push(jednostkaItem);
            }
            
            console.log(chalk.magenta('[GUS DEBUG] Jednostki - sparsowano'), jednostkiArray.length, 'jednostek');
            if (jednostkiArray.length > 0) {
              console.log(chalk.magenta('[GUS DEBUG] Jednostki - dane (pierwsze 2000 znaków):'), JSON.stringify(jednostkiArray, null, 2).substring(0, 2000));
            }
            
            result.jednostkiLokalne = jednostkiArray;
            result.jednostkiCount = jednostkiArray.length;
          }
          // ============================================================================
          // PRZYPADEK 4: Raporty działalności (Ceidg, Rolnicza, Pozostala) - mogą być tablicą LUB obiektem
          // ============================================================================
          else if (isDzialalnoscReport) {
            console.log(chalk.magenta('[GUS DEBUG] Działalność Report:'), reportName);
            console.log(chalk.magenta('[GUS DEBUG] Działalność - liczba wpisów w tablicy dane:'), daneArray.length);
            
            // Jeśli tablica ma więcej niż 1 element, zwróć jako tablicę
            if (daneArray.length > 1) {
              var dzialalnoscArray = [];
              for (var ddx = 0; ddx < daneArray.length; ddx++) {
                var dzialEntry = daneArray[ddx];
                var dzialItem = {};
                
                Object.keys(dzialEntry || {}).forEach(function(k) {
                  var v = dzialEntry[k];
                  dzialItem[k] = (Array.isArray(v) && v.length > 0) ? v[0] : v;
                });
                
                dzialalnoscArray.push(dzialItem);
              }
              
              console.log(chalk.magenta('[GUS DEBUG] Działalność - sparsowano'), dzialalnoscArray.length, 'wpisów');
              if (dzialalnoscArray.length > 0) {
                console.log(chalk.magenta('[GUS DEBUG] Działalność - dane (pierwsze 2000 znaków):'), JSON.stringify(dzialalnoscArray, null, 2).substring(0, 2000));
              }
              
              result.dzialalnosc = dzialalnoscArray;
              result.dzialalnoscCount = dzialalnoscArray.length;
            } else {
              // Jeden wpis - zwróć jako obiekt (nie tablica)
              var dane = daneArray[0] || {};
              var keys = Object.keys(dane);
              
              for (var i = 0; i < keys.length; i++) {
                var key = keys[i];
                var value = dane[key];
                result[key] = (Array.isArray(value) && value.length > 0) ? value[0] : value;
              }
              
              console.log(chalk.green('[GUS] Raport działalności - zwrócono'), Object.keys(result).length, 'pól (pojedynczy obiekt)');
            }
          }
          // ============================================================================
          // PRZYPADEK 5: Raport podstawowy (OsPrawna, OsFizyczna, JednLokalna) - WSZYSTKIE pola
          // ============================================================================
          else {
            var dane = daneArray.length > 0 ? daneArray[0] : {};
            
            if (process.env.NODE_ENV !== 'production') {
              console.log(chalk.cyan('[GUS full-report] dane keys:'), Object.keys(dane));
            }
            
            // Konwersja WSZYSTKICH pól z XML do JSON
            var keys = Object.keys(dane || {});
            
            for (var i = 0; i < keys.length; i++) {
              var key = keys[i];
              var value = dane[key];
              
              // xml2js zwraca każde pole jako tablicę - wyciągnij pierwszy element
              if (Array.isArray(value) && value.length > 0) {
                result[key] = value[0] || null;
              } else {
                result[key] = value;
              }
            }
            
            // Backward compatibility: dodaj pole 'krs' jeśli nie istnieje
            if (!result.krs && !result.praw_numerWRejestrzeEwidencji) {
              var krsCandidateKeys = [
                'praw_Krs',
                'praw_numerWRejestrzeEwidencji',
                'fiz_Krs',
                'fiz_numerwRejestrzeEwidencji',
                'fizC_numerwRejestrzeEwidencji'
              ];
              for (var j = 0; j < krsCandidateKeys.length; j++) {
                var candidateKey = krsCandidateKeys[j];
                if (result[candidateKey]) {
                  result.krs = result[candidateKey];
                  break;
                }
              }
            }
            
            console.log(chalk.green('[GUS] Raport podstawowy - zwrócono'), Object.keys(result).length, 'pól');
            
            if (process.env.NODE_ENV !== 'production') {
              console.log(chalk.cyan('[GUS] Przykładowe pola:'), Object.keys(result).slice(0, 15).join(', '));
            }
          }
          
          // ============================================================================
          // ZAWSZE dołącz nazwę raportu w odpowiedzi
          // ============================================================================
          var fieldsCount = 0;
          if (isPkdReport) {
            fieldsCount = result.pkdCount || 0;
          } else if (isWspolnicyReport) {
            fieldsCount = result.wspolnicyCount || 0;
          } else if (isJednLokalneReport) {
            fieldsCount = result.jednostkiCount || 0;
          } else if (isDzialalnoscReport && result.dzialalnosc) {
            fieldsCount = result.dzialalnoscCount || 0;
          } else {
            fieldsCount = Object.keys(result).length;
          }
          
          return res.status(200).json({ 
            data: result,
            reportName: reportName,
            fieldsCount: fieldsCount
          });
        }).catch(function(err) {
          console.error(chalk.red('[GUS] Błąd parsowania pełnego raportu'), err);
          return res.status(502).json({ error: 'Błąd parsowania pełnego raportu', message: err && err.message ? err.message : String(err) });
        });
      });
    }).catch(function(err) {
      console.error(chalk.red('[GUS] Błąd pełnego raportu'), err);
      return res.status(502).json({ error: 'Błąd komunikacji z GUS' });
    });
  } catch (e) {
    console.error(chalk.red('[GUS] Błąd endpointu full-report'), e);
    return res.status(500).json({ error: 'Błąd serwera' });
  }
});

// Render.com i GCP Cloud Run obsługują SSL - używamy HTTP
var serverPort = process.env.PORT || port;

expressApp.listen(serverPort, function () {
  console.log(chalk.green('========================================'));
  console.log(chalk.green('Googie GUS Backend uruchomiony'));
  console.log(chalk.green('========================================'));
  console.log(chalk.cyan('Port: ') + serverPort);
  console.log(chalk.cyan('Środowisko: ') + chalk.bold(process.env.NODE_ENV || 'production'));
  console.log(chalk.cyan('Rate limiting: ') + '100 req/15min/IP');
  console.log(chalk.cyan('CORS: ') + 'Tylko Zoho CRM domeny');
  console.log(chalk.cyan('HTTPS redirect: ') + (process.env.NODE_ENV === 'production' ? 'AKTYWNY' : 'wyłączony (dev)'));
  console.log(chalk.cyan('Logging: ') + (process.env.NODE_ENV === 'production' ? 'production (combined)' : 'development (verbose)'));
  console.log(chalk.green('========================================'));
}).on('error', function (err) {
  if (err.code === 'EADDRINUSE') {
    console.log(chalk.bold.red(serverPort + " port is already in use"));
  } else {
    console.error(chalk.red('Server error:'), err);
  }
});
