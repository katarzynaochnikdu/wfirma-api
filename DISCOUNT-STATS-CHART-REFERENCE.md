# Discount Stats Chart - Specyfikacja Komponentu

## Przeznaczenie
Wizualizacja przychodów i uczestników per kod rabatowy z podziałem na status płatności (opłacony/oczekujący/przeterminowany). Każdy wiersz to accordion rozwijany ze szczegółami zamówień/uczestników.

## Lokalizacja
- **React**: `src/components/admin/DiscountStatsChart.tsx`
- **Typy**: `src/types/discount-stats.ts`
- **Mock Data**: `src/lib/mock-data/discount-stats.ts`

---

## Anatomia Główna

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ CARD CONTAINER                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│ HEADER                                                                      │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ [Icon] Przychód per kod rabatowy        ● Opłacony ● Oczekujący ● Przet.│ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────────────────┤
│ CONTENT (Accordion)                                                         │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ ACCORDION ITEM (collapsed)                                              │ │
│ │ ┌─────────────────────────────────────────────────────────────────────┐ │ │
│ │ │ Bez rabatu   [████████████████████░░░░░░░░]  68 500 zł  +12 300 zł │ │ │
│ │ └─────────────────────────────────────────────────────────────────────┘ │ │
│ ├─────────────────────────────────────────────────────────────────────────┤ │
│ │ ACCORDION ITEM (expanded)                                 [border-red]  │ │
│ │ ┌─────────────────────────────────────────────────────────────────────┐ │ │
│ │ │ EARLY20      [███████████████░░░░░░░█]      42 000 zł  +8 400 zł  ▼ │ │ │
│ │ ├─────────────────────────────────────────────────────────────────────┤ │ │
│ │ │ STATS BAR                                                           │ │ │
│ │ │ Zamówienia: 36  Opłacone: 30  Oczekujące: 4  Przet.: 2  Rabat: -12k │ │ │
│ │ ├─────────────────────────────────────────────────────────────────────┤ │ │
│ │ │ ORDER ROW                                                           │ │ │
│ │ │ ┌─────────────────────────────────────────────────────────────────┐ │ │ │
│ │ │ │ Kate Brown              1 400 zł       [✓ Opłacone]         > │ │ │ │
│ │ │ │ kate@mail.com           2025-01-12                             │ │ │ │
│ │ │ └─────────────────────────────────────────────────────────────────┘ │ │ │
│ │ │ ┌─────────────────────────────────────────────────────────────────┐ │ │ │
│ │ │ │ Agnes Taylor            1 400 zł       [◷ Oczekujące]       > │ │ │ │
│ │ │ │ agnes@company.com       2025-01-20                             │ │ │ │
│ │ │ └─────────────────────────────────────────────────────────────────┘ │ │ │
│ │ │ ┌─────────────────────────────────────────────────────────────────┐ │ │ │
│ │ │ │ Robert Davis            1 400 zł       [⚠ 14 dni]           > │ │ │ │
│ │ │ │ robert@biz.co           2025-01-05                             │ │ │ │
│ │ │ └─────────────────────────────────────────────────────────────────┘ │ │ │
│ │ └─────────────────────────────────────────────────────────────────────┘ │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────────────────┤
│ FOOTER                                                                      │
│ Suma (139 zamówień)                        187 300 zł  +41 300 zł           │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Anatomia Szczegółowa: Stacked Bar

```
STACKED BAR (3 segmenty)
┌────────────────────────────────────────────────────────────────┐
│                                                                │
│ ┌──────────────────────────┬─────────────┬────────┐            │
│ │ ██████████████████████████│█████████████│████████│            │
│ │        PAID (green)       │PENDING (amb)│OVERDUE │            │
│ │        bg-success         │ bg-warning  │bg-destr│            │
│ └──────────────────────────┴─────────────┴────────┘            │
│                                                                │
│ Height: 24px (h-6)                                             │
│ Border-radius: 4px (rounded)                                   │
│ Background (empty): bg-muted                                   │
│                                                                │
│ Szerokość segmentów = (wartość / maxValue) * 100%              │
└────────────────────────────────────────────────────────────────┘
```

