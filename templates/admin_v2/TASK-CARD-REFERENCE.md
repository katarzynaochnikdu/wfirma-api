# Task Card - Wzorcowa Dokumentacja CSS/HTML

**Źródło prawdy:** `src/components/admin/TaskCard.tsx`

---

## 📐 Anatomia TaskCard (Pełna struktura)

```
┌─────────────────────────────────────────────────────────────────────────┐
│▌                                                                        │
│▌  ┌──────┐                                                              │
│▌  │ ICON │  Tytuł zadania   [Ostrzeżenie]  [⚠ Przeterminowane]         │
│▌  │      │                                                              │
│▌  └──────┘  Opis zadania - co poszło nie tak i wymaga interwencji...   │
│▌                                                                        │
│▌            [ERR_CODE]  [PROFORMA]  ⏱ 2h temu  🔄 1/3                   │
│▌                                                                        │
│▌            Medidesk Conference 2025 - Warszawa   #ORD/2025/01/015      │
│▌                                                                        │
├─────────────────────────────────────────────────────────────────────────┤
│  ACTION BAR                                                             │
│  [🔔 Wyślij przypomnienie]   [✓ Oznacz opłacone]                       │
└─────────────────────────────────────────────────────────────────────────┘

▌ = border-left (4px, kolor zależny od severity)
```

---

## 🎨 Główny Kontener

### React:
```tsx
<div className={cn(
  "group relative rounded-xl border border-l-4 border-l-muted bg-card transition-all hover:shadow-sm overflow-hidden flex flex-col",
  (task.alert_level === 'critical' || task.alert_level === 'security') && "border-l-destructive",
  task.alert_level === 'error' && "border-l-destructive/70",
  task.alert_level === 'warning' && "border-l-primary/60",
  task.alert_level === 'info' && "border-l-muted-foreground/40"
)}>
```

### CSS:
```css
.task-card {
  position: relative;
  border-radius: 0.75rem;                    /* rounded-xl */
  border: 1px solid var(--border);
  border-left-width: 4px;                    /* border-l-4 */
  border-left-color: var(--muted);           /* default */
  background-color: var(--card);
  transition: all 0.2s ease;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.task-card:hover {
  box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.1); /* hover:shadow-sm */
}

/* Severity borders */
.task-card-critical { border-left-color: hsl(var(--destructive)); }
.task-card-error    { border-left-color: hsl(var(--destructive) / 0.7); }
.task-card-warning  { border-left-color: hsl(var(--primary) / 0.6); }
.task-card-info     { border-left-color: hsl(var(--muted-foreground) / 0.4); }
```

---

## 📏 Wymiary - Tailwind → CSS (Master Table)

| Element | Tailwind | CSS |
|---------|----------|-----|
| **Card border-radius** | `rounded-xl` | `border-radius: 0.75rem;` |
| **Left border** | `border-l-4` | `border-left-width: 4px;` |
| **Content padding** | `p-5` | `padding: 1.25rem;` |
| **Icon-content gap** | `gap-4` | `gap: 1rem;` |
| **Icon container padding** | `p-2.5` | `padding: 0.625rem;` |
| **Icon size** | `h-4 w-4` | `16px` |
| **Title font** | `text-sm font-semibold` | `font-size: 0.875rem; font-weight: 600;` |
| **Badge padding** | `px-2 py-0.5` | `padding: 0.125rem 0.5rem;` |
| **Badge font** | `text-[11px]` | `font-size: 11px;` |
| **Metadata icon** | `h-3.5 w-3.5` | `14px` |
| **Action bar padding** | `px-5 py-3` | `padding: 0.75rem 1.25rem;` |
| **Action button height** | `h-9` | `height: 2.25rem;` (36px) |
| **Action icon** | `h-3.5 w-3.5` | `14px` |

---

## 📦 Content Section

### React:
```tsx
<div className="flex-1 p-5">
  <div className="flex items-start gap-4">
    {/* Icon + Content */}
  </div>
</div>
```

### CSS:
```css
.task-card-content {
  flex: 1;
  padding: 1.25rem;                          /* p-5 */
}

.task-card-content-inner {
  display: flex;
  align-items: flex-start;                   /* items-start */
  gap: 1rem;                                 /* gap-4 */
}
```

