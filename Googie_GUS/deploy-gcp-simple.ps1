# ============================================================================
# Skrypt automatycznego deployment na GCP Cloud Run (WINDOWS PowerShell)
# Googie GUS Backend - Wersja FULL DATA (PKD, formy prawne, jednostki)
# ============================================================================

$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Green
Write-Host "DEPLOYMENT GOOGIE GUS BACKEND NA GCP" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""

# ============================================================================
# KROK 1: Sprawdzenie srodowiska
# ============================================================================
Write-Host "Sprawdzam wymagania..." -ForegroundColor Cyan

# Sprawdz czy gcloud jest zainstalowane
try {
    $gcloudVersion = gcloud --version 2>&1 | Select-Object -First 1
    Write-Host "[OK] Google Cloud SDK zainstalowane: $gcloudVersion" -ForegroundColor Green
} catch {
    Write-Host "[BLAD] Google Cloud SDK (gcloud) nie jest zainstalowane" -ForegroundColor Red
    Write-Host "Zainstaluj z: https://cloud.google.com/sdk/docs/install" -ForegroundColor Yellow
    exit 1
}

# ============================================================================
# KROK 2: Projekt GCP
# ============================================================================
try {
    $CURRENT_PROJECT = gcloud config get-value project 2>$null
} catch {
    $CURRENT_PROJECT = ""
}

if ([string]::IsNullOrWhiteSpace($CURRENT_PROJECT)) {
    Write-Host ""
    Write-Host "Nie wykryto aktywnego projektu GCP" -ForegroundColor Yellow
    $GCP_PROJECT_ID = Read-Host "Wpisz PROJECT_ID"
    
    if ([string]::IsNullOrWhiteSpace($GCP_PROJECT_ID)) {
        Write-Host "[BLAD] PROJECT_ID jest wymagany" -ForegroundColor Red
        exit 1
    }
    
    gcloud config set project $GCP_PROJECT_ID
} else {
    $GCP_PROJECT_ID = $CURRENT_PROJECT
    Write-Host "[OK] Projekt GCP: $GCP_PROJECT_ID" -ForegroundColor Green
}

# ============================================================================
# KROK 3: Pobierz GUS_API_KEY ze zmiennych srodowiskowych (elastycznie)
# ============================================================================
Write-Host ""
Write-Host "Pobieram klucz API GUS ze zmiennych srodowiskowych..." -ForegroundColor Cyan

# Multi-fallback: sprawdz rozne nazwy zmiennych
$GUS_API_KEY = $null

# Proba 1: GUS_API_KEY (standardowa nazwa)
if (-not [string]::IsNullOrWhiteSpace($env:GUS_API_KEY)) {
    $GUS_API_KEY = $env:GUS_API_KEY
    Write-Host "[OK] Znaleziono zmienna: GUS_API_KEY" -ForegroundColor Green
}
# Proba 2: BIR1_medidesk (legacy nazwa)
elseif (-not [string]::IsNullOrWhiteSpace($env:BIR1_medidesk)) {
    $GUS_API_KEY = $env:BIR1_medidesk
    Write-Host "[OK] Znaleziono zmienna: BIR1_medidesk (legacy)" -ForegroundColor Green
}
# Proba 3: Zapytaj uzytkownika
else {
    Write-Host "[INFO] Nie znaleziono zmiennej srodowiskowej GUS_API_KEY ani BIR1_medidesk" -ForegroundColor Yellow
    Write-Host ""
    $GUS_API_KEY_INPUT = Read-Host "Wprowadz klucz API GUS"
    
    if ([string]::IsNullOrWhiteSpace($GUS_API_KEY_INPUT)) {
        Write-Host "[BLAD] GUS_API_KEY jest wymagany" -ForegroundColor Red
        Write-Host ""
        Write-Host "Ustaw zmienna srodowiskowa przed uruchomieniem:" -ForegroundColor Yellow
        Write-Host "   `$env:GUS_API_KEY = 'twoj_klucz'" -ForegroundColor Gray
        Write-Host "   .\deploy-gcp-simple.ps1" -ForegroundColor Gray
        Write-Host ""
        exit 1
    }
    
    $GUS_API_KEY = $GUS_API_KEY_INPUT
}

