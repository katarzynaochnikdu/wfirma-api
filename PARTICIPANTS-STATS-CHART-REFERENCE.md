# Participants Stats Chart - Specyfikacja Komponentu

## Przeznaczenie
Wizualizacja liczby uczestników per kod rabatowy z podziałem na status płatności (opłacony/oczekujący/przeterminowany). Każdy wiersz to accordion rozwijany ze szczegółami uczestników.

## Lokalizacja
- **React**: `src/components/admin/DiscountStatsChart.tsx` (sekcja "Uczestnicy per kod rabatowy")
- **Typy**: `src/types/discount-stats.ts` (`DiscountCodeParticipants`, `ParticipantInfo`)
- **Mock Data**: `src/lib/mock-data/discount-stats.ts` (`mockParticipantStats`)

---

## Anatomia Główna

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ CARD CONTAINER                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│ HEADER                                                                      │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ [👥] Uczestnicy per kod rabatowy        ● Opłacony ● Oczekujący ● Przet.│ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────────────────┤
│ CONTENT (Accordion)                                                         │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ ACCORDION ITEM (collapsed)                                              │ │
│ │ ┌─────────────────────────────────────────────────────────────────────┐ │ │
│ │ │ Bez rabatu   [████████████████████░░░░░░░░]       47  +8   osób   │ │ │
│ │ └─────────────────────────────────────────────────────────────────────┘ │ │
│ ├─────────────────────────────────────────────────────────────────────────┤ │
│ │ ACCORDION ITEM (expanded)                                 [border-red]  │ │
│ │ ┌─────────────────────────────────────────────────────────────────────┐ │ │
│ │ │ EARLY20      [███████████████░░░░░░░█]             36  +7   osób ▼ │ │ │
│ │ ├─────────────────────────────────────────────────────────────────────┤ │ │
│ │ │ STATS BAR                                                           │ │ │
│ │ │ Razem: 43   Opłaceni: 36   Oczekujący: 5   Przeterminowani: 2       │ │ │
│ │ ├─────────────────────────────────────────────────────────────────────┤ │ │
│ │ │ PARTICIPANT ROW                                                     │ │ │
│ │ │ ┌─────────────────────────────────────────────────────────────────┐ │ │ │
│ │ │ │ Kate Brown                    [Standard]  [✓ Opłacone]       > │ │ │ │
│ │ │ │ kate@mail.com                                                    │ │ │ │
│ │ │ └─────────────────────────────────────────────────────────────────┘ │ │ │
│ │ │ ┌─────────────────────────────────────────────────────────────────┐ │ │ │
│ │ │ │ Agnes Taylor                  [VIP]       [◷ Oczekujące]     > │ │ │ │
│ │ │ │ agnes@company.com                                                │ │ │ │
│ │ │ └─────────────────────────────────────────────────────────────────┘ │ │ │
│ │ │ ┌─────────────────────────────────────────────────────────────────┐ │ │ │
│ │ │ │ Robert Davis                  [Standard]  [⚠ Przeterminowane]> │ │ │ │
│ │ │ │ robert@biz.co                                                    │ │ │ │
│ │ │ └─────────────────────────────────────────────────────────────────┘ │ │ │
│ │ └─────────────────────────────────────────────────────────────────────┘ │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────────────────┤
│ FOOTER                                                                      │
│ Suma (185 uczestników)                                 150  +25  +10  osób  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Różnice względem wykresu Przychodu

| Aspekt | Przychód | Uczestnicy |
|--------|----------|------------|
| Ikona header | `trending-up` | `users` |
| Wartości | Kwoty (zł) | Liczby osób |
| Suffix | brak | "osób" |
| Row content | Kwota + data | Typ biletu (badge) |
| Stats summary | Zamówienia/Rabat | Razem (bez rabatu) |
| Link | `/admin/orders/` | `/admin/participants/` |

---

## Anatomia Szczegółowa: Stacked Bar (identyczna)

```
STACKED BAR (3 segmenty) - osoby zamiast kwot
┌────────────────────────────────────────────────────────────────┐
│                                                                │
│ ┌──────────────────────────┬─────────────┬────────┐            │
│ │ ██████████████████████████│█████████████│████████│            │
│ │   PAID (participantsPaid) │   PENDING   │OVERDUE │            │
│ │        bg-success         │ bg-warning  │bg-destr│            │
│ └──────────────────────────┴─────────────┴────────┘            │
│                                                                │
│ Height: 24px (h-6)                                             │
│ Border-radius: 4px (rounded)                                   │
│ Background (empty): bg-muted                                   │
│                                                                │
│ Szerokość = (wartość / maxParticipants) * 100%                 │
│ gdzie maxParticipants = max(participantsTotal) dla wszystkich  │
└────────────────────────────────────────────────────────────────┘
```