---

## 🔲 Category Icon Container

### React:
```tsx
<div className="shrink-0 p-2.5 rounded-lg bg-muted/60">
  <CategoryIcon className={cn("h-4 w-4", catConfig.color)} />
</div>
```

### CSS:
```css
.task-icon-container {
  flex-shrink: 0;
  padding: 0.625rem;                         /* p-2.5 */
  border-radius: 0.5rem;                     /* rounded-lg */
  background-color: hsl(var(--muted) / 0.6); /* bg-muted/60 */
}

.task-icon-container i {
  width: 16px;                               /* h-4 w-4 */
  height: 16px;
  color: var(--muted-foreground);            /* text-slate-500 */
}
```

### Mapowanie kategorii → ikona:

| Kategoria | Ikona | Lucide Name |
|-----------|-------|-------------|
| wFirma | `<FileText />` | `file-text` |
| Make.com | `<Zap />` | `zap` |
| Stripe | `<CreditCard />` | `credit-card` |
| Database | `<Database />` | `database` |
| Attendee | `<Users />` | `users` |
| Config | `<Settings />` | `settings` |

---

## 📝 Title Row (z badges)

### React:
```tsx
<div className="flex items-center gap-2 flex-wrap">
  <h4 className="font-semibold text-sm text-foreground">{task.title}</h4>
  
  {/* Alert level badge */}
  <span className={cn(
    "text-[11px] font-medium px-2 py-0.5 rounded-full",
    alertConfig.className
  )}>
    {alertConfig.label}
  </span>
  
  {/* Overdue badge */}
  {task.is_overdue && (
    <span className="text-[11px] font-medium px-2 py-0.5 rounded-full text-red-600 bg-red-50 flex items-center gap-1">
      <AlertTriangle className="h-3 w-3" />
      Przeterminowane
    </span>
  )}
</div>
```

### CSS:
```css
.task-title-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;                               /* gap-2 */
  flex-wrap: wrap;
}

.task-title {
  font-weight: 600;                          /* font-semibold */
  font-size: 0.875rem;                       /* text-sm */
  color: var(--foreground);
  margin: 0;
}

/* Alert level badges */
.task-badge {
  font-size: 11px;                           /* text-[11px] */
  font-weight: 500;                          /* font-medium */
  padding: 0.125rem 0.5rem;                  /* py-0.5 px-2 */
  border-radius: 9999px;                     /* rounded-full */
  white-space: nowrap;
}

.task-badge-info     { color: hsl(215, 16%, 37%); background: hsl(215, 16%, 93%); }
.task-badge-warning  { color: hsl(45, 100%, 31%); background: hsl(45, 100%, 96%); }
.task-badge-error    { color: hsl(24, 100%, 37%); background: hsl(24, 100%, 96%); }
.task-badge-critical { color: hsl(0, 72%, 45%); background: hsl(0, 72%, 96%); }

/* Overdue badge */
.task-badge-overdue {
  font-size: 11px;
  font-weight: 500;
  padding: 0.125rem 0.5rem;
  border-radius: 9999px;
  color: hsl(0, 72%, 45%);                   /* text-red-600 */
  background: hsl(0, 86%, 97%);              /* bg-red-50 */
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;                              /* gap-1 */
}

.task-badge-overdue i {
  width: 12px;                               /* h-3 w-3 */
  height: 12px;
}
```

### HTML:
```html
<div class="task-title-row">
  <h4 class="task-title">Błąd tworzenia sesji Stripe</h4>
  <span class="task-badge task-badge-error">Błąd</span>
  {% if task.is_overdue %}
  <span class="task-badge-overdue">
    <i data-lucide="alert-triangle"></i>
    Przeterminowane
  </span>
  {% endif %}
</div>
```

---

## 📄 Description

### React:
```tsx
{task.description && (
  <p className="text-sm text-muted-foreground leading-relaxed">{task.description}</p>
)}
```

### CSS:
```css
.task-description {
  font-size: 0.875rem;                       /* text-sm */
  color: var(--muted-foreground);
  line-height: 1.625;                        /* leading-relaxed */
  margin: 0;
}
```

---

## 🏷️ Metadata Row

