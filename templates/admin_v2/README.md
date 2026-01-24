# Medidesk Admin Panel V2 - Eksport HTML/CSS

## Pliki szablonów

### Strony główne

| Plik | Opis |
|------|------|
| `base.html` | Bazowy layout Jinja2 z blokami |
| `login.html` | Strona logowania |
| `dashboard.html` | Dashboard ze statystykami |
| `events.html` | Lista wydarzeń z kartami |
| `event_room.html` | Dashboard pojedynczego wydarzenia (tabs) |
| `orders.html` | Lista zamówień z tabelą |
| `order_detail.html` | Szczegóły zamówienia z Operational Bar |
| `participants.html` | Lista uczestników |
| `communication.html` | Historia komunikacji |
| `work_queue.html` | Kolejka zadań operacyjnych |
| `users.html` | Konta i uprawnienia |
| `audit.html` | Log audytu |
| `settings.html` | Ustawienia systemu |

### Partiale (include)

| Plik | Opis |
|------|------|
| `_sidebar.html` | Sidebar jako partial (include) |
| `_payment_buckets.html` | Buckety płatności z checkbox selection |
| `_send_message_dialog.html` | Modal wysyłania wiadomości |

### Style

| Plik | Opis |
|------|------|
| `admin-styles.css` | Wszystkie style (design system) |

### Dokumentacja specyfikacji

| Plik | Opis |
|------|------|
| `ICON-STYLES-REFERENCE.md` | Specyfikacja rozmiarów i kolorów ikon |
| `EVENT-CARD-REFERENCE.md` | Specyfikacja karty wydarzenia |
| `TASK-CARD-REFERENCE.md` | Specyfikacja karty zadania (Work Queue) |
| `OPERATIONAL-BAR-REFERENCE.md` | Specyfikacja paska operacyjnego zamówienia |
| `PAYMENT-BUCKETS-REFERENCE.md` | Specyfikacja bucketów płatności |
| `SEND-MESSAGE-DIALOG-REFERENCE.md` | Specyfikacja modala wiadomości |

## Struktura folderów

```
templates/
├── admin_v2/
│   ├── base.html
│   ├── _sidebar.html
│   ├── _payment_buckets.html
│   ├── _send_message_dialog.html
│   ├── dashboard.html
│   ├── events.html
│   ├── event_room.html
│   ├── orders.html
│   ├── order_detail.html
│   ├── participants.html
│   ├── communication.html
│   ├── work_queue.html
│   ├── users.html
│   ├── audit.html
│   ├── settings.html
│   └── login.html
│
static/
├── css/
│   └── admin-v2.css
└── images/
    ├── medidesk-logo.png
    ├── backstage-logo.jpg
    ├── empty-list.jpg
    └── empty-orders.png
```

## Integracja z Flask

### 1. Skopiuj style

```bash
cp admin-styles.css static/css/admin-v2.css
cp -r images/ static/images/
```

### 2. Skopiuj szablony

```bash
mkdir -p templates/admin_v2
cp *.html templates/admin_v2/
```

### 3. Blueprint (przykład)

```python
from flask import Blueprint, render_template

admin_v2_bp = Blueprint('admin_v2_bp', __name__, url_prefix='/admin-v2')

@admin_v2_bp.route('/')
def dashboard():
    return render_template('admin_v2/dashboard.html',
        stats={
            'total_orders': 127,
            'total_participants': 284,
            'total_revenue': 156420,
            'avg_order_value': 1232
        }
    )

@admin_v2_bp.route('/orders')
def orders():
    orders = Order.query.order_by(Order.created_at.desc()).all()
    return render_template('admin_v2/orders.html', orders=orders)

@admin_v2_bp.route('/orders/<order_id>')
def order_detail(order_id):
    order = Order.query.get_or_404(order_id)
    # Prepare operational bar data
    return render_template('admin_v2/order_detail.html', 
        order=order,
        wfirma_documents=order.documents,
        emails=order.email_logs,
        participants=order.participants,
        order_history=order.history
    )

@admin_v2_bp.route('/events/<event_id>')
def event_room(event_id):
    event = Event.query.get_or_404(event_id)
    active_tab = request.args.get('tab', 'sales')
    
    # Prepare payment buckets
    buckets = {
        'due_today': {'orders': [...], 'total': 12450},
        'overdue': {'orders': [...], 'total': 8320},
        'paid': {'orders': [...], 'total': 89200},
        'cancelled': {'orders': [...], 'total': 1500}
    }
    
    return render_template('admin_v2/event_room.html',
        event=event,
        active_tab=active_tab,
        buckets=buckets,
        stats=event.stats
    )
```

