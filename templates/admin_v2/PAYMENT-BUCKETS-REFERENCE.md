# Payment Buckets - Specyfikacja Komponentu

## Przeznaczenie
Interaktywna siatka kart grupujących zamówienia według statusu płatności z możliwością zaznaczania i akcji zbiorczych.

## Lokalizacja
- **React**: `src/components/admin/PaymentBuckets.tsx`
- **HTML**: `export/_payment_buckets.html`

---

## Anatomia

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ BULK ACTIONS BAR (widoczny gdy zaznaczono elementy)                        │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ ☑ Zaznaczono: 3                    [Wyślij przypomnienie] [Oznacz opł.] │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌────────────────────────────┐    ┌────────────────────────────┐          │
│  │ ☐  🔵 Do opłacenia dziś   │    │ ☐  🔴 Przeterminowane      │          │
│  │      3 zamówienia          │    │      5 zamówień             │          │
│  │      12 450,00 zł     ⌄   │    │      8 320,00 zł       ⌄   │          │
│  ├────────────────────────────┤    ├────────────────────────────┤          │
│  │ ☐ Jan Kowalski   2 500 zł │    │ ☐ Anna Nowak     3 200 zł │          │
│  │ ☐ Piotr Wiśnia   4 800 zł │    │ ☐ Marek Zieliń.  2 100 zł │          │
│  │ ☐ Maria Kwiat.   5 150 zł │    │ ...                         │          │
│  └────────────────────────────┘    └────────────────────────────┘          │
│                                                                             │
│  ┌────────────────────────────┐    ┌────────────────────────────┐          │
│  │ ☐  🟢 Opłacone            │    │ ☐  ⚫ Anulowane            │          │
│  │      45 zamówień           │    │      2 zamówienia           │          │
│  │      89 200,00 zł     ⌄   │    │      1 500,00 zł       ⌄   │          │
│  └────────────────────────────┘    └────────────────────────────┘          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Definicja Bucketów

| ID | Label | Ikona | Kolor | Filtr |
|----|-------|-------|-------|-------|
| `due_today` | Do opłacenia dziś | `calendar-clock` | `hsl(212, 100%, 42%)` | `payment_due_date == today` |
| `overdue` | Przeterminowane | `alert-triangle` | `hsl(0, 84%, 60%)` | `payment_due_date < today && status != 'paid'` |
| `paid` | Opłacone | `check-circle` | `hsl(160, 82%, 44%)` | `status == 'paid'` |
| `cancelled` | Anulowane | `x-circle` | `hsl(220, 14%, 50%)` | `status == 'cancelled'` |

---

## CSS Classes

```css
/* Container */
.payment-buckets {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

/* Bulk Actions Bar */
.bulk-actions-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  background: hsl(212, 100%, 97%);
  border: 1px solid hsl(212, 100%, 85%);
  border-radius: var(--radius);
}

.bulk-actions-bar.hidden {
  display: none;
}

.bulk-count {
  font-size: 0.875rem;
  font-weight: 500;
  color: hsl(212, 100%, 42%);
}

.bulk-actions-buttons {
  display: flex;
  gap: 0.5rem;
}

/* Buckets Grid */
.buckets-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1rem;
}

@media (max-width: 768px) {
  .buckets-grid {
    grid-template-columns: 1fr;
  }
}

/* Bucket Card */
.bucket-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}

/* Bucket Header */
.bucket-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.875rem 1rem;
  cursor: pointer;
  transition: background 0.15s;
}

.bucket-header:hover {
  background: var(--muted);
}

.bucket-checkbox {
  width: 1rem;
  height: 1rem;
  border: 1px solid var(--border);
  border-radius: 0.25rem;
  cursor: pointer;
  flex-shrink: 0;
}

.bucket-checkbox:indeterminate {
  background: var(--primary);
  border-color: var(--primary);
}

.bucket-icon {
  width: 32px;
  height: 32px;
  border-radius: var(--radius);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.bucket-icon i {
  width: 16px;
  height: 16px;
}

/* Bucket icon variants */
.bucket-icon-due_today {
  background: hsl(212, 100%, 95%);
  color: hsl(212, 100%, 42%);
}

.bucket-icon-overdue {
  background: hsl(0, 84%, 95%);
  color: hsl(0, 84%, 50%);
}

.bucket-icon-paid {
  background: hsl(160, 82%, 95%);
  color: hsl(160, 82%, 35%);
}

.bucket-icon-cancelled {
  background: hsl(220, 14%, 93%);
  color: hsl(220, 14%, 45%);
}

.bucket-info {
  flex: 1;
  min-width: 0;
}

.bucket-label {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--foreground);
}

.bucket-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 1.25rem;
  height: 1.25rem;
  padding: 0 0.375rem;
  background: var(--muted);
  border-radius: 9999px;
  font-size: 0.6875rem;
  font-weight: 600;
}

.bucket-total {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--foreground);
  margin-left: auto;
}

.bucket-toggle {
  width: 1rem;
  height: 1rem;
  color: var(--muted-foreground);
  transition: transform 0.2s;
  flex-shrink: 0;
}

.bucket-toggle.expanded {
  transform: rotate(180deg);
}

/* Bucket Content */
.bucket-content {
  border-top: 1px solid var(--border);
  max-height: 0;
  overflow: hidden;
  transition: max-height 0.3s ease;
}

.bucket-content.expanded {
  max-height: 400px;
  overflow-y: auto;
}

/* Order Item */
.bucket-order-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.625rem 1rem;
  border-bottom: 1px solid var(--border);
  transition: background 0.15s;
}

.bucket-order-item:last-child {
  border-bottom: none;
}

.bucket-order-item:hover {
  background: hsl(210, 40%, 96%, 0.5);
}

.bucket-order-item.selected {
  background: hsl(212, 100%, 97%);
}

.order-checkbox {
  width: 1rem;
  height: 1rem;
  border: 1px solid var(--border);
  border-radius: 0.25rem;
  cursor: pointer;
  flex-shrink: 0;
}

.bucket-order-link {
  display: flex;
  flex-direction: column;
  flex: 1;
  text-decoration: none;
  color: inherit;
  min-width: 0;
}

.bucket-order-buyer {
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--foreground);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.bucket-order-event {
  font-size: 0.75rem;
  color: var(--muted-foreground);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.bucket-order-amount {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--foreground);
  flex-shrink: 0;
}
```