# Maskuj klucz dla bezpieczenstwa (pokaz tylko fragment)
$keyLength = $GUS_API_KEY.Length
$maskedKey = if ($keyLength -gt 8) { $GUS_API_KEY.Substring(0,4) + "..." + $GUS_API_KEY.Substring($keyLength-4) } else { "****" }
Write-Host "[OK] Klucz API gotowy: $maskedKey (dlugosc: $keyLength znakow)" -ForegroundColor Green

# ============================================================================
# KROK 4: Konfiguracja deployment
# ============================================================================
$SERVICE_NAME = "googie-gus-backend"
$REGION = "europe-central2"
$MEMORY = "512Mi"
$CPU = "1"
$TIMEOUT = "60"
$MIN_INSTANCES = "0"
$MAX_INSTANCES = "10"

Write-Host ""
Write-Host "Konfiguracja deployment:" -ForegroundColor Cyan
Write-Host "   Nazwa serwisu: $SERVICE_NAME"
Write-Host "   Region: $REGION"
Write-Host "   Memory: $MEMORY"
Write-Host "   CPU: $CPU"
Write-Host "   Timeout: ${TIMEOUT}s"
Write-Host "   Min instances: $MIN_INSTANCES"
Write-Host "   Max instances: $MAX_INSTANCES"
Write-Host ""

# ============================================================================
# KROK 5: Potwierdzenie
# ============================================================================
$CONFIRM = Read-Host "Kontynuowac deployment? (y/n)"

if ($CONFIRM -ne "y" -and $CONFIRM -ne "Y") {
    Write-Host "[ANULOWANO] Deployment anulowany" -ForegroundColor Red
    exit 0
}

# ============================================================================
# KROK 6: Wlacz Cloud Run API
# ============================================================================
Write-Host ""
Write-Host "Wlaczam Cloud Run API..." -ForegroundColor Cyan
try {
    gcloud services enable run.googleapis.com --project=$GCP_PROJECT_ID 2>$null
    Write-Host "[OK] Cloud Run API wlaczone" -ForegroundColor Green
} catch {
    Write-Host "[INFO] Cloud Run API juz wlaczone (kontynuuje)" -ForegroundColor Yellow
}

# ============================================================================
# KROK 7: DEPLOYMENT
# ============================================================================
Write-Host ""
Write-Host "Rozpoczynam deployment..." -ForegroundColor Green
Write-Host ""

$ENV_VARS = "NODE_ENV=production,GUS_API_KEY=$GUS_API_KEY"

gcloud run deploy $SERVICE_NAME `
  --source . `
  --platform managed `
  --region $REGION `
  --project $GCP_PROJECT_ID `
  --allow-unauthenticated `
  --set-env-vars $ENV_VARS `
  --min-instances $MIN_INSTANCES `
  --max-instances $MAX_INSTANCES `
  --memory $MEMORY `
  --cpu $CPU `
  --timeout $TIMEOUT

# ============================================================================
# KROK 8: Pobierz URL serwisu
# ============================================================================
Write-Host ""
Write-Host "Pobieram URL serwisu..." -ForegroundColor Cyan

$SERVICE_URL = gcloud run services describe $SERVICE_NAME `
  --region $REGION `
  --project $GCP_PROJECT_ID `
  --format="value(status.url)"

Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host "DEPLOYMENT ZAKONCZONY POMYSLNIE!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""
Write-Host "URL serwisu:" -ForegroundColor Cyan
Write-Host "   $SERVICE_URL" -ForegroundColor White
Write-Host ""
Write-Host "Nastepne kroki:" -ForegroundColor Cyan
Write-Host "   1. Skopiuj powyzszy URL"
Write-Host "   2. W Zoho CRM -> Setup -> Developer Space -> Organization Variables"
Write-Host "   3. Ustaw zmienna GUS_BACKEND_URL na: $SERVICE_URL"
Write-Host ""
Write-Host "Test endpointu:" -ForegroundColor Cyan
Write-Host "   curl -X POST $SERVICE_URL/api/gus/name-by-nip \"
Write-Host "     -H 'Content-Type: application/json' \"
Write-Host "     -H 'x-gus-api-key: your_key' \"
Write-Host "     -d '{`"nip`":`"5250001009`"}'"
Write-Host ""
Write-Host "Sprawdz logi:" -ForegroundColor Cyan
Write-Host "   gcloud run services logs tail $SERVICE_NAME --region $REGION"
Write-Host ""
Write-Host "==========================================" -ForegroundColor Green

