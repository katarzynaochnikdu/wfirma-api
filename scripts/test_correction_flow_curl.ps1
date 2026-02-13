# Test: faktura VAT TEST + korekta na 0 z mark_correction_settled
# Uzycie: $env:BASE_URL="https://wfirma-api.onrender.com"; $env:API_KEY="twoj_klucz"; .\scripts\test_correction_flow_curl.ps1

$BASE_URL = if ($env:BASE_URL) { $env:BASE_URL } else { "https://wfirma-api.onrender.com" }
$API_KEY = $env:API_KEY
if (-not $API_KEY) {
    Write-Host "Podaj API_KEY: `$env:API_KEY = 'twoj_MAKE_RENDER_API_KEY'" -ForegroundColor Red
    exit 1
}

Write-Host "=== 1. Tworze fakture VAT TEST ===" -ForegroundColor Cyan
$body1 = @{
    company = "test"
    nip = "5260250996"
    document_type = "normal"
    payment_status = "paid"
    invoice = @{
        positions = @(@{ name = "Test korekta flow"; quantity = 1; unit_price_net = 100; vat_rate = "23" })
    }
} | ConvertTo-Json -Depth 5

$resp1 = Invoke-RestMethod -Uri "$BASE_URL/api/workflow/create-invoice-from-nip" `
    -Method POST -Headers @{
        "Content-Type" = "application/json"
        "X-API-Key" = $API_KEY
    } -Body $body1

$INV_ID = $resp1.invoice_id
if (-not $INV_ID) {
    Write-Host "Blad: brak invoice_id. Odpowiedz:" -ForegroundColor Red
    $resp1 | ConvertTo-Json -Depth 5
    exit 1
}
Write-Host "Faktura ID: $INV_ID" -ForegroundColor Green

Write-Host "`n=== 2. Tworze korekte na 0 z mark_correction_settled=true ===" -ForegroundColor Cyan
$body2 = @{ parent_invoice_id = [int]$INV_ID; mark_correction_settled = $true } | ConvertTo-Json
$resp2 = Invoke-RestMethod -Uri "$BASE_URL/api/test/correction-payment-flow" `
    -Method POST -Headers @{
        "Content-Type" = "application/json"
        "X-API-Key" = $API_KEY
    } -Body $body2

Write-Host "Korekta:" -ForegroundColor Green
$resp2 | ConvertTo-Json -Depth 3
Write-Host "`nSprawdz w wFirma czy korekta ma platnosc jako rozliczona." -ForegroundColor Yellow