### React:
```tsx
<div className="flex items-center gap-3 text-xs flex-wrap pt-1">
  {/* Error code */}
  {task.error_code && (
    <code className="font-mono text-[11px] text-muted-foreground bg-muted px-2 py-1 rounded-md">
      {task.error_code}
    </code>
  )}
  
  {/* Flow type badge */}
  {task.flow_type && (
    <span className={cn(
      "font-mono text-[11px] font-semibold px-2 py-1 rounded-md",
      task.flow_type === 'foc' && "bg-emerald-50 text-emerald-600",
      task.flow_type === 'proforma' && "bg-blue-50 text-blue-600",
      task.flow_type === 'stripe' && "bg-purple-50 text-purple-600"
    )}>
      {flowConfig[task.flow_type].label}
    </span>
  )}
  
  {/* Timestamp */}
  <span className="text-muted-foreground flex items-center gap-1">
    <Clock className="h-3.5 w-3.5" />
    {formatTimeAgo(task.created_at)}
  </span>
  
  {/* Retry counter */}
  {task.can_retry && task.max_retries > 0 && (
    <span className={cn(
      "flex items-center gap-1",
      task.retry_count >= task.max_retries ? "text-red-500" : "text-muted-foreground"
    )}>
      <RefreshCw className="h-3.5 w-3.5" />
      {task.retry_count}/{task.max_retries}
    </span>
  )}
</div>
```

### CSS:
```css
.task-metadata {
  display: flex;
  align-items: center;
  gap: 0.75rem;                              /* gap-3 */
  flex-wrap: wrap;
  padding-top: 0.25rem;                      /* pt-1 */
  font-size: 0.75rem;                        /* text-xs */
}

/* Error code */
.task-error-code {
  font-family: ui-monospace, monospace;      /* font-mono */
  font-size: 11px;                           /* text-[11px] */
  color: var(--muted-foreground);
  background-color: var(--muted);
  padding: 0.25rem 0.5rem;                   /* py-1 px-2 */
  border-radius: 0.375rem;                   /* rounded-md */
}

/* Flow type badges */
.task-flow-badge {
  font-family: ui-monospace, monospace;
  font-size: 11px;
  font-weight: 600;                          /* font-semibold */
  padding: 0.25rem 0.5rem;
  border-radius: 0.375rem;
}

.task-flow-foc      { background: hsl(152, 69%, 96%); color: hsl(152, 69%, 31%); }
.task-flow-proforma { background: hsl(214, 95%, 96%); color: hsl(214, 95%, 45%); }
.task-flow-stripe   { background: hsl(270, 67%, 96%); color: hsl(270, 67%, 47%); }

/* Timestamp */
.task-timestamp {
  color: var(--muted-foreground);
  display: flex;
  align-items: center;
  gap: 0.25rem;                              /* gap-1 */
}

.task-timestamp i {
  width: 14px;                               /* h-3.5 w-3.5 */
  height: 14px;
}

/* Retry counter */
.task-retry {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  color: var(--muted-foreground);
}

.task-retry.exhausted {
  color: hsl(0, 84%, 60%);                   /* text-red-500 */
}

.task-retry i {
  width: 14px;
  height: 14px;
}
```

### HTML:
```html
<div class="task-metadata">
  {% if task.error_code %}
  <code class="task-error-code">{{ task.error_code }}</code>
  {% endif %}
  
  {% if task.flow_type %}
  <span class="task-flow-badge task-flow-{{ task.flow_type }}">{{ task.flow_type|upper }}</span>
  {% endif %}
  
  <span class="task-timestamp">
    <i data-lucide="clock"></i>
    {{ task.created_at|timeago }}
  </span>
  
  {% if task.can_retry and task.max_retries > 0 %}
  <span class="task-retry {% if task.retry_count >= task.max_retries %}exhausted{% endif %}">
    <i data-lucide="refresh-cw"></i>
    {{ task.retry_count }}/{{ task.max_retries }}
  </span>
  {% endif %}
</div>
```

---

## 🔗 Event/Order Links