---

## HTML Template (Jinja2)

```html
<!-- PAYMENT BUCKETS -->
<div class="payment-buckets">
  
  <!-- Bulk Actions Bar -->
  <div id="bulk-actions-bar" class="bulk-actions-bar hidden">
    <span class="bulk-count">
      <i data-lucide="check-square" style="width: 16px; height: 16px;"></i>
      Zaznaczono: <span id="selected-count">0</span>
    </span>
    <div class="bulk-actions-buttons">
      <button class="btn btn-outline btn-sm" onclick="bulkAction('send_reminder')">
        <i data-lucide="bell"></i>
        Wyślij przypomnienie
      </button>
      <button class="btn btn-outline btn-sm" onclick="bulkAction('resend_proforma')">
        <i data-lucide="send"></i>
        Wyślij proformę
      </button>
      <button class="btn btn-primary btn-sm" onclick="bulkAction('mark_paid')">
        <i data-lucide="credit-card"></i>
        Oznacz opłacone
      </button>
    </div>
  </div>
  
  <!-- Buckets Grid -->
  <div class="buckets-grid">
    {% for bucket in buckets %}
    <div class="bucket-card" data-bucket-id="{{ bucket.id }}">
      <div class="bucket-header" onclick="toggleBucket('{{ bucket.id }}')">
        <input type="checkbox" 
               class="bucket-checkbox" 
               data-bucket="{{ bucket.id }}" 
               onclick="event.stopPropagation(); selectAllInBucket('{{ bucket.id }}', this.checked)"
               {% if bucket.orders|length == 0 %}disabled{% endif %}>
        <div class="bucket-icon bucket-icon-{{ bucket.id }}">
          <i data-lucide="{{ bucket.icon }}"></i>
        </div>
        <div class="bucket-info">
          <span class="bucket-label">{{ bucket.label }}</span>
          <span class="bucket-count">{{ bucket.orders|length }}</span>
        </div>
        <span class="bucket-total">{{ bucket.total|format_currency }}</span>
        <i data-lucide="chevron-down" class="bucket-toggle" id="toggle-{{ bucket.id }}"></i>
      </div>
      
      <div class="bucket-content" id="content-{{ bucket.id }}">
        {% for order in bucket.orders %}
        <div class="bucket-order-item" data-order-id="{{ order.order_id }}">
          <input type="checkbox" 
                 class="order-checkbox" 
                 data-order-id="{{ order.order_id }}" 
                 data-bucket="{{ bucket.id }}"
                 onchange="updateSelection()">
          <a href="{{ url_for('admin_v2_bp.order_detail', order_id=order.order_id) }}" class="bucket-order-link">
            <span class="bucket-order-buyer">{{ order.buyer_first_name }} {{ order.buyer_last_name }}</span>
            <span class="bucket-order-event">{{ order.event_name }}</span>
          </a>
          <span class="bucket-order-amount">{{ order.total|format_currency }}</span>
        </div>
        {% else %}
        <div style="padding: 1rem; text-align: center; color: var(--muted-foreground); font-size: 0.875rem;">
          Brak zamówień w tej kategorii
        </div>
        {% endfor %}
      </div>
    </div>
    {% endfor %}
  </div>
</div>
```

