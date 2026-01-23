# Medidesk Admin Panel V2 - Eksport HTML/CSS

## Pliki szablonów

| Plik | Opis |
|------|------|
| `base.html` | Bazowy layout Jinja2 z blokami |
| `_sidebar.html` | Sidebar jako partial (include) |
| `dashboard.html` | Dashboard ze statystykami |
| `events.html` | Lista wydarzeń z kartami |
| `orders.html` | Lista zamówień z tabelą |
| `order_detail.html` | Szczegóły zamówienia z timeline |
| `users.html` | Konta i uprawnienia |
| `audit.html` | Log audytu |
| `login.html` | Strona logowania |
| `admin-styles.css` | Wszystkie style (design system) |

## Struktura folderów

```
templates/
├── admin_v2/
│   ├── base.html
│   ├── _sidebar.html
│   ├── dashboard.html
│   ├── events.html
│   ├── orders.html
│   ├── order_detail.html
│   ├── users.html
│   ├── audit.html
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
cp base.html _sidebar.html dashboard.html events.html orders.html order_detail.html users.html audit.html login.html templates/admin_v2/
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
    return render_template('admin_v2/order_detail.html', order=order)
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