---

## CSS Variables (identyczne jak Revenue)

```css
:root {
  /* Status Colors - HSL format */
  --success: 142 76% 36%;           /* Green - Opłacony */
  --warning: 38 92% 50%;            /* Amber - Oczekujący */
  --destructive: 0 84% 60%;         /* Red - Przeterminowany */
  
  /* Neutral */
  --muted: 210 40% 96%;
  --muted-foreground: 215 16% 47%;
  --border: 214 32% 91%;
  --foreground: 222 47% 11%;
}
```

---

## CSS Classes (rozszerzenie)

```css
/* ============================================
   PARTICIPANTS STATS CHART
   Używa tych samych klas co Revenue Chart
   + dodatkowe klasy specyficzne
   ============================================ */

/* Values section - wersja dla osób */
.participant-values {
  display: flex;
  align-items: center;
  gap: 0.5rem;                        /* gap-2 */
  width: 10rem;                       /* w-40 = 160px (mniej niż revenue) */
  justify-content: flex-end;
}

.participant-value-paid {
  font-size: 0.875rem;                /* text-sm */
  font-weight: 600;                   /* font-semibold */
  color: hsl(var(--success));
  font-variant-numeric: tabular-nums;
}

.participant-value-pending {
  font-size: 0.75rem;                 /* text-xs */
  font-variant-numeric: tabular-nums;
  color: hsl(var(--warning));
}

.participant-value-pending.has-overdue {
  color: hsl(var(--destructive));
}

.participant-value-suffix {
  font-size: 0.75rem;                 /* text-xs */
  color: hsl(var(--muted-foreground));
}

/* ============================================
   PARTICIPANT ROW (różni się od Order Row)
   ============================================ */

.participant-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;                       /* gap-3 */
  padding: 0.5rem;                    /* p-2 */
  border-radius: 0.5rem;              /* rounded-lg */
  transition: background 0.15s;
  text-decoration: none;
  color: inherit;
}

.participant-row:hover {
  background: hsl(var(--muted) / 0.5);
}

/* Left side: name + email */
.participant-row-info {
  flex: 1;
  min-width: 0;
}

.participant-row-name {
  font-size: 0.875rem;                /* text-sm */
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.participant-row-email {
  font-size: 0.75rem;                 /* text-xs */
  color: hsl(var(--muted-foreground));
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Ticket Type Badge */
.ticket-type-badge {
  display: inline-flex;
  align-items: center;
  padding: 0.25rem 0.5rem;            /* py-1 px-2 */
  border: 1px solid hsl(var(--border));
  border-radius: 0.25rem;             /* rounded */
  font-size: 0.75rem;                 /* text-xs */
  font-weight: 400;
  color: hsl(var(--foreground));
  background: transparent;
}

/* Chevron (appears on hover) */
.participant-row-chevron {
  width: 1rem;
  height: 1rem;
  color: hsl(var(--muted-foreground));
  opacity: 0;
  transition: opacity 0.15s;
}

.participant-row:hover .participant-row-chevron {
  opacity: 1;
}

/* ============================================
   STATS SUMMARY (wersja dla uczestników)
   ============================================ */

.participant-stats-summary {
  display: flex;
  align-items: center;
  gap: 1rem;                          /* gap-4 */
  margin-bottom: 0.75rem;             /* mb-3 */
  padding-bottom: 0.75rem;            /* pb-3 */
  border-bottom: 1px solid hsl(var(--border));
  font-size: 0.75rem;                 /* text-xs */
}

/* Brak sekcji "Rabat" - tylko liczby osób */

/* ============================================
   FOOTER (wersja dla uczestników)
   ============================================ */

.participant-stats-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 1rem;                  /* pt-4 */
  margin-top: 1rem;                   /* mt-4 */
  border-top: 1px solid hsl(var(--border));
  font-size: 0.875rem;                /* text-sm */
}

.participant-stats-footer-values {
  display: flex;
  align-items: center;
  gap: 0.75rem;                       /* gap-3 */
}

.participant-stats-footer-suffix {
  font-size: 0.75rem;
  color: hsl(var(--muted-foreground));
}
```

---

## HTML Template (Jinja2)