---

## JavaScript

```javascript
// State
const selectedOrders = new Set();

// Toggle bucket expand/collapse
function toggleBucket(bucketId) {
  const content = document.getElementById(`content-${bucketId}`);
  const toggle = document.getElementById(`toggle-${bucketId}`);
  
  content.classList.toggle('expanded');
  toggle.classList.toggle('expanded');
}

// Select all orders in a bucket
function selectAllInBucket(bucketId, checked) {
  const checkboxes = document.querySelectorAll(`.order-checkbox[data-bucket="${bucketId}"]`);
  
  checkboxes.forEach(checkbox => {
    checkbox.checked = checked;
    const orderId = checkbox.dataset.orderId;
    
    if (checked) {
      selectedOrders.add(orderId);
    } else {
      selectedOrders.delete(orderId);
    }
  });
  
  updateBulkActionsBar();
}

// Update selection state
function updateSelection() {
  selectedOrders.clear();
  
  document.querySelectorAll('.order-checkbox:checked').forEach(checkbox => {
    selectedOrders.add(checkbox.dataset.orderId);
  });
  
  // Update bucket checkboxes (indeterminate state)
  document.querySelectorAll('.bucket-checkbox').forEach(bucketCheckbox => {
    const bucketId = bucketCheckbox.dataset.bucket;
    const allCheckboxes = document.querySelectorAll(`.order-checkbox[data-bucket="${bucketId}"]`);
    const checkedCheckboxes = document.querySelectorAll(`.order-checkbox[data-bucket="${bucketId}"]:checked`);
    
    if (checkedCheckboxes.length === 0) {
      bucketCheckbox.checked = false;
      bucketCheckbox.indeterminate = false;
    } else if (checkedCheckboxes.length === allCheckboxes.length) {
      bucketCheckbox.checked = true;
      bucketCheckbox.indeterminate = false;
    } else {
      bucketCheckbox.checked = false;
      bucketCheckbox.indeterminate = true;
    }
  });
  
  updateBulkActionsBar();
}

// Update bulk actions bar visibility
function updateBulkActionsBar() {
  const bar = document.getElementById('bulk-actions-bar');
  const countEl = document.getElementById('selected-count');
  
  if (selectedOrders.size > 0) {
    bar.classList.remove('hidden');
    countEl.textContent = selectedOrders.size;
  } else {
    bar.classList.add('hidden');
  }
}

// Bulk action handler
function bulkAction(action) {
  if (selectedOrders.size === 0) return;
  
  const orderIds = Array.from(selectedOrders);
  
  let confirmMessage = '';
  switch (action) {
    case 'send_reminder':
      confirmMessage = `Wysłać przypomnienie do ${orderIds.length} zamówień?`;
      break;
    case 'resend_proforma':
      confirmMessage = `Wysłać proformę do ${orderIds.length} zamówień?`;
      break;
    case 'mark_paid':
      confirmMessage = `Oznaczyć ${orderIds.length} zamówień jako opłacone?`;
      break;
  }
  
  if (confirm(confirmMessage)) {
    fetch('/api/orders/bulk-action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, order_ids: orderIds })
    })
    .then(response => response.json())
    .then(data => {
      showToast(`Akcja wykonana dla ${orderIds.length} zamówień`, 'success');
      location.reload();
    })
    .catch(err => {
      showToast('Błąd wykonania akcji', 'error');
    });
  }
}

// Initialize on load
document.addEventListener('DOMContentLoaded', function() {
  // Auto-expand due_today and overdue buckets
  ['due_today', 'overdue'].forEach(bucketId => {
    const content = document.getElementById(`content-${bucketId}`);
    const toggle = document.getElementById(`toggle-${bucketId}`);
    if (content && content.querySelector('.bucket-order-item')) {
      content.classList.add('expanded');
      toggle.classList.add('expanded');
    }
  });
});
```

---

## Responsywność

```css
@media (max-width: 768px) {
  .buckets-grid {
    grid-template-columns: 1fr;
  }
  
  .bulk-actions-bar {
    flex-direction: column;
    gap: 0.75rem;
    align-items: stretch;
  }
  
  .bulk-actions-buttons {
    flex-direction: column;
  }
  
  .bulk-actions-buttons .btn {
    width: 100%;
  }
}
```

---

## Ikony Lucide

| Bucket | Ikona |
|--------|-------|
| due_today | `calendar-clock` |
| overdue | `alert-triangle` |
| paid | `check-circle` |
| cancelled | `x-circle` |
| Toggle | `chevron-down` |
| Bulk count | `check-square` |