### React:
```tsx
{(task.event_name || task.order_number) && (
  <div className="flex items-center gap-3 pt-1 text-sm">
    {task.event_name && (
      <Link 
        to={`/admin/events/${task.event_id}`}
        className="text-muted-foreground hover:text-primary hover:underline truncate"
      >
        {task.event_name}
      </Link>
    )}
    {task.order_number && (
      <Link 
        to={`/admin/orders/${task.order_id}`}
        className="font-mono text-xs text-muted-foreground hover:text-primary bg-muted px-2 py-0.5 rounded"
      >
        #{task.order_number}
      </Link>
    )}
  </div>
)}
```

### CSS:
```css
.task-links {
  display: flex;
  align-items: center;
  gap: 0.75rem;                              /* gap-3 */
  padding-top: 0.25rem;                      /* pt-1 */
  font-size: 0.875rem;                       /* text-sm */
}

.task-event-link {
  color: var(--muted-foreground);
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: color 0.2s ease;
}

.task-event-link:hover {
  color: hsl(var(--primary));
  text-decoration: underline;
}

.task-order-link {
  font-family: ui-monospace, monospace;      /* font-mono */
  font-size: 0.75rem;                        /* text-xs */
  color: var(--muted-foreground);
  background-color: var(--muted);
  padding: 0.125rem 0.5rem;                  /* py-0.5 px-2 */
  border-radius: 0.25rem;                    /* rounded */
  text-decoration: none;
  transition: color 0.2s ease;
}

.task-order-link:hover {
  color: hsl(var(--primary));
}
```

### HTML:
```html
<div class="task-links">
  {% if task.event_name %}
  <a href="{{ url_for('admin_v2_bp.event_room', event_id=task.event_id) }}" class="task-event-link">
    {{ task.event_name }}
  </a>
  {% endif %}
  {% if task.order_number %}
  <a href="{{ url_for('admin_v2_bp.order_detail', order_id=task.order_id) }}" class="task-order-link">
    #{{ task.order_number }}
  </a>
  {% endif %}
</div>
```

---

## 🔲 Action Bar

### React:
```tsx
{task.quick_actions.length > 0 && (
  <div className="flex items-center gap-2 px-5 py-3 border-t bg-muted/30 flex-wrap">
    {task.quick_actions.map((action, index) => {
      const isPrimary = action.variant === 'primary' || index === 0;
      // ... button rendering
    })}
  </div>
)}
```

### CSS:
```css
.task-action-bar {
  display: flex;
  align-items: center;
  gap: 0.5rem;                               /* gap-2 */
  flex-wrap: wrap;
  padding: 0.75rem 1.25rem;                  /* py-3 px-5 */
  border-top: 1px solid var(--border);       /* border-t */
  background-color: hsl(var(--muted) / 0.3); /* bg-muted/30 */
}
```

*(Szczegóły przycisków → patrz ACTION-BUTTONS-REFERENCE.md)*

---

## 📋 Kompletny HTML Template