```html
<div class="discount-stats-card">
  <!-- Header -->
  <div class="discount-stats-header">
    <svg class="discount-stats-header-icon" data-lucide="users"></svg>
    <span>Uczestnicy per kod rabatowy</span>
    
    <!-- Legend (identyczna) -->
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
      
      {% for code in participant_stats %}
      <div class="discount-accordion-item {% if code.participants_overdue > 0 %}has-problems{% endif %}" 
           data-state="closed" data-code="{{ code.code }}-participants">
        
        <!-- Trigger -->
        <button class="discount-accordion-trigger" 
                onclick="toggleDiscountAccordion('{{ code.code }}-participants')">
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
                   style="width: {{ (code.participants_paid / max_participants * 100)|round(1) }}%"></div>
              <div class="stacked-bar-segment stacked-bar-segment-pending" 
                   style="width: {{ (code.participants_pending / max_participants * 100)|round(1) }}%"></div>
              <div class="stacked-bar-segment stacked-bar-segment-overdue" 
                   style="width: {{ (code.participants_overdue / max_participants * 100)|round(1) }}%"></div>
            </div>
            {% endif %}
            
            <!-- Values (osoby) -->
            <div class="participant-values">
              {% if code.is_foc %}
              <span class="badge-foc">Bezpłatne</span>
              {% else %}
              <span class="participant-value-paid">{{ code.participants_paid }}</span>
              {% if code.participants_pending > 0 or code.participants_overdue > 0 %}
              <span class="participant-value-pending {% if code.participants_overdue > 0 %}has-overdue{% endif %}">
                +{{ code.participants_pending + code.participants_overdue }}
              </span>
              {% endif %}
              {% endif %}
              <span class="participant-value-suffix">osób</span>
            </div>
            
          </div>
          
          <!-- Chevron -->
          <svg class="accordion-chevron" data-lucide="chevron-down"></svg>
        </button>
        
        <!-- Content (hidden by default) -->
        <div class="discount-accordion-content" style="display: none;">
          
          <!-- Stats Summary -->
          <div class="participant-stats-summary">
            <span class="discount-stats-summary-item">
              Razem: <strong>{{ code.participants_total }}</strong>
            </span>
            <span class="discount-stats-summary-item success">
              Opłaceni: <strong>{{ code.participants_paid }}</strong>
            </span>
            {% if code.participants_pending > 0 %}
            <span class="discount-stats-summary-item warning">
              Oczekujący: <strong>{{ code.participants_pending }}</strong>
            </span>
            {% endif %}
            {% if code.participants_overdue > 0 %}
            <span class="discount-stats-summary-item destructive">
              Przeterminowani: <strong>{{ code.participants_overdue }}</strong>
            </span>
            {% endif %}
          </div>
          
          <!-- Participants List -->
          <div class="participant-list">
            {% for participant in code.participants %}
            <a href="/admin/participants/{{ participant.participant_id }}" class="participant-row">
              <div class="participant-row-info">
                <div class="participant-row-name">{{ participant.name }}</div>
                <div class="participant-row-email">{{ participant.email }}</div>
              </div>
              
              <!-- Ticket Type Badge -->
              <span class="ticket-type-badge">{{ participant.ticket_type }}</span>
              
              <!-- Status Badge -->
              {% if participant.status == 'paid' %}
              <span class="status-badge status-badge-paid">
                <svg class="status-badge-icon" data-lucide="check-circle"></svg>
                Opłacone
              </span>
              {% elif participant.status == 'pending' %}
              <span class="status-badge status-badge-pending">
                <svg class="status-badge-icon" data-lucide="clock"></svg>
                Oczekujące
              </span>
              {% else %}
              <span class="status-badge status-badge-overdue">
                <svg class="status-badge-icon" data-lucide="alert-triangle"></svg>
                Przeterminowane
              </span>
              {% endif %}
              
              <svg class="participant-row-chevron" data-lucide="chevron-right"></svg>
            </a>
            {% endfor %}
          </div>
          
          {% if code.participants|length > 5 %}
          <div class="accordion-view-all">
            <a href="/admin/participants?discount={{ code.code }}" class="view-all-link">
              Zobacz wszystkich uczestników
              <svg class="view-all-icon" data-lucide="external-link"></svg>
            </a>
          </div>
          {% endif %}
          
        </div>
      </div>
      {% endfor %}
      
    </div>
    
    <!-- Footer -->
    <div class="participant-stats-footer">
      <span class="discount-stats-footer-label">Suma ({{ total_participants }} uczestników)</span>
      <div class="participant-stats-footer-values">
        <span class="discount-stats-footer-paid">{{ total_participants_paid }}</span>
        {% if total_participants_pending > 0 %}
        <span class="discount-stats-footer-pending">+{{ total_participants_pending }}</span>
        {% endif %}
        {% if total_participants_overdue > 0 %}
        <span class="discount-stats-footer-overdue">+{{ total_participants_overdue }}</span>
        {% endif %}
        <span class="participant-stats-footer-suffix">osób</span>
      </div>
    </div>
    
  </div>
</div>
```