## Obrazki

| Plik | Użycie |
|------|--------|
| `medidesk-logo.png` | Logo w sidebarze |
| `backstage-logo.jpg` | Logo Backstage (jeśli potrzebne) |
| `empty-list.jpg` | Pusty stan - lista uczestników |
| `empty-orders.png` | Pusty stan - lista zamówień |

## Ikony

Używamy [Lucide Icons](https://lucide.dev/). W HTML:

```html
<i data-lucide="nazwa-ikony"></i>
```

Po załadowaniu strony wywołaj:
```javascript
lucide.createIcons();
```

## CSS Variables

Wszystkie kolory są zdefiniowane jako CSS variables w `:root`. Możesz je nadpisać:

```css
:root {
  --primary: hsl(212, 100%, 42%);  /* Zmień na swój kolor */
  --brand-teal: hsl(160, 82%, 44%);
  --brand-cyan: hsl(195, 100%, 42%);
  --brand-blue: hsl(212, 100%, 42%);
}
```

## Komponenty interaktywne

### Operational Bar (order_detail.html)

Trzkolumnowy pasek statusu z Quick Actions. Wymaga zmiennych:
- `order.status` - status zamówienia
- `wfirma_documents` - lista dokumentów
- `emails` - historia emaili

### Payment Buckets (_payment_buckets.html)

Interaktywne buckety płatności. Wymaga:
- `buckets.due_today`, `buckets.overdue`, `buckets.paid`, `buckets.cancelled`
- Każdy bucket: `{ orders: [...], total: float }`
- `stats.revenue`, `stats.pending_revenue`

### Send Message Dialog (_send_message_dialog.html)

Modal wysyłania wiadomości. Wywoływany przez JavaScript:
```javascript
openSendMessageModal(recipients, eventName);
// recipients = [{id, email, name}, ...]
```

## Uprawnienia w sidebar

Sidebar używa Jinja2 `{% if ... %}` do pokazywania/ukrywania linków w zależności od uprawnień:

```html
{% if 'view_orders' in permissions %}
  <a href="..." class="nav-item">Zamówienia</a>
{% endif %}
```

## Wykresy

Pliki HTML mają placeholdery na wykresy. Użyj:
- [Chart.js](https://www.chartjs.org/) - najprostszy
- [ApexCharts](https://apexcharts.com/) - więcej opcji

## JavaScript Dependencies

Wszystkie szablony wymagają:
1. **Lucide Icons** - do renderowania ikon
2. **DOMContentLoaded** - inicjalizacja po załadowaniu DOM

Funkcje globalne (zdefiniowane w szablonach):
- `showToast(message, type)` - powiadomienia
- `openSendMessageModal(recipients, eventName)` - modal wiadomości
- `toggleBucket(bucketId)` - expand/collapse bucket
- `bulkAction(action)` - akcje zbiorcze

## Jinja2 Filters

Szablony korzystają z custom filters:
- `|format_currency` - formatowanie kwot (np. `12 450,00 zł`)
- `|format_date_pl` - formatowanie dat (np. `12.01.2025, 14:30`)
- `|initials` - wyciąganie inicjałów z imienia i nazwiska
