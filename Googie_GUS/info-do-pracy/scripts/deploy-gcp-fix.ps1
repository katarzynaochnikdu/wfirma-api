# ============================================================================
# DEPLOYMENT GCP - NAPRAWIONY (wykrywa PROJECT_ID zamiast NUMBER)
# ============================================================================

param([string]$ApiKey = "")

$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Green
Write-Host "DEPLOYMENT GOOGIE GUS NA GCP (FIXED)" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""

# ============================================================================
# 1. Klucz API
# ============================================================================
if (-not [string]::IsNullOrWhiteSpace($ApiKey)) {
    $GUS_API_KEY = $ApiKey
}
elseif (-not [string]::IsNullOrWhiteSpace($env:BIR1_medidesk)) {
    $GUS_API_KEY = $env:BIR1_medidesk
    Write-Host "[OK] Klucz: BIR1_medidesk" -ForegroundColor Green
}
elseif (-not [string]::IsNullOrWhiteSpace($env:GUS_API_KEY)) {
    $GUS_API_KEY = $env:GUS_API_KEY
    Write-Host "[OK] Klucz: GUS_API_KEY" -ForegroundColor Green
}
else {
    $GUS_API_KEY = Read-Host "Wprowadz klucz GUS"
    if ([string]::IsNullOrWhiteSpace($GUS_API_KEY)) {
        Write-Host "[BLAD] Klucz wymagany" -ForegroundColor Red
        exit 1
    }
}

$keyLen = $GUS_API_KEY.Length
$masked = if ($keyLen -gt 8) { $GUS_API_KEY.Substring(0,3) + "***" + $GUS_API_KEY.Substring($keyLen-3) } else { "***" }
Write-Host "[OK] Klucz: $masked ($keyLen znakow)" -ForegroundColor Green

# ============================================================================
# 2. PROJECT_ID (nie NUMBER!)
# ============================================================================
Write-Host ""
Write-Host "Sprawdzam projekt GCP..." -ForegroundColor Cyan

$currentProject = gcloud config get-value project 2>$null
Write-Host "Aktualny projekt: $currentProject" -ForegroundColor Gray

# Sprawdz czy to NUMBER czy ID (number = tylko cyfry)
if ($currentProject -match '^\d+$') {
    Write-Host ""
    Write-Host "[UWAGA] Ustawiony jest PROJECT NUMBER ($currentProject), nie PROJECT ID!" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Pobieram liste projektow..." -ForegroundColor Cyan
    
    # Wyswietl projekty
    gcloud projects list --format="table(projectId,name,projectNumber)"
    
    Write-Host ""
    Write-Host "Znajdz projekt z numerem $currentProject w powyzszej tabeli" -ForegroundColor Yellow
    $PROJECT_ID = Read-Host "Wpisz PROJECT_ID (kolumna projectId)"
    
    if ([string]::IsNullOrWhiteSpace($PROJECT_ID)) {
        Write-Host "[BLAD] PROJECT_ID jest wymagany" -ForegroundColor Red
        exit 1
    }
    
    # Ustaw poprawny projekt
    gcloud config set project $PROJECT_ID
    Write-Host "[OK] Ustawiono projekt: $PROJECT_ID" -ForegroundColor Green
} else {
    $PROJECT_ID = $currentProject
    Write-Host "[OK] Projekt ID: $PROJECT_ID" -ForegroundColor Green
}

# ============================================================================
# 3. Konfiguracja
# ============================================================================
$SERVICE = "googie-gus-backend"
$REGION = "europe-central2"

Write-Host ""
Write-Host "Konfiguracja:" -ForegroundColor Cyan
Write-Host "  Serwis: $SERVICE"
Write-Host "  Region: $REGION"
Write-Host "  Projekt: $PROJECT_ID"
Write-Host ""

# ============================================================================
# 4. Deployment
# ============================================================================
$confirm = Read-Host "Kontynuowac deployment? (y/n)"
if ($confirm -ne "y") {
    Write-Host "[ANULOWANO]" -ForegroundColor Red
    exit 0
}

Write-Host ""
Write-Host "Deployment w toku (2-5 minut)..." -ForegroundColor Yellow
Write-Host ""

try {
    gcloud run deploy $SERVICE `
      --source . `
      --platform managed `
      --region $REGION `
      --project $PROJECT_ID `
      --allow-unauthenticated `
      --set-env-vars "NODE_ENV=production,GUS_API_KEY=$GUS_API_KEY" `
      --min-instances 0 `
      --max-instances 10 `
      --memory 512Mi `
      --timeout 60
    
    Write-Host ""
    $URL = gcloud run services describe $SERVICE --region $REGION --project $PROJECT_ID --format="value(status.url)"
    
    Write-Host ""
    Write-Host "==========================================" -ForegroundColor Green
    Write-Host "SUKCES! DEPLOYMENT ZAKONCZONY" -ForegroundColor Green
    Write-Host "==========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "URL backendu:" -ForegroundColor Cyan
    Write-Host "  $URL" -ForegroundColor White
    Write-Host ""
    Write-Host "Ustaw w Zoho CRM:" -ForegroundColor Yellow
    Write-Host "  Setup -> Organization Variables -> GUS_BACKEND_URL = $URL" -ForegroundColor White
    Write-Host ""
    Write-Host "Test:" -ForegroundColor Cyan
    Write-Host "  gcloud run services logs tail $SERVICE --region $REGION" -ForegroundColor Gray
    Write-Host ""
    
} catch {
    Write-Host ""
    Write-Host "[BLAD] Deployment nie powiodl sie: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

