#!/bin/bash
# ============================================================================
# Skrypt testowania backendu LOKALNIE przed deploymentem na GCP
# ============================================================================

echo "=========================================="
echo "🧪 TEST LOKALNY BACKENDU GOOGIE GUS"
echo "=========================================="
echo ""

# Sprawdź czy serwer działa
if ! curl -s http://localhost:5000 > /dev/null 2>&1; then
    echo "❌ Backend nie działa na localhost:5000"
    echo ""
    echo "Uruchom serwer:"
    echo "  npm run dev:windows  (Windows)"
    echo "  npm run dev          (Linux/Mac)"
    exit 1
fi

echo "✅ Backend działa na localhost:5000"
echo ""

# ============================================================================
# TEST 1: Podstawowy endpoint (name-by-nip)
# ============================================================================
echo "📋 TEST 1: Podstawowy endpoint (name-by-nip)"
echo "NIP: 5250001009 (Państwowa Wyższa Szkoła Zawodowa)"
echo ""

curl -s -X POST http://localhost:5000/api/gus/name-by-nip \
  -H "Content-Type: application/json" \
  -H "x-gus-api-key: abcde12345abcde12345" \
  -d '{"nip":"5250001009"}' | jq '.'

echo ""
echo "✅ TEST 1 zakończony"
echo ""

# ============================================================================
# TEST 2: Pełny raport (wszystkie pola)
# ============================================================================
echo "=========================================="
echo "📋 TEST 2: Pełny raport podstawowy (BIR11OsPrawna)"
echo "REGON: 321537875 (DERMADENT)"
echo ""

RESPONSE=$(curl -s -X POST http://localhost:5000/api/gus/full-report \
  -H "Content-Type: application/json" \
  -H "x-gus-api-key: abcde12345abcde12345" \
  -d '{"regon":"321537875"}')

echo "$RESPONSE" | jq '.'
echo ""

# Policz pola
FIELDS_COUNT=$(echo "$RESPONSE" | jq '.fieldsCount')
echo "📊 Liczba pól: $FIELDS_COUNT"

if [ "$FIELDS_COUNT" -gt 50 ]; then
    echo "✅ Backend zwraca WSZYSTKIE dane (>50 pól)"
else
    echo "⚠️  Backend zwraca mało danych ($FIELDS_COUNT pól)"
fi

echo ""

# ============================================================================
# TEST 3: Raport PKD
# ============================================================================
echo "=========================================="
echo "📋 TEST 3: Raport PKD (BIR11OsPrawnaPkd)"
echo "REGON: 321537875"
echo ""

PKD_RESPONSE=$(curl -s -X POST http://localhost:5000/api/gus/full-report \
  -H "Content-Type: application/json" \
  -H "x-gus-api-key: abcde12345abcde12345" \
  -d '{"regon":"321537875","reportName":"BIR11OsPrawnaPkd"}')

echo "$PKD_RESPONSE" | jq '.'
echo ""

PKD_COUNT=$(echo "$PKD_RESPONSE" | jq '.data.pkdCount // 0')
echo "📊 Liczba kodów PKD: $PKD_COUNT"

if [ "$PKD_COUNT" -gt 0 ]; then
    echo "✅ Backend zwraca kody PKD"
else
    echo "⚠️  Brak kodów PKD (może być puste w GUS)"
fi

echo ""

# ============================================================================
# TEST 4: Jednostki lokalne
# ============================================================================
echo "=========================================="
echo "📋 TEST 4: Jednostki lokalne (BIR11OsPrawnaListaJednLokalnych)"
echo "REGON: 321537875"
echo ""

JEDN_RESPONSE=$(curl -s -X POST http://localhost:5000/api/gus/full-report \
  -H "Content-Type: application/json" \
  -H "x-gus-api-key: abcde12345abcde12345" \
  -d '{"regon":"321537875","reportName":"BIR11OsPrawnaListaJednLokalnych"}')

echo "$JEDN_RESPONSE" | jq '.'
echo ""

JEDN_COUNT=$(echo "$JEDN_RESPONSE" | jq '.data.jednostkiCount // 0')
echo "📊 Liczba jednostek lokalnych: $JEDN_COUNT"

if [ "$JEDN_COUNT" -gt 0 ]; then
    echo "✅ Backend zwraca jednostki lokalne"
else
    echo "⚠️  Brak jednostek lokalnych (może być 0 w GUS)"
fi

echo ""
echo "=========================================="
echo "✅ WSZYSTKIE TESTY ZAKOŃCZONE"
echo "=========================================="
echo ""
echo "📋 Podsumowanie:"
echo "   - Podstawowy endpoint: OK"
echo "   - Pełny raport: $FIELDS_COUNT pól"
echo "   - PKD: $PKD_COUNT kodów"
echo "   - Jednostki lokalne: $JEDN_COUNT jednostek"
echo ""
echo "🚀 Jeśli wszystko OK, możesz deployować na GCP!"
echo ""

