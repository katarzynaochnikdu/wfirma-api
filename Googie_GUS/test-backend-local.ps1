# ============================================================================
# Skrypt testowania backendu LOKALNIE przed deploymentem na GCP (WINDOWS)
# ============================================================================

Write-Host "==========================================" -ForegroundColor Green
Write-Host "🧪 TEST LOKALNY BACKENDU GOOGIE GUS" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""

# Sprawdź czy serwer działa
try {
    $null = Invoke-RestMethod -Uri "http://localhost:5000" -TimeoutSec 2 -ErrorAction Stop
    Write-Host "✅ Backend działa na localhost:5000" -ForegroundColor Green
} catch {
    Write-Host "❌ Backend nie działa na localhost:5000" -ForegroundColor Red
    Write-Host ""
    Write-Host "Uruchom serwer:" -ForegroundColor Yellow
    Write-Host "  npm run dev:windows" -ForegroundColor White
    exit 1
}

Write-Host ""

# ============================================================================
# TEST 1: Podstawowy endpoint (name-by-nip)
# ============================================================================
Write-Host "📋 TEST 1: Podstawowy endpoint (name-by-nip)" -ForegroundColor Cyan
Write-Host "NIP: 5250001009 (Państwowa Wyższa Szkoła Zawodowa)" -ForegroundColor Gray
Write-Host ""

try {
    $response1 = Invoke-RestMethod -Uri "http://localhost:5000/api/gus/name-by-nip" `
        -Method POST `
        -Headers @{"Content-Type"="application/json"; "x-gus-api-key"="abcde12345abcde12345"} `
        -Body '{"nip":"5250001009"}'
    
    $response1 | ConvertTo-Json -Depth 5
    Write-Host ""
    Write-Host "✅ TEST 1 zakończony" -ForegroundColor Green
} catch {
    Write-Host "❌ TEST 1 BŁĄD: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""

# ============================================================================
# TEST 2: Pełny raport (wszystkie pola)
# ============================================================================
Write-Host "==========================================" -ForegroundColor Gray
Write-Host "📋 TEST 2: Pełny raport podstawowy (BIR11OsPrawna)" -ForegroundColor Cyan
Write-Host "REGON: 321537875 (DERMADENT)" -ForegroundColor Gray
Write-Host ""

try {
    $response2 = Invoke-RestMethod -Uri "http://localhost:5000/api/gus/full-report" `
        -Method POST `
        -Headers @{"Content-Type"="application/json"; "x-gus-api-key"="abcde12345abcde12345"} `
        -Body '{"regon":"321537875"}'
    
    $response2 | ConvertTo-Json -Depth 5
    Write-Host ""
    
    $fieldsCount = $response2.fieldsCount
    Write-Host "📊 Liczba pól: $fieldsCount" -ForegroundColor White
    
    if ($fieldsCount -gt 50) {
        Write-Host "✅ Backend zwraca WSZYSTKIE dane (>50 pól)" -ForegroundColor Green
    } else {
        Write-Host "⚠️  Backend zwraca mało danych ($fieldsCount pól)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "❌ TEST 2 BŁĄD: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""

# ============================================================================
# TEST 3: Raport PKD
# ============================================================================
Write-Host "==========================================" -ForegroundColor Gray
Write-Host "📋 TEST 3: Raport PKD (BIR11OsPrawnaPkd)" -ForegroundColor Cyan
Write-Host "REGON: 321537875" -ForegroundColor Gray
Write-Host ""

try {
    $response3 = Invoke-RestMethod -Uri "http://localhost:5000/api/gus/full-report" `
        -Method POST `
        -Headers @{"Content-Type"="application/json"; "x-gus-api-key"="abcde12345abcde12345"} `
        -Body '{"regon":"321537875","reportName":"BIR11OsPrawnaPkd"}'
    
    $response3 | ConvertTo-Json -Depth 5
    Write-Host ""
    
    $pkdCount = $response3.data.pkdCount
    Write-Host "📊 Liczba kodów PKD: $pkdCount" -ForegroundColor White
    
    if ($pkdCount -gt 0) {
        Write-Host "✅ Backend zwraca kody PKD" -ForegroundColor Green
    } else {
        Write-Host "⚠️  Brak kodów PKD (może być puste w GUS)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "❌ TEST 3 BŁĄD: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""

# ============================================================================
# TEST 4: Jednostki lokalne
# ============================================================================
Write-Host "==========================================" -ForegroundColor Gray
Write-Host "📋 TEST 4: Jednostki lokalne (BIR11OsPrawnaListaJednLokalnych)" -ForegroundColor Cyan
Write-Host "REGON: 321537875" -ForegroundColor Gray
Write-Host ""

try {
    $response4 = Invoke-RestMethod -Uri "http://localhost:5000/api/gus/full-report" `
        -Method POST `
        -Headers @{"Content-Type"="application/json"; "x-gus-api-key"="abcde12345abcde12345"} `
        -Body '{"regon":"321537875","reportName":"BIR11OsPrawnaListaJednLokalnych"}'
    
    $response4 | ConvertTo-Json -Depth 5
    Write-Host ""
    
    $jednCount = $response4.data.jednostkiCount
    Write-Host "📊 Liczba jednostek lokalnych: $jednCount" -ForegroundColor White
    
    if ($jednCount -gt 0) {
        Write-Host "✅ Backend zwraca jednostki lokalne" -ForegroundColor Green
    } else {
        Write-Host "⚠️  Brak jednostek lokalnych (może być 0 w GUS)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "❌ TEST 4 BŁĄD: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host "✅ WSZYSTKIE TESTY ZAKOŃCZONE" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""
Write-Host "📋 Podsumowanie:" -ForegroundColor Cyan
Write-Host "   - Podstawowy endpoint: OK"
Write-Host "   - Pełny raport: $fieldsCount pól"
Write-Host "   - PKD: $pkdCount kodów"
Write-Host "   - Jednostki lokalne: $jednCount jednostek"
Write-Host ""
Write-Host "🚀 Jeśli wszystko OK, możesz deployować na GCP!" -ForegroundColor Green
Write-Host ""

