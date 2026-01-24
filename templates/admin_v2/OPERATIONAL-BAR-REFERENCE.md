# Operational Bar - Specyfikacja Komponentu

## Przeznaczenie
Trzykolumnowy pasek statusu wyświetlający kluczowe informacje operacyjne zamówienia z szybkimi akcjami.

## Lokalizacja
- **React**: `src/components/admin/OperationalBar.tsx`
- **HTML**: `export/order_detail.html` (sekcja `<!-- OPERATIONAL BAR -->`)

---

## Anatomia

```
┌──────────────────────────────────────────────────────────────────────────┐
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐           │
│  │ 💳 PŁATNOŚĆ     │  │ 📄 DOKUMENTY    │  │ ✉️ KOMUNIKACJA  │           │
│  │   ○ Opłacone    │  │   ○ Faktura VAT │  │   ○ Wysłano     │           │
│  │   • 2 dni temu  │  │   • FV/2025/001 │  │   • dziś 14:30  │           │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘           │
├──────────────────────────────────────────────────────────────────────────┤
│  [ Wyślij proformę ]  [ Oznacz opłacone ]  [ Korekta danych ]            │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Warianty statusów

### Payment Status
| Status | Kolor | Ikona statusowa | Opis |
|--------|-------|-----------------|------|
| `success` | emerald | `check-circle` | Opłacone |
| `warning` | amber | `clock` | Oczekuje na płatność |
| `error` | red | `x-circle` | Płatność nieudana / Anulowana |
| `neutral` | slate | `minus-circle` | Zwrot / FOC |

### Document Status
| Status | Kolor | Ikona statusowa | Opis |
|--------|-------|-----------------|------|
| `success` | emerald | `check-circle` | Faktura wystawiona |
| `warning` | amber | `clock` | Proforma wysłana |
| `neutral` | slate | `file-x` | Brak dokumentów |

### Email Status
| Status | Kolor | Ikona statusowa | Opis |
|--------|-------|-----------------|------|
| `success` | emerald | `check-circle` | Dostarczono |
| `warning` | amber | `clock` | W trakcie wysyłki |
| `error` | red | `alert-triangle` | Błąd wysyłki |
| `neutral` | slate | `mail-x` | Nie wysłano |

---

## Mapowanie Tailwind → CSS

| Tailwind | CSS Variable / Value |
|----------|---------------------|
| `bg-emerald-50` | `hsl(160, 82%, 96%)` |
| `border-emerald-200` | `hsl(160, 82%, 80%)` |
| `text-emerald-700` | `hsl(160, 82%, 30%)` |
| `bg-amber-50` | `hsl(38, 92%, 95%)` |
| `border-amber-200` | `hsl(38, 92%, 75%)` |
| `text-amber-700` | `hsl(38, 92%, 35%)` |
| `bg-red-50` | `hsl(0, 84%, 96%)` |
| `border-red-200` | `hsl(0, 84%, 80%)` |
| `text-red-700` | `hsl(0, 84%, 40%)` |
| `bg-slate-100` | `hsl(220, 14%, 96%)` |
| `border-slate-200` | `hsl(220, 14%, 85%)` |
| `text-slate-600` | `hsl(220, 14%, 40%)` |

---

## CSS Classes

```css
/* Container */
.operational-bar {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.75rem;
  margin-bottom: 1rem;
}

/* Status Badge */
.operational-status-badge {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  border-radius: var(--radius);
  border: 1px solid;
}

/* Variants */
.operational-status-success {
  background: hsl(160, 82%, 96%);
  border-color: hsl(160, 82%, 80%);
  color: hsl(160, 82%, 30%);
}

.operational-status-warning {
  background: hsl(38, 92%, 95%);
  border-color: hsl(38, 92%, 75%);
  color: hsl(38, 92%, 35%);
}

.operational-status-error {
  background: hsl(0, 84%, 96%);
  border-color: hsl(0, 84%, 80%);
  color: hsl(0, 84%, 40%);
}

.operational-status-neutral {
  background: hsl(220, 14%, 96%);
  border-color: hsl(220, 14%, 85%);
  color: hsl(220, 14%, 40%);
}

/* Icon container */
.operational-icon-wrapper {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: currentColor;
  opacity: 0.15;
}

.operational-icon-wrapper i {
  width: 20px;
  height: 20px;
}

/* Content */
.operational-status-content {
  flex: 1;
}

.operational-status-label {
  font-size: 0.6875rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  opacity: 0.8;
}

.operational-status-value {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.875rem;
  font-weight: 500;
}