### Wariant FOC (Free of Charge)
```
┌────────────────────────────────────────────────────────────────┐
│ ┌────────────────────────────────────────────────────────────┐ │
│ │                          FOC                               │ │
│ │                    bg-slate-200                            │ │
│ │               text-slate-600 text-xs                       │ │
│ └────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

---

## CSS Variables (Colors)

```css
:root {
  /* Status Colors - HSL format */
  --success: 142 76% 36%;           /* Green - Opłacony */
  --warning: 38 92% 50%;            /* Amber - Oczekujący */
  --destructive: 0 84% 60%;         /* Red - Przeterminowany */
  
  /* Status Backgrounds (10% opacity) */
  --success-bg: 142 76% 95%;
  --warning-bg: 38 92% 95%;
  --destructive-bg: 0 84% 95%;
  
  /* Neutral */
  --muted: 210 40% 96%;             /* Empty bar track */
  --muted-foreground: 215 16% 47%;
  --border: 214 32% 91%;
  --foreground: 222 47% 11%;
  
  /* Card */
  --card: 0 0% 100%;
  --card-foreground: 222 47% 11%;
  
  /* Slate (for FOC variant) */
  --slate-200: 214 32% 91%;
  --slate-600: 215 19% 35%;
}
```

---

## CSS Classes

```css
/* ============================================
   DISCOUNT STATS CHART - MAIN CONTAINER
   ============================================ */

.discount-stats-card {
  background: hsl(var(--card));
  border: 1px solid hsl(var(--border));
  border-radius: 0.5rem;              /* rounded-lg = 8px */
  overflow: hidden;
}

/* Card Header */
.discount-stats-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;                        /* gap-2 */
  padding: 1.5rem 1.5rem 0.75rem;     /* CardHeader default */
  font-size: 1rem;                    /* text-base */
  font-weight: 600;                   /* font-semibold */
}

.discount-stats-header-icon {
  width: 1rem;
  height: 1rem;
  color: hsl(var(--foreground));
}

/* Legend (prawy róg headera) */
.discount-stats-legend {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 0.75rem;                       /* gap-3 */
  font-size: 0.75rem;                 /* text-xs */
  font-weight: 400;                   /* font-normal */
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 0.25rem;                       /* gap-1 */
}

.legend-dot {
  width: 0.75rem;                     /* w-3 */
  height: 0.75rem;                    /* h-3 */
  border-radius: 0.25rem;             /* rounded */
}

.legend-dot-success { background: hsl(var(--success)); }
.legend-dot-warning { background: hsl(var(--warning)); }
.legend-dot-destructive { background: hsl(var(--destructive)); }

/* Card Content */
.discount-stats-content {
  padding: 0 1.5rem 1.5rem;           /* pt-0 px-6 pb-6 */
}

/* ============================================
   ACCORDION
   ============================================ */

.discount-accordion {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;                        /* space-y-2 */
}

/* Accordion Item */
.discount-accordion-item {
  border: 1px solid hsl(var(--border));
  border-radius: 0.5rem;              /* rounded-lg */
  overflow: hidden;
}

.discount-accordion-item.has-problems {
  border-color: hsl(var(--destructive) / 0.3);
}

/* Accordion Trigger (collapsed header row) */
.discount-accordion-trigger {
  display: flex;
  align-items: center;
  width: 100%;
  padding: 0.75rem 1rem;              /* px-4 py-3 */
  background: transparent;
  border: none;
  cursor: pointer;
  text-align: left;
  transition: background 0.15s;
}

.discount-accordion-trigger:hover {
  background: hsl(var(--muted) / 0.5);
}

/* Trigger inner layout */
.discount-accordion-trigger-inner {
  display: flex;
  align-items: center;
  gap: 0.75rem;                       /* gap-3 */
  flex: 1;
  margin-right: 1rem;                 /* mr-4 */
}

/* Code name (left side) */
.discount-code-name {
  font-size: 0.875rem;                /* text-sm */
  width: 7rem;                        /* w-28 = 112px */
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace;
  text-align: left;
}

/* Values (right side) */
.discount-values {
  display: flex;
  align-items: center;
  gap: 0.5rem;                        /* gap-2 */
  width: 13rem;                       /* w-52 = 208px */
  justify-content: flex-end;
}

