# Medidesk Admin Panel - Eksport HTML/CSS

## Pliki

- `admin-styles.css` - Wszystkie style (design system, komponenty, layout)
- `admin-panel.html` - Strona zamówień (przykład z tabelą i filtrami)
- `admin-dashboard.html` - Strona dashboard (przykład ze statystykami)

## Jak użyć w Flask/Python

### 1. Skopiuj style

Umieść `admin-styles.css` w folderze `static/css/`:

```
static/
  css/
    admin-styles.css
```

### 2. Utwórz bazowy szablon

Utwórz `templates/admin/base.html`:

```html
<!DOCTYPE html>
<html lang="pl">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{% block title %}Admin{% endblock %} - Medidesk</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='css/admin-styles.css') }}">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <script src="https://unpkg.com/lucide@latest"></script>
</head>
<body>
  <div class="admin-layout">
    {% include 'admin/_sidebar.html' %}
    
    <main class="main-content">
      <div class="content-wrapper animate-fade-in">
        {% block content %}{% endblock %}
      </div>
    </main>
  </div>

  <script>
    lucide.createIcons();
    function toggleSidebar() {
      document.getElementById('sidebar').classList.toggle('collapsed');
    }
  </script>
  {% block scripts %}{% endblock %}
</body>
</html>
```

### 3. Utwórz sidebar jako partial

Utwórz `templates/admin/_sidebar.html` - skopiuj sekcję `<aside class="sidebar">...</aside>` z plików HTML.

Podmień statyczne dane na zmienne Jinja2:
- `{{ current_user.name }}` - nazwa użytkownika
- `{{ current_user.initials }}` - inicjały
- `{% if request.path == '/admin' %}active{% endif %}` - aktywna nawigacja

### 4. Utwórz stronę zamówień

`templates/admin/orders.html`:

```html
{% extends 'admin/base.html' %}

{% block title %}Zamówienia{% endblock %}

{% block content %}
<div class="page-header">
  <div>
    <h1 class="page-title">Zamówienia</h1>
    <p class="page-description">Zarządzaj zamówieniami</p>
  </div>
</div>

<!-- Filtry -->
<div class="card filters-card">
  <form class="filters-grid" method="GET">
    <div class="filter-search">
      <i data-lucide="search" class="search-icon"></i>
      <input type="text" name="q" value="{{ request.args.get('q', '') }}" 
             placeholder="Szukaj..." class="search-input">
    </div>
    <div class="filter-select">
      <select name="status">
        <option value="">Wszystkie statusy</option>
        <option value="paid" {% if request.args.get('status') == 'paid' %}selected{% endif %}>Opłacone</option>
        <option value="pending" {% if request.args.get('status') == 'pending' %}selected{% endif %}>Oczekujące</option>
      </select>
    </div>
    <button type="submit" class="btn btn-primary">Filtruj</button>
  </form>
</div>

<!-- Tabela -->
<div class="card">
  <table class="data-table">
    <thead>
      <tr>
        <th>ID</th>
        <th>Kupujący</th>
        <th>Wartość</th>
        <th>Status</th>
      </tr>
    </thead>
    <tbody>
      {% for order in orders %}
      <tr>
        <td><a href="{{ url_for('admin.order_detail', order_id=order.id) }}" class="order-link">{{ order.id }}</a></td>
        <td>{{ order.buyer_name }}</td>
        <td class="font-medium">{{ order.total|format_currency }}</td>
        <td>
          <span class="status-badge status-{{ order.status }}">
            {{ order.status_label }}
          </span>
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endblock %}
```

## Ikony

Używamy [Lucide Icons](https://lucide.dev/). W HTML:

```html
<i data-lucide="nazwa-ikony"></i>
```

Po załadowaniu strony wywołaj:
```javascript
lucide.createIcons();
```

## Kolory CSS Variables

Wszystkie kolory są zdefiniowane jako CSS variables w `:root`. Możesz je nadpisać:

```css
:root {
  --primary: hsl(212, 100%, 42%);  /* Zmień na swój kolor */
}
```

## Wykresy

Pliki HTML mają placeholdery na wykresy. Użyj:
- [Chart.js](https://www.chartjs.org/) - najprostszy
- [ApexCharts](https://apexcharts.com/) - więcej opcji
- Matplotlib/Plotly (renderuj server-side i wstaw jako SVG/img)