.operational-status-value i {
  width: 14px;
  height: 14px;
}

.operational-status-detail {
  font-size: 0.75rem;
  opacity: 0.7;
}

/* Quick Actions */
.operational-actions {
  display: flex;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  background: var(--muted);
  border-radius: var(--radius);
  margin-bottom: 1.5rem;
}

.operational-actions .btn {
  flex: 1;
}
```

---

## HTML Template (Jinja2)

```html
<!-- OPERATIONAL BAR -->
<div class="operational-bar">
  <!-- Payment Status -->
  <div class="operational-status-badge operational-status-{{ payment_status.type }}">
    <div class="operational-icon-wrapper">
      <i data-lucide="credit-card"></i>
    </div>
    <div class="operational-status-content">
      <span class="operational-status-label">Płatność</span>
      <div class="operational-status-value">
        <i data-lucide="{{ payment_status.icon }}"></i>
        <span>{{ payment_status.label }}</span>
      </div>
      {% if payment_status.detail %}
      <span class="operational-status-detail">{{ payment_status.detail }}</span>
      {% endif %}
    </div>
  </div>
  
  <!-- Document Status -->
  <div class="operational-status-badge operational-status-{{ document_status.type }}">
    <div class="operational-icon-wrapper">
      <i data-lucide="file-text"></i>
    </div>
    <div class="operational-status-content">
      <span class="operational-status-label">Dokumenty</span>
      <div class="operational-status-value">
        <i data-lucide="{{ document_status.icon }}"></i>
        <span>{{ document_status.label }}</span>
      </div>
      {% if document_status.detail %}
      <span class="operational-status-detail">{{ document_status.detail }}</span>
      {% endif %}
    </div>
  </div>
  
  <!-- Email Status -->
  <div class="operational-status-badge operational-status-{{ email_status.type }}">
    <div class="operational-icon-wrapper">
      <i data-lucide="mail"></i>
    </div>
    <div class="operational-status-content">
      <span class="operational-status-label">Komunikacja</span>
      <div class="operational-status-value">
        <i data-lucide="{{ email_status.icon }}"></i>
        <span>{{ email_status.label }}</span>
      </div>
      {% if email_status.detail %}
      <span class="operational-status-detail">{{ email_status.detail }}</span>
      {% endif %}
    </div>
  </div>
</div>

<!-- Quick Actions -->
<div class="operational-actions">
  <button class="btn btn-outline" {% if not can_send_proforma %}disabled{% endif %} onclick="sendProforma()">
    <i data-lucide="send"></i>
    Wyślij proformę
  </button>
  <button class="btn btn-primary" {% if not can_mark_paid %}disabled{% endif %} onclick="markAsPaid()">
    <i data-lucide="credit-card"></i>
    Oznacz opłacone
  </button>
  <button class="btn btn-outline" onclick="openCorrectionModal()">
    <i data-lucide="edit"></i>
    Korekta danych
  </button>
</div>
```

---

## JavaScript Handlers

```javascript
function sendProforma() {
  if (confirm('Czy na pewno chcesz wysłać proformę?')) {
    fetch(`/api/orders/${orderId}/send-proforma`, { method: 'POST' })
      .then(response => response.json())
      .then(data => {
        showToast('Proforma została wysłana', 'success');
        location.reload();
      })
      .catch(err => showToast('Błąd wysyłki proformy', 'error'));
  }
}

function markAsPaid() {
  if (confirm('Czy na pewno chcesz oznaczyć zamówienie jako opłacone?')) {
    fetch(`/api/orders/${orderId}/mark-paid`, { method: 'POST' })
      .then(response => response.json())
      .then(data => {
        showToast('Zamówienie zostało oznaczone jako opłacone', 'success');
        location.reload();
      })
      .catch(err => showToast('Błąd zmiany statusu', 'error'));
  }
}

function openCorrectionModal() {
  document.getElementById('correction-modal').style.display = 'flex';
}
```

---

## Ikony Lucide

| Kontekst | Ikona główna | Ikony statusowe |
|----------|--------------|-----------------|
| Płatność | `credit-card` | `check-circle`, `clock`, `x-circle`, `minus-circle` |
| Dokumenty | `file-text` | `check-circle`, `clock`, `file-x` |
| Email | `mail` | `check-circle`, `clock`, `alert-triangle`, `mail-x` |

---

## Responsywność

```css
@media (max-width: 768px) {
  .operational-bar {
    grid-template-columns: 1fr;
  }
  
  .operational-actions {
    flex-direction: column;
  }
  
  .operational-actions .btn {
    width: 100%;
  }
}
```
