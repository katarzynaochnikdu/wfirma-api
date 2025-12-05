# ============================================================================
# SZYBKI DEPLOYMENT NA GCP - z parametrem lub ze zmiennej srodowiskowej
# ============================================================================
# Uzycie:
#   .\deploy-gcp-now.ps1 -ApiKey "twoj_klucz"
#   LUB
#   .\deploy-gcp-now.ps1  (pobierze z $env:BIR1_medidesk lub $env:GUS_API_KEY)
# ============================================================================

param(
    [string]$ApiKey = ""
)

$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Green
Write-Host "DEPLOYMENT GOOGIE GUS NA GCP" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""

# ============================================================================
# Pobierz klucz API (parametr > env BIR1_medidesk > env GUS_API_KEY > pytaj)
# ============================================================================

if (-not [string]::IsNullOrWhiteSpace($ApiKey)) {
    $GUS_API_KEY = $ApiKey
    Write-Host "[OK] Klucz API z parametru skryptu" -ForegroundColor Green
}
elseif (-not [string]::IsNullOrWhiteSpace($env:BIR1_medidesk)) {
    $GUS_API_KEY = $env:BIR1_medidesk
    Write-Host "[OK] Klucz API ze zmiennej: BIR1_medidesk" -ForegroundColor Green
}
elseif (-not [string]::IsNullOrWhiteSpace($env:GUS_API_KEY)) {
    $GUS_API_KEY = $env:GUS_API_KEY
    Write-Host "[OK] Klucz API ze zmiennej: GUS_API_KEY" -ForegroundColor Green
}
else {
    Write-Host "[INFO] Brak zmiennej srodowiskowej" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Dostepne zmienne srodowiskowe:" -ForegroundColor Gray
    Write-Host "  BIR1_medidesk = $env:BIR1_medidesk"
    Write-Host "  GUS_API_KEY = $env:GUS_API_KEY"
    Write-Host ""
    $GUS_API_KEY = Read-Host "Wprowadz klucz API GUS"
    
    if ([string]::IsNullOrWhiteSpace($GUS_API_KEY)) {
        Write-Host "[BLAD] Klucz jest wymagany!" -ForegroundColor Red
        exit 1
    }
}

# Pokaz zamaskowany klucz
$keyLen = $GUS_API_KEY.Length
$masked = if ($keyLen -gt 8) { $GUS_API_KEY.Substring(0,3) + "****" + $GUS_API_KEY.Substring($keyLen-3) } else { "****" }
Write-Host "[OK] Klucz: $masked (dlugosc: $keyLen)" -ForegroundColor Green

# ============================================================================
# Projekt GCP
# ============================================================================
try {
    $PROJECT = gcloud config get-value project 2>$null
    if ([string]::IsNullOrWhiteSpace($PROJECT)) {
        Write-Host "[BLAD] Nie wykryto projektu GCP" -ForegroundColor Red
        Write-Host "Ustaw projekt: gcloud config set project PROJECT_ID" -ForegroundColor Yellow
        exit 1
    }
    Write-Host "[OK] Projekt: $PROJECT" -ForegroundColor Green
} catch {
    Write-Host "[BLAD] gcloud nie dziala" -ForegroundColor Red
    exit 1
}

# ============================================================================
# Konfiguracja
# ============================================================================
$SERVICE = "googie-gus-backend"
$REGION = "europe-central2"

Write-Host ""
Write-Host "Konfiguracja:" -ForegroundColor Cyan
Write-Host "  Serwis: $SERVICE"
Write-Host "  Region: $REGION"
Write-Host "  Projekt: $PROJECT"
Write-Host ""

# ============================================================================
# Potwierdzenie
# ============================================================================
$confirm = Read-Host "Kontynuowac? (y/n)"
if ($confirm -ne "y") {
    Write-Host "[ANULOWANO]" -ForegroundColor Red
    exit 0
}

# ============================================================================
# DEPLOYMENT
# ============================================================================
Write-Host ""
Write-Host "Rozpoczynam deployment (moze potrwac 2-5 minut)..." -ForegroundColor Yellow
Write-Host ""

try {
    gcloud run deploy $SERVICE `
      --source . `
      --platform managed `
      --region $REGION `
      --allow-unauthenticated `
      --set-env-vars "NODE_ENV=production,GUS_API_KEY=$GUS_API_KEY" `
      --min-instances 0 `
      --max-instances 10 `
      --memory 512Mi `
      --timeout 60
    
    # Pobierz URL
    Write-Host ""
    $URL = gcloud run services describe $SERVICE --region $REGION --format="value(status.url)"
    
    Write-Host ""
    Write-Host "==========================================" -ForegroundColor Green
    Write-Host "SUKCES!" -ForegroundColor Green
    Write-Host "==========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "URL: $URL" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "W Zoho CRM ustaw:" -ForegroundColor Yellow
    Write-Host "  GUS_BACKEND_URL = $URL" -ForegroundColor White
    Write-Host ""
    
} catch {
    Write-Host ""
    Write-Host "[BLAD] Deployment nie powiodl sie" -ForegroundColor Red
    Write-Host "Szczegoly: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