```html
<div class="task-card task-card-{{ task.alert_level }}">
  <!-- Content Section -->
  <div class="task-card-content">
    <div class="task-card-content-inner">
      <!-- Category Icon -->
      <div class="task-icon-container">
        <i data-lucide="{{ task.category_icon }}"></i>
      </div>

      <!-- Content -->
      <div class="task-content-body">
        <!-- Title row with badges -->
        <div class="task-title-row">
          <h4 class="task-title">{{ task.title }}</h4>
          <span class="task-badge task-badge-{{ task.alert_level }}">{{ task.alert_label }}</span>
          {% if task.is_overdue %}
          <span class="task-badge-overdue">
            <i data-lucide="alert-triangle"></i>
            Przeterminowane
          </span>
          {% endif %}
        </div>

        <!-- Description -->
        {% if task.description %}
        <p class="task-description">{{ task.description }}</p>
        {% endif %}

        <!-- Metadata row -->
        <div class="task-metadata">
          {% if task.error_code %}
          <code class="task-error-code">{{ task.error_code }}</code>
          {% endif %}
          
          {% if task.flow_type %}
          <span class="task-flow-badge task-flow-{{ task.flow_type }}">{{ task.flow_type|upper }}</span>
          {% endif %}
          
          <span class="task-timestamp">
            <i data-lucide="clock"></i>
            {{ task.created_at|timeago }}
          </span>
          
          {% if task.can_retry and task.max_retries > 0 %}
          <span class="task-retry {% if task.retry_count >= task.max_retries %}exhausted{% endif %}">
            <i data-lucide="refresh-cw"></i>
            {{ task.retry_count }}/{{ task.max_retries }}
          </span>
          {% endif %}
        </div>

        <!-- Event/Order links -->
        {% if task.event_name or task.order_number %}
        <div class="task-links">
          {% if task.event_name %}
          <a href="{{ url_for('admin_v2_bp.event_room', event_id=task.event_id) }}" class="task-event-link">
            {{ task.event_name }}
          </a>
          {% endif %}
          {% if task.order_number %}
          <a href="{{ url_for('admin_v2_bp.order_detail', order_id=task.order_id) }}" class="task-order-link">
            #{{ task.order_number }}
          </a>
          {% endif %}
        </div>
        {% endif %}
      </div>
    </div>
  </div>

  <!-- Action Bar -->
  {% if task.quick_actions %}
  <div class="task-action-bar">
    {% for action in task.quick_actions %}
    {% if action.action_type == 'retry' %}
    <form method="POST" action="{{ url_for('admin_v2_bp.work_queue_retry', task_id=task.id) }}" style="display: inline;">
      <button type="submit" class="btn-action-{% if loop.first %}primary{% else %}outline{% endif %}">
        <i data-lucide="{{ action.icon }}"></i>
        <span>{{ action.label }}</span>
      </button>
    </form>
    {% elif action.action_type == 'navigate' %}
    <a href="{{ action.url }}" class="btn-action-{% if loop.first %}primary{% else %}outline{% endif %}">
      <i data-lucide="{{ action.icon }}"></i>
      <span>{{ action.label }}</span>
    </a>
    {% else %}
    <button type="button" class="btn-action-{% if loop.first %}primary{% else %}outline{% endif %}" onclick="{{ action.onclick }}">
      <i data-lucide="{{ action.icon }}"></i>
      <span>{{ action.label }}</span>
    </button>
    {% endif %}
    {% endfor %}
  </div>
  {% endif %}
</div>
```

---

## 📋 Kompletny CSS

