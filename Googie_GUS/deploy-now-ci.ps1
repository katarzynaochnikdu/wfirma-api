Param()

$ErrorActionPreference = 'Stop'

$SERVICE = 'googie-gus-backend'
$REGION  = 'europe-central2'

# Pobierz klucz API z env (preferuj BIR1_medidesk, potem GUS_API_KEY)
$API = $env:BIR1_medidesk
if (-not $API) { $API = $env:GUS_API_KEY }

if (-not $API) {
  Write-Error '[ERROR] Brak klucza API w zmiennych środowiskowych: BIR1_medidesk / GUS_API_KEY'
  exit 1
}

$envStr = "NODE_ENV=production,GUS_API_KEY=$API"

Write-Host \"[DEPLOY] Deploy na Cloud Run: service=$SERVICE region=$REGION\" -ForegroundColor Cyan

gcloud run deploy $SERVICE `
  --source . `
  --platform managed `
  --region $REGION `
  --allow-unauthenticated `
  --set-env-vars $envStr `
  --min-instances 0 `
  --max-instances 10 `
  --memory 512Mi `
  --timeout 60


