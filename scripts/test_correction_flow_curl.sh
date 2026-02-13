#!/bin/bash
# Test: faktura VAT TEST + korekta na 0 z mark_correction_settled
# Wymaga: BASE_URL (np. https://wfirma-api.onrender.com), API_KEY, company=test z tokenem
# Użycie: BASE_URL=... API_KEY=... ./scripts/test_correction_flow_curl.sh

set -e
BASE_URL="${BASE_URL:-https://wfirma-api.onrender.com}"
API_KEY="${API_KEY:?Podaj API_KEY (MAKE_RENDER_API_KEY)}"

echo "=== 1. Tworzę fakturę VAT TEST ==="
RESP1=$(curl -s -X POST "$BASE_URL/api/workflow/create-invoice-from-nip" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{
    "company": "test",
    "nip": "5260250996",
    "document_type": "normal",
    "payment_status": "paid",
    "invoice": {
      "positions": [{"name": "Test korekta flow", "quantity": 1, "unit_price_net": 100, "vat_rate": "23"}]
    }
  }')

echo "$RESP1" | python3 -m json.tool 2>/dev/null || echo "$RESP1"

INV_ID=$(echo "$RESP1" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('invoice_id') or d.get('invoice',{}).get('id') or '')" 2>/dev/null || true)
if [ -z "$INV_ID" ]; then
  echo "Błąd: nie uzyskano invoice_id. Sprawdź odpowiedź powyżej."
  exit 1
fi
echo "Faktura ID: $INV_ID"

echo ""
echo "=== 2. Tworzę korektę na 0 z mark_correction_settled=true ==="
RESP2=$(curl -s -X POST "$BASE_URL/api/test/correction-payment-flow" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d "{\"parent_invoice_id\": $INV_ID, \"mark_correction_settled\": true}")

echo "$RESP2" | python3 -m json.tool 2>/dev/null || echo "$RESP2"
echo ""
echo "Sprawdź w wFirma czy korekta ma płatność jako rozliczoną."