.discount-value-paid {
  font-size: 0.875rem;                /* text-sm */
  font-weight: 600;                   /* font-semibold */
  color: hsl(var(--success));
  font-variant-numeric: tabular-nums;
}

.discount-value-pending {
  font-size: 0.75rem;                 /* text-xs */
  font-variant-numeric: tabular-nums;
  color: hsl(var(--warning));
}

.discount-value-pending.has-overdue {
  color: hsl(var(--destructive));
}

/* ============================================
   STACKED BAR
   ============================================ */

.stacked-bar {
  flex: 1;
  height: 1.5rem;                     /* h-6 = 24px */
  background: hsl(var(--muted));
  border-radius: 0.25rem;             /* rounded */
  overflow: hidden;
  display: flex;
}

.stacked-bar-segment {
  height: 100%;
  transition: width 0.3s ease;
}

.stacked-bar-segment-paid {
  background: hsl(var(--success));
}

.stacked-bar-segment-pending {
  background: hsl(var(--warning));
}

.stacked-bar-segment-overdue {
  background: hsl(var(--destructive));
}

/* FOC Variant */
.stacked-bar-foc {
  flex: 1;
  height: 1.5rem;
  background: hsl(214 32% 91%);       /* slate-200 */
  border-radius: 0.25rem;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
}

.stacked-bar-foc-text {
  font-size: 0.75rem;                 /* text-xs */
  font-weight: 500;
  color: hsl(215 19% 35%);            /* slate-600 */
}

/* ============================================
   ACCORDION CONTENT (expanded)
   ============================================ */

.discount-accordion-content {
  padding: 0 1rem 1rem;               /* px-4 pb-4 */
}

/* Stats summary bar */
.discount-stats-summary {
  display: flex;
  align-items: center;
  gap: 1rem;                          /* gap-4 */
  margin-bottom: 0.75rem;             /* mb-3 */
  padding-bottom: 0.75rem;            /* pb-3 */
  border-bottom: 1px solid hsl(var(--border));
  font-size: 0.75rem;                 /* text-xs */
}

.discount-stats-summary-item {
  color: hsl(var(--muted-foreground));
}

.discount-stats-summary-item strong {
  color: hsl(var(--foreground));
  font-weight: 600;
}

.discount-stats-summary-item.success { color: hsl(var(--success)); }
.discount-stats-summary-item.warning { color: hsl(var(--warning)); }
.discount-stats-summary-item.destructive { color: hsl(var(--destructive)); }

.discount-stats-summary-rabat {
  margin-left: auto;
  color: hsl(var(--muted-foreground));
}

.discount-stats-summary-rabat strong {
  color: hsl(var(--destructive));
}

/* ============================================
   ORDER/PARTICIPANT ROWS
   ============================================ */

.order-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;                       /* gap-3 */
  padding: 0.5rem;                    /* p-2 */
  border-radius: 0.5rem;              /* rounded-lg */
  transition: background 0.15s;
  text-decoration: none;
  color: inherit;
}

.order-row:hover {
  background: hsl(var(--muted) / 0.5);
}

/* Left side: name + email */
.order-row-info {
  flex: 1;
  min-width: 0;
}