---

## Wymiary i Proporcje

| Element | Wartość | Opis |
|---------|---------|------|
| Card border-radius | 8px | rounded-lg |
| Values width | **160px** | w-40 (mniej niż 208px dla revenue) |
| Ticket badge padding | 4px 8px | py-1 px-2 |
| Pozostałe | Identyczne jak Revenue Chart | |

---

## Typografia

| Element | Font Size | Font Weight |
|---------|-----------|-------------|
| Header title | 16px | 600 |
| Value paid (liczba) | 14px | 600 |
| Value pending | 12px | 400 |
| Suffix "osób" | 12px | 400 |
| Participant name | 14px | 500 |
| Ticket type badge | 12px | 400 |
| Stats summary | 12px | 400 |

---

## Data Structure (Python/Flask)

```python
# Context for template
participant_stats = [
    {
        'code': 'EARLY20',
        'display_name': 'EARLY20',
        'participants_total': 43,
        'participants_paid': 36,
        'participants_pending': 5,
        'participants_overdue': 2,
        'is_foc': False,
        'ticket_breakdown': [
            {'ticket_type_id': 'standard', 'ticket_type_name': 'Standard', 
             'count_total': 22, 'count_paid': 18, 'count_pending': 3, 'count_overdue': 1},
            {'ticket_type_id': 'vip', 'ticket_type_name': 'VIP', 
             'count_total': 10, 'count_paid': 9, 'count_pending': 0, 'count_overdue': 1},
            # ...
        ],
        'participants': [
            {
                'participant_id': 'prt_010',
                'name': 'Kate Brown',
                'email': 'kate@mail.com',
                'ticket_type': 'Standard',
                'status': 'paid',  # paid | pending | overdue
                'order_id': 'ord_010',
            },
            # ... more participants
        ],
    },
    # ... more codes
]

# Calculate max for bar scaling
max_participants = max(c['participants_total'] for c in participant_stats)

# Totals for footer
total_participants = sum(c['participants_total'] for c in participant_stats)
total_participants_paid = sum(c['participants_paid'] for c in participant_stats)
total_participants_pending = sum(c['participants_pending'] for c in participant_stats)
total_participants_overdue = sum(c['participants_overdue'] for c in participant_stats)
```

---

## Porównanie Layout: Revenue vs Participants

```
REVENUE ROW:
┌────────────┬──────────────────────────────────┬─────────────────────────────┐
│ EARLY20    │ [███████████████░░░░░░░█]        │ 42 000 zł  +8 400 zł      ▼ │
│            │                                  │   w-52 (208px)               │
└────────────┴──────────────────────────────────┴─────────────────────────────┘

PARTICIPANTS ROW:
┌────────────┬──────────────────────────────────┬─────────────────────────────┐
│ EARLY20    │ [███████████████░░░░░░░█]        │    36  +7   osób          ▼ │
│            │                                  │   w-40 (160px)               │
└────────────┴──────────────────────────────────┴─────────────────────────────┘

REVENUE ORDER ROW:
┌─────────────────────────┬────────────────┬──────────────────┬───┐
│ Kate Brown              │   1 400 zł     │ [✓ Opłacone]     │ > │
│ kate@mail.com           │   2025-01-12   │                  │   │
└─────────────────────────┴────────────────┴──────────────────┴───┘
                               ↑ Kwota + Data

PARTICIPANT ROW:
┌─────────────────────────┬────────────┬──────────────────┬───┐
│ Kate Brown              │ [Standard] │ [✓ Opłacone]     │ > │
│ kate@mail.com           │            │                  │   │
└─────────────────────────┴────────────┴──────────────────┴───┘
                               ↑ Ticket Type Badge (bez daty/kwoty)
```

---

## Accessibility

- Identyczne wymagania jak Revenue Chart
- Ticket type badge ma czytelny tekst z odpowiednim kontrastem
- Linki do uczestników są w pełni klawiszowo nawigowalne