```css
/* ============================================
   TASK CARD - Complete Styles
   ============================================ */

/* === MAIN CONTAINER === */
.task-card {
  position: relative;
  border-radius: 0.75rem;
  border: 1px solid var(--border);
  border-left-width: 4px;
  border-left-color: var(--muted);
  background-color: var(--card);
  transition: all 0.2s ease;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.task-card:hover {
  box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.1);
}

/* Severity left borders */
.task-card-critical,
.task-card-security { border-left-color: hsl(var(--destructive)); }
.task-card-error    { border-left-color: hsl(var(--destructive) / 0.7); }
.task-card-warning  { border-left-color: hsl(var(--primary) / 0.6); }
.task-card-info     { border-left-color: hsl(var(--muted-foreground) / 0.4); }

/* === CONTENT SECTION === */
.task-card-content {
  flex: 1;
  padding: 1.25rem;
}

.task-card-content-inner {
  display: flex;
  align-items: flex-start;
  gap: 1rem;
}

.task-content-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

/* === ICON CONTAINER === */
.task-icon-container {
  flex-shrink: 0;
  padding: 0.625rem;
  border-radius: 0.5rem;
  background-color: hsl(var(--muted) / 0.6);
}

.task-icon-container i {
  width: 16px;
  height: 16px;
  color: hsl(215, 16%, 47%);
}

/* === TITLE ROW === */
.task-title-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.task-title {
  font-weight: 600;
  font-size: 0.875rem;
  color: var(--foreground);
  margin: 0;
}

/* === BADGES === */
.task-badge {
  font-size: 11px;
  font-weight: 500;
  padding: 0.125rem 0.5rem;
  border-radius: 9999px;
  white-space: nowrap;
}

.task-badge-info     { color: hsl(215, 16%, 37%); background: hsl(215, 16%, 93%); }
.task-badge-warning  { color: hsl(45, 100%, 31%); background: hsl(45, 100%, 96%); }
.task-badge-error    { color: hsl(24, 100%, 37%); background: hsl(24, 100%, 96%); }
.task-badge-critical { color: hsl(0, 72%, 45%); background: hsl(0, 72%, 96%); }
.task-badge-security { color: hsl(0, 72%, 45%); background: hsl(0, 72%, 96%); }

.task-badge-overdue {
  font-size: 11px;
  font-weight: 500;
  padding: 0.125rem 0.5rem;
  border-radius: 9999px;
  color: hsl(0, 72%, 45%);
  background: hsl(0, 86%, 97%);
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
}

.task-badge-overdue i {
  width: 12px;
  height: 12px;
}

/* === DESCRIPTION === */
.task-description {
  font-size: 0.875rem;
  color: var(--muted-foreground);
  line-height: 1.625;
  margin: 0;
}

/* === METADATA ROW === */
.task-metadata {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
  padding-top: 0.25rem;
  font-size: 0.75rem;
}

.task-error-code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
  color: var(--muted-foreground);
  background-color: var(--muted);
  padding: 0.25rem 0.5rem;
  border-radius: 0.375rem;
}

.task-flow-badge {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
  font-weight: 600;
  padding: 0.25rem 0.5rem;
  border-radius: 0.375rem;
}

.task-flow-foc      { background: hsl(152, 69%, 96%); color: hsl(152, 69%, 31%); }
.task-flow-proforma { background: hsl(214, 95%, 96%); color: hsl(214, 95%, 45%); }
.task-flow-stripe   { background: hsl(270, 67%, 96%); color: hsl(270, 67%, 47%); }

.task-timestamp,
.task-retry {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  color: var(--muted-foreground);
}

.task-timestamp i,
.task-retry i {
  width: 14px;
  height: 14px;
}

.task-retry.exhausted {
  color: hsl(0, 84%, 60%);
}

/* === LINKS === */
.task-links {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding-top: 0.25rem;
  font-size: 0.875rem;
}

.task-event-link {
  color: var(--muted-foreground);
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: color 0.2s ease;
}

.task-event-link:hover {
  color: hsl(var(--primary));
  text-decoration: underline;
}

.task-order-link {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.75rem;
  color: var(--muted-foreground);
  background-color: var(--muted);
  padding: 0.125rem 0.5rem;
  border-radius: 0.25rem;
  text-decoration: none;
  transition: color 0.2s ease;
}

.task-order-link:hover {
  color: hsl(var(--primary));
}

/* === ACTION BAR === */
.task-action-bar {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
  padding: 0.75rem 1.25rem;
  border-top: 1px solid var(--border);
  background-color: hsl(var(--muted) / 0.3);
}

/* === ACTION BUTTONS === */
.btn-action-primary,
.btn-action-outline,
.btn-action-destructive {
  height: 2.25rem;
  padding-left: 1rem;
  padding-right: 1rem;
  font-size: 0.875rem;
  font-weight: 500;
  border-radius: var(--radius);
  display: inline-flex;
  align-items: center;
  cursor: pointer;
  transition: all 0.2s ease;
  text-decoration: none;
}

.btn-action-primary i,
.btn-action-outline i,
.btn-action-destructive i {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
}

.btn-action-primary span,
.btn-action-outline span,
.btn-action-destructive span {
  margin-left: 0.5rem;
}

.btn-action-primary {
  background-color: hsl(var(--primary));
  color: hsl(var(--primary-foreground));
  border: none;
  box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
}

.btn-action-primary:hover {
  background-color: hsl(var(--primary) / 0.9);
}

.btn-action-outline {
  background-color: hsl(var(--background));
  color: hsl(var(--foreground));
  border: 1px solid hsl(var(--border));
}

.btn-action-outline:hover {
  background-color: hsl(var(--accent));
}

.btn-action-destructive {
  background-color: hsl(var(--destructive));
  color: hsl(var(--destructive-foreground));
  border: none;
}

.btn-action-destructive:hover {
  background-color: hsl(var(--destructive) / 0.9);
}
```

---

## ⚠️ Ważne zasady

1. **Border-left 4px** - ZAWSZE obecny, kolor zależy od severity
2. **Pierwszy przycisk = PRIMARY** - wypełniony, niebieski
3. **Ikony 14px w metadata/akcjach, 16px w kontenerze kategorii**
4. **flex-wrap** - wszędzie dla responsywności
5. **gap zamiast margin** - konsystentne odstępy

---

*Ostatnia aktualizacja: 2026-01-24*
*Źródło: TaskCard.tsx (React)*