.order-row-name {
  font-size: 0.875rem;                /* text-sm */
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.order-row-email {
  font-size: 0.75rem;                 /* text-xs */
  color: hsl(var(--muted-foreground));
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Right side: amount + date */
.order-row-amount {
  text-align: right;
}

.order-row-amount-value {
  font-size: 0.875rem;                /* text-sm */
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.order-row-amount-date {
  font-size: 0.75rem;                 /* text-xs */
  color: hsl(var(--muted-foreground));
}

/* Chevron (appears on hover) */
.order-row-chevron {
  width: 1rem;
  height: 1rem;
  color: hsl(var(--muted-foreground));
  opacity: 0;
  transition: opacity 0.15s;
}

.order-row:hover .order-row-chevron {
  opacity: 1;
}

/* ============================================
   STATUS BADGES
   ============================================ */

.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.25rem 0.5rem;            /* px-2 py-1 */
  border-radius: 9999px;              /* rounded-full */
  font-size: 0.75rem;                 /* text-xs */
  font-weight: 500;
  border: 1px solid;
}

.status-badge-icon {
  width: 0.75rem;                     /* h-3 w-3 */
  height: 0.75rem;
}

/* Paid */
.status-badge-paid {
  background: hsl(var(--success) / 0.1);
  color: hsl(var(--success));
  border-color: hsl(var(--success) / 0.3);
}

/* Pending */
.status-badge-pending {
  background: hsl(var(--warning) / 0.1);
  color: hsl(var(--warning));
  border-color: hsl(var(--warning) / 0.3);
}

/* Overdue */
.status-badge-overdue {
  background: hsl(var(--destructive) / 0.1);
  color: hsl(var(--destructive));
  border-color: hsl(var(--destructive) / 0.3);
}

/* ============================================
   FOOTER
   ============================================ */

.discount-stats-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 1rem;                  /* pt-4 */
  margin-top: 1rem;                   /* mt-4 */
  border-top: 1px solid hsl(var(--border));
  font-size: 0.875rem;                /* text-sm */
}

.discount-stats-footer-label {
  font-weight: 500;
  color: hsl(var(--muted-foreground));
}

.discount-stats-footer-values {
  display: flex;
  align-items: center;
  gap: 0.75rem;                       /* gap-3 */
}

.discount-stats-footer-paid {
  font-weight: 700;
  color: hsl(var(--success));
}

.discount-stats-footer-pending {
  color: hsl(var(--warning));
}

.discount-stats-footer-overdue {
  color: hsl(var(--destructive));
}

/* ============================================
   FOC BADGE
   ============================================ */

.badge-foc {
  display: inline-flex;
  align-items: center;
  padding: 0.25rem 0.625rem;
  background: hsl(var(--muted));
  border-radius: 0.25rem;
  font-size: 0.75rem;
  font-weight: 500;
  color: hsl(var(--muted-foreground));
}
```

---

## HTML Template (Jinja2)

```html
<div class="discount-stats-card">
  <!-- Header -->
  <div class="discount-stats-header">
    <svg class="discount-stats-header-icon" data-lucide="trending-up"></svg>
    <span>Przychód per kod rabatowy</span>
    
    <!-- Legend -->
    <div class="discount-stats-legend">
      <div class="legend-item">
        <span class="legend-dot legend-dot-success"></span>
        <span>Opłacony</span>
      </div>
      <div class="legend-item">
        <span class="legend-dot legend-dot-warning"></span>
        <span>Oczekujący</span>
      </div>
      <div class="legend-item">
        <span class="legend-dot legend-dot-destructive"></span>
        <span>Przeterminowany</span>
      </div>
    </div>
  </div>
  
  <!-- Content -->
  <div class="discount-stats-content">
    <div class="discount-accordion">
      
      {% for code in discount_codes %}
      <div class="discount-accordion-item {% if code.orders_overdue > 0 %}has-problems{% endif %}" 
           data-state="closed" data-code="{{ code.code }}">
        
        <!-- Trigger -->
        <button class="discount-accordion-trigger" 
                onclick="toggleDiscountAccordion('{{ code.code }}')">
          <div class="discount-accordion-trigger-inner">
            
            <!-- Code name -->
            <span class="discount-code-name" title="{{ code.display_name }}">
              {{ code.display_name }}
            </span>
            
            <!-- Stacked Bar -->
            {% if code.is_foc %}
            <div class="stacked-bar-foc">
              <span class="stacked-bar-foc-text">FOC</span>
            </div>
            {% else %}
            <div class="stacked-bar">
              <div class="stacked-bar-segment stacked-bar-segment-paid" 
                   style="width: {{ (code.revenue_paid / max_revenue * 100)|round(1) }}%"></div>
              <div class="stacked-bar-segment stacked-bar-segment-pending" 
                   style="width: {{ (code.revenue_pending / max_revenue * 100)|round(1) }}%"></div>
              <div class="stacked-bar-segment stacked-bar-segment-overdue" 
                   style="width: {{ (code.revenue_overdue / max_revenue * 100)|round(1) }}%"></div>
            </div>
            {% endif %}
            
            <!-- Values -->
            <div class="discount-values">
              {% if code.is_foc %}
              <span class="badge-foc">Bezpłatne</span>
              {% else %}
              <span class="discount-value-paid">{{ code.revenue_paid|format_currency }}</span>
              {% if code.revenue_pending > 0 or code.revenue_overdue > 0 %}
              <span class="discount-value-pending {% if code.revenue_overdue > 0 %}has-overdue{% endif %}">
                +{{ (code.revenue_pending + code.revenue_overdue)|format_currency }}
              </span>
              {% endif %}
              {% endif %}
            </div>
            
          </div>
          
          <!-- Chevron -->
          <svg class="accordion-chevron" data-lucide="chevron-down"></svg>
        </button>
        
        <!-- Content (hidden by default) -->
        <div class="discount-accordion-content" style="display: none;">
          
          <!-- Stats Summary -->
          <div class="discount-stats-summary">
            <span class="discount-stats-summary-item">
              Zamówienia: <strong>{{ code.orders_count }}</strong>
            </span>
            <span class="discount-stats-summary-item success">
              Opłacone: <strong>{{ code.orders_paid }}</strong>
            </span>
            {% if code.orders_pending > 0 %}
            <span class="discount-stats-summary-item warning">
              Oczekujące: <strong>{{ code.orders_pending }}</strong>
            </span>
            {% endif %}
            {% if code.orders_overdue > 0 %}
            <span class="discount-stats-summary-item destructive">
              Przeterminowane: <strong>{{ code.orders_overdue }}</strong>
            </span>
            {% endif %}
            {% if code.discount_value > 0 %}
            <span class="discount-stats-summary-rabat">
              Rabat: <strong>-{{ code.discount_value|format_currency }}</strong>
            </span>
            {% endif %}
          </div>
          
          <!-- Orders List -->
          <div class="order-list">
            {% for order in code.orders %}
            <a href="/admin/orders/{{ order.order_id }}" class="order-row">
              <div class="order-row-info">
                <div class="order-row-name">{{ order.buyer_name }}</div>
                <div class="order-row-email">{{ order.buyer_email }}</div>
              </div>
              <div class="order-row-amount">
                <div class="order-row-amount-value">
                  {% if order.total > 0 %}{{ order.total|format_currency }}{% else %}FOC{% endif %}
                </div>
                <div class="order-row-amount-date">{{ order.created_at|format_date_pl }}</div>
              </div>
              
              <!-- Status Badge -->
              {% if order.status == 'paid' %}
              <span class="status-badge status-badge-paid">
                <svg class="status-badge-icon" data-lucide="check-circle"></svg>
                Opłacone
              </span>
              {% elif order.status == 'pending' %}
              <span class="status-badge status-badge-pending">
                <svg class="status-badge-icon" data-lucide="clock"></svg>
                Oczekujące
              </span>
              {% else %}
              <span class="status-badge status-badge-overdue">
                <svg class="status-badge-icon" data-lucide="alert-triangle"></svg>
                {{ order.days_overdue }} dni
              </span>
              {% endif %}
              
              <svg class="order-row-chevron" data-lucide="chevron-right"></svg>
            </a>
            {% endfor %}
          </div>
          
        </div>
      </div>
      {% endfor %}
      
    </div>
    
    <!-- Footer -->
    <div class="discount-stats-footer">
      <span class="discount-stats-footer-label">Suma ({{ total_orders }} zamówień)</span>
      <div class="discount-stats-footer-values">
        <span class="discount-stats-footer-paid">{{ total_paid|format_currency }}</span>
        {% if total_pending > 0 %}
        <span class="discount-stats-footer-pending">+{{ total_pending|format_currency }}</span>
        {% endif %}
        {% if total_overdue > 0 %}
        <span class="discount-stats-footer-overdue">+{{ total_overdue|format_currency }}</span>
        {% endif %}
      </div>
    </div>
    
  </div>
</div>
```

---

## JavaScript

```javascript
// Toggle accordion
function toggleDiscountAccordion(code) {
  const item = document.querySelector(`.discount-accordion-item[data-code="${code}"]`);
  const content = item.querySelector('.discount-accordion-content');
  const chevron = item.querySelector('.accordion-chevron');
  const currentState = item.dataset.state;
  
  if (currentState === 'open') {
    item.dataset.state = 'closed';
    content.style.display = 'none';
    chevron.style.transform = 'rotate(0deg)';
  } else {
    item.dataset.state = 'open';
    content.style.display = 'block';
    chevron.style.transform = 'rotate(180deg)';
  }
}

// Initialize Lucide icons
document.addEventListener('DOMContentLoaded', function() {
  if (typeof lucide !== 'undefined') {
    lucide.createIcons();
  }
});
```

---

## Wymiary i Proporcje

| Element | Wartość | Opis |
|---------|---------|------|
| Card border-radius | 8px | rounded-lg |
| Card padding | 24px | p-6 |
| Accordion gap | 8px | space-y-2 |
| Trigger padding | 12px 16px | py-3 px-4 |
| Code name width | 112px | w-28 |
| Values width | 208px | w-52 |
| Stacked bar height | 24px | h-6 |
| Order row padding | 8px | p-2 |
| Badge padding | 4px 8px | py-1 px-2 |
| Footer margin-top | 16px | mt-4 |

---

## Typografia

| Element | Font Size | Font Weight | Font Family |
|---------|-----------|-------------|-------------|
| Header title | 16px (1rem) | 600 | System |
| Legend | 12px (0.75rem) | 400 | System |
| Code name | 14px (0.875rem) | 400 | Monospace |
| Value paid | 14px (0.875rem) | 600 | System |
| Value pending | 12px (0.75rem) | 400 | System |
| Stats summary | 12px (0.75rem) | 400 | System |
| Order name | 14px (0.875rem) | 500 | System |
| Order email | 12px (0.75rem) | 400 | System |
| Status badge | 12px (0.75rem) | 500 | System |
| Footer label | 14px (0.875rem) | 500 | System |
| Footer value | 14px (0.875rem) | 700 | System |

---

## Kolory Statusów (HSL)

| Status | Main Color | Background (10%) | Border (30%) |
|--------|------------|------------------|--------------|
| Paid (Success) | `hsl(142, 76%, 36%)` | `hsl(142, 76%, 36%, 0.1)` | `hsl(142, 76%, 36%, 0.3)` |
| Pending (Warning) | `hsl(38, 92%, 50%)` | `hsl(38, 92%, 50%, 0.1)` | `hsl(38, 92%, 50%, 0.3)` |
| Overdue (Destructive) | `hsl(0, 84%, 60%)` | `hsl(0, 84%, 60%, 0.1)` | `hsl(0, 84%, 60%, 0.3)` |

---

## Data Structure (Python/Flask)

```python
# Context for template
discount_codes = [
    {
        'code': 'EARLY20',
        'display_name': 'EARLY20',
        'orders_count': 36,
        'orders_paid': 30,
        'orders_pending': 4,
        'orders_overdue': 2,
        'revenue_paid': 42000,
        'revenue_pending': 5600,
        'revenue_overdue': 2800,
        'discount_value': 12600,
        'is_foc': False,
        'orders': [
            {
                'order_id': 'ord_010',
                'buyer_name': 'Kate Brown',
                'buyer_email': 'kate@mail.com',
                'total': 1400,
                'status': 'paid',  # paid | pending | overdue
                'created_at': '2025-01-12',
                'days_overdue': None,
            },
            # ... more orders
        ],
    },
    # ... more codes
]

# Calculate max for bar scaling
max_revenue = max(
    c['revenue_paid'] + c['revenue_pending'] + c['revenue_overdue'] 
    for c in discount_codes if not c['is_foc']
)

# Totals for footer
total_orders = sum(c['orders_count'] for c in discount_codes)
total_paid = sum(c['revenue_paid'] for c in discount_codes)
total_pending = sum(c['revenue_pending'] for c in discount_codes)
total_overdue = sum(c['revenue_overdue'] for c in discount_codes)
```

---

## Accessibility

- Accordion triggers mają `role="button"` i reagują na Enter/Space
- Badge'e mają odpowiednie ikony dla wizualnego rozróżnienia statusów
- Kolory statusów spełniają wymagania WCAG AA dla kontrastu
- Stacked bar ma odpowiednią wysokość (24px) dla łatwego klikania
- Order rows są linkami z hover state dla jasnej interaktywności
