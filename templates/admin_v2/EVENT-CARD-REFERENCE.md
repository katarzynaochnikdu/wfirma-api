# Event Card - Wzorcowa Dokumentacja CSS/HTML

**Źródło prawdy:** `src/pages/admin/EventsPage.tsx`

---

## 📐 Struktura karty (Anatomia)

```
┌─────────────────────────────────────────────────────────────┐
│  BANNER (aspect-ratio: 3/1)                                 │
│  ┌─────────────────────────────────────────────────────┐    │
│  │                                                     │    │
│  │  [banner image / gradient fallback]           ⚙️    │ <- settings btn (top-3 right-3)
│  │                                                     │    │
│  └─────────────────────────────────────────────────────┘    │
├─────────────────────────────────────────────────────────────┤
│  📄 BODY (p-5 = padding: 1.25rem)                           │
│                                                             │
│  Tytuł Wydarzenia (text-lg, font-semibold, truncate)        │
│                                                             │
│  📅 Data   📍 Miasto  (text-sm, text-muted-foreground, mt-2)│
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  📊 STATS (border-t, grid-cols-2, py-3 mt-4, text-center)   │
│        0                    0                               │
│    ZAMÓWIEŃ            UCZESTNIKÓW                          │
│  (text-xl bold)      (text-xs uppercase tracking-wide)      │
└─────────────────────────────────────────────────────────────┘
```

---

## 🎨 Warianty Kart

### 1. Aktywna Karta
**React (Tailwind):**
```tsx
<Card className="overflow-hidden transition-all group ring-2 ring-primary/20 shadow-md hover:shadow-lg hover:ring-primary/40">
```

**CSS odpowiednik:**
```css
.event-card-active {
  overflow: hidden;
  transition: all 0.2s ease;
  /* ring-2 ring-primary/20 */
  box-shadow: 
    0 4px 6px -1px rgba(0, 0, 0, 0.1),           /* shadow-md */
    0 0 0 2px hsl(var(--primary) / 0.2);         /* ring-2 ring-primary/20 */
}

.event-card-active:hover {
  /* shadow-lg + ring-primary/40 */
  box-shadow: 
    0 10px 15px -3px rgba(0, 0, 0, 0.1),
    0 0 0 2px hsl(var(--primary) / 0.4);
}
```

### 2. Nieaktywna Karta
**React (Tailwind):**
```tsx
<Card className="overflow-hidden opacity-70 hover:opacity-90 transition-all group">
```

**CSS odpowiednik:**
```css
.event-card-inactive {
  overflow: hidden;
  opacity: 0.7;
  transition: all 0.2s ease;
}

.event-card-inactive:hover {
  opacity: 0.9;
}
```

---

## 📏 Wymiary - Tailwind → CSS

| Element | Tailwind | CSS |
|---------|----------|-----|
| **Banner (aktywny)** | `aspect-[3/1]` | `aspect-ratio: 3 / 1;` |
| **Banner (nieaktywny)** | `h-2` | `height: 0.5rem;` (8px) |
| **Body padding** | `p-5` | `padding: 1.25rem;` |
| **Grid gap** | `gap-6` | `gap: 1.5rem;` |
| **Stats margin** | `mt-4` | `margin-top: 1rem;` |
| **Stats padding** | `py-3` | `padding-top: 0.75rem; padding-bottom: 0.75rem;` |
| **Meta margin** | `mt-2` | `margin-top: 0.5rem;` |
| **Meta gap** | `gap-4` | `gap: 1rem;` |
| **Icon gap** | `gap-1.5` | `gap: 0.375rem;` |

---

## 🖼️ Banner Header

### React:
```tsx
<div className="relative aspect-[3/1] overflow-hidden">
  {hasImage ? (
    <img 
      src={event.data.email_header_url} 
      alt={event.event_name}
      className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105"
    />
  ) : (
    <div 
      className="w-full h-full"
      style={{ background: gradient }}
    />
  )}
</div>
```

### CSS:
```css
.event-card-header {
  position: relative;
  aspect-ratio: 3 / 1;
  overflow: hidden;
}

.event-card-banner-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.3s ease;
}

.event-card:hover .event-card-banner-img {
  transform: scale(1.05);
}

/* Gradient fallback gdy brak obrazka */
.event-card-gradient {
  width: 100%;
  height: 100%;
  /* background ustawiany inline */
}
```

### HTML:
```html
<div class="event-card-header">
  {% if banner_url %}
    <img src="{{ banner_url }}" alt="{{ event.event_name }}" class="event-card-banner-img">
  {% else %}
    <div class="event-card-gradient" style="background: linear-gradient(135deg, {{ color1 }}, {{ color2 }});"></div>
  {% endif %}
</div>
```

---

## ⚙️ Settings Button

### React:
```tsx
<Link
  to={`/admin/events/${event.event_id}/edit`}
  onClick={(e) => e.stopPropagation()}
  className="absolute top-3 right-3 h-8 w-8 rounded-full bg-black/40 hover:bg-black/60 flex items-center justify-center text-white transition-colors backdrop-blur-sm"
>
  <Settings className="h-4 w-4" />
</Link>
```

### CSS:
```css
.event-settings-btn {
  position: absolute;
  top: 0.75rem;                              /* top-3 */
  right: 0.75rem;                            /* right-3 */
  width: 2rem;                               /* w-8 */
  height: 2rem;                              /* h-8 */
  border-radius: 9999px;                     /* rounded-full */
  background: rgba(0, 0, 0, 0.4);            /* bg-black/40 */
  backdrop-filter: blur(4px);                /* backdrop-blur-sm */
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  transition: background-color 0.2s ease;
  text-decoration: none;
  z-index: 10;
}

.event-settings-btn:hover {
  background: rgba(0, 0, 0, 0.6);            /* hover:bg-black/60 */
}

.event-settings-btn i {
  width: 16px;                               /* h-4 w-4 */
  height: 16px;
}
```

### HTML:
```html
<a href="...?tab=config" class="event-settings-btn" onclick="event.stopPropagation();" title="Konfiguracja">
  <i data-lucide="settings"></i>
</a>
```

---

## 📝 Tytuł

### React:
```tsx
<h3 className="font-semibold text-lg truncate">{event.event_name}</h3>
```

### CSS:
```css
.event-card-title {
  font-weight: 600;                          /* font-semibold */
  font-size: 1.125rem;                       /* text-lg */
  line-height: 1.75rem;
  white-space: nowrap;                       /* truncate */
  overflow: hidden;
  text-overflow: ellipsis;
  margin: 0;
}
```

---

## 📅 Metadata (Data + Miasto)

### React:
```tsx
<div className="flex flex-wrap gap-4 text-sm text-muted-foreground mt-2">
  {event.data.eventDate && (
    <div className="flex items-center gap-1.5">
      <Calendar className="h-4 w-4" />
      <span>{formattedDate}</span>
    </div>
  )}
  {event.data.eventCity && (
    <div className="flex items-center gap-1.5">
      <MapPin className="h-4 w-4" />
      <span>{event.data.eventCity}</span>
    </div>
  )}
</div>
```

### CSS:
```css
.event-card-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;                                 /* gap-4 */
  margin-top: 0.5rem;                        /* mt-2 */
  font-size: 0.875rem;                       /* text-sm */
  line-height: 1.25rem;
  color: var(--muted-foreground);
}

.event-meta-item {
  display: flex;
  align-items: center;
  gap: 0.375rem;                             /* gap-1.5 */
}

.event-meta-item i {
  width: 16px;                               /* h-4 w-4 */
  height: 16px;
  flex-shrink: 0;                            /* WAŻNE! Zapobiega kurczeniu */
}
```

### HTML:
```html
<div class="event-card-meta">
  {% if event_date %}
  <div class="event-meta-item">
    <i data-lucide="calendar"></i>
    <span>{{ event_date }}</span>
  </div>
  {% endif %}
  {% if event_city %}
  <div class="event-meta-item">
    <i data-lucide="map-pin"></i>
    <span>{{ event_city }}</span>
  </div>
  {% endif %}
</div>
```

---

## 📊 Sekcja Statystyk

### React:
```tsx
<div className="grid grid-cols-2 gap-4 py-3 mt-4 border-t border-border">
  <div className="text-center">
    <div className="text-xl font-bold">0</div>
    <div className="text-xs text-muted-foreground uppercase tracking-wide">Zamówień</div>
  </div>
  <div className="text-center">
    <div className="text-xl font-bold">0</div>
    <div className="text-xs text-muted-foreground uppercase tracking-wide">Uczestników</div>
  </div>
</div>
```

### CSS:
```css
.event-card-stats {
  display: grid;
  grid-template-columns: repeat(2, 1fr);     /* grid-cols-2 */
  gap: 1rem;                                 /* gap-4 */
  padding-top: 0.75rem;                      /* py-3 */
  padding-bottom: 0.75rem;
  margin-top: 1rem;                          /* mt-4 */
  border-top: 1px solid var(--border);       /* border-t border-border */
}

.event-stat {
  text-align: center;
}

.event-stat-value {
  font-size: 1.25rem;                        /* text-xl */
  line-height: 1.75rem;
  font-weight: 700;                          /* font-bold */
}

.event-stat-label {
  font-size: 0.75rem;                        /* text-xs */
  line-height: 1rem;
  color: var(--muted-foreground);
  text-transform: uppercase;
  letter-spacing: 0.025em;                   /* tracking-wide */
}
```

---

## 🔲 Events Grid

### React:
```tsx
<div className="grid grid-cols-1 md:grid-cols-2 gap-6">
```

### CSS:
```css
.events-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1.5rem;                               /* gap-6 */
}

@media (max-width: 768px) {
  .events-grid {
    grid-template-columns: 1fr;
  }
}
```

---

## 🎯 Nagłówek sekcji "Aktywne wydarzenia"

### React:
```tsx
<h2 className="text-lg font-semibold flex items-center gap-2">
  <Circle className="h-2.5 w-2.5 fill-primary text-primary" />
  Aktywne wydarzenia ({activeEvents.length})
</h2>
```

### CSS:
```css
.section-header {
  font-size: 1.125rem;                       /* text-lg */
  font-weight: 600;                          /* font-semibold */
  display: flex;
  align-items: center;
  gap: 0.5rem;                               /* gap-2 */
  margin-bottom: 1rem;
}

.active-dot {
  width: 0.625rem;                           /* h-2.5 w-2.5 */
  height: 0.625rem;
  border-radius: 9999px;
  background-color: hsl(var(--primary));     /* fill-primary */
}
```

### HTML:
```html
<h2 class="section-header">
  <span class="active-dot"></span>
  Aktywne wydarzenia ({{ active_events|length }})
</h2>
```

---

## 📋 Kompletny HTML Template

```html
<!-- AKTYWNA KARTA -->
<a href="{{ url_for('admin_v2_bp.event_room', event_id=event.event_id) }}" class="event-card event-card-active">
  <!-- Banner -->
  <div class="event-card-header">
    {% if banner_url %}
      <img src="{{ banner_url }}" alt="{{ event.event_name }}" class="event-card-banner-img">
    {% else %}
      <div class="event-card-gradient" style="background: linear-gradient(135deg, {{ color1 }}, {{ color2 }});"></div>
    {% endif %}
    
    <!-- Settings button -->
    <a href="...?tab=config" class="event-settings-btn" onclick="event.stopPropagation();">
      <i data-lucide="settings"></i>
    </a>
  </div>
  
  <!-- Body -->
  <div class="event-card-body">
    <h3 class="event-card-title">{{ event.event_name }}</h3>
    
    <div class="event-card-meta">
      {% if event_date %}
      <div class="event-meta-item">
        <i data-lucide="calendar"></i>
        <span>{{ event_date }}</span>
      </div>
      {% endif %}
      {% if event_city %}
      <div class="event-meta-item">
        <i data-lucide="map-pin"></i>
        <span>{{ event_city }}</span>
      </div>
      {% endif %}
    </div>
    
    <!-- Stats -->
    <div class="event-card-stats">
      <div class="event-stat">
        <div class="event-stat-value">{{ event.order_count or 0 }}</div>
        <div class="event-stat-label">Zamówień</div>
      </div>
      <div class="event-stat">
        <div class="event-stat-value">{{ event.participant_count or 0 }}</div>
        <div class="event-stat-label">Uczestników</div>
      </div>
    </div>
  </div>
</a>
```

---

## 📋 Kompletny CSS

```css
/* === EVENT CARD BASE === */
.event-card {
  display: block;
  text-decoration: none;
  color: inherit;
  background: var(--card);
  border-radius: var(--radius);
  border: 1px solid var(--border);
}

/* === ACTIVE CARD === */
.event-card-active {
  overflow: hidden;
  transition: all 0.2s ease;
  box-shadow: 
    0 4px 6px -1px rgba(0, 0, 0, 0.1),
    0 0 0 2px hsl(var(--primary) / 0.2);
}

.event-card-active:hover {
  box-shadow: 
    0 10px 15px -3px rgba(0, 0, 0, 0.1),
    0 0 0 2px hsl(var(--primary) / 0.4);
}

/* === INACTIVE CARD === */
.event-card-inactive {
  overflow: hidden;
  opacity: 0.7;
  transition: all 0.2s ease;
}

.event-card-inactive:hover {
  opacity: 0.9;
}

/* === BANNER === */
.event-card-header {
  position: relative;
  aspect-ratio: 3 / 1;
  overflow: hidden;
}

.event-card-banner-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.3s ease;
}

.event-card:hover .event-card-banner-img {
  transform: scale(1.05);
}

.event-card-gradient {
  width: 100%;
  height: 100%;
}

/* === INACTIVE BANNER (thin line) === */
.event-card-header-minimal {
  height: 0.5rem;
  width: 100%;
}

/* === SETTINGS BUTTON === */
.event-settings-btn {
  position: absolute;
  top: 0.75rem;
  right: 0.75rem;
  width: 2rem;
  height: 2rem;
  border-radius: 9999px;
  background: rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  transition: background-color 0.2s ease;
  text-decoration: none;
  z-index: 10;
}

.event-settings-btn:hover {
  background: rgba(0, 0, 0, 0.6);
}

.event-settings-btn i {
  width: 16px;
  height: 16px;
}

/* === BODY === */
.event-card-body {
  padding: 1.25rem;
  display: flex;
  flex-direction: column;
}

/* === TITLE === */
.event-card-title {
  font-weight: 600;
  font-size: 1.125rem;
  line-height: 1.75rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin: 0;
}

/* === METADATA === */
.event-card-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  margin-top: 0.5rem;
  font-size: 0.875rem;
  line-height: 1.25rem;
  color: var(--muted-foreground);
}

.event-meta-item {
  display: flex;
  align-items: center;
  gap: 0.375rem;
}

.event-meta-item i {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
}

/* === STATS === */
.event-card-stats {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1rem;
  padding-top: 0.75rem;
  padding-bottom: 0.75rem;
  margin-top: 1rem;
  border-top: 1px solid var(--border);
}

.event-stat {
  text-align: center;
}

.event-stat-value {
  font-size: 1.25rem;
  line-height: 1.75rem;
  font-weight: 700;
}

.event-stat-label {
  font-size: 0.75rem;
  line-height: 1rem;
  color: var(--muted-foreground);
  text-transform: uppercase;
  letter-spacing: 0.025em;
}

/* === GRID === */
.events-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1.5rem;
}

@media (max-width: 768px) {
  .events-grid {
    grid-template-columns: 1fr;
  }
}

/* === SECTION HEADER === */
.section-header {
  font-size: 1.125rem;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 1rem;
}

.active-dot {
  width: 0.625rem;
  height: 0.625rem;
  border-radius: 9999px;
  background-color: hsl(var(--primary));
}
```

---

## ⚠️ Kluczowe różnice React vs HTML

| Aspekt | React | HTML/CSS |
|--------|-------|----------|
| **Ring effect** | `ring-2 ring-primary/20` | `box-shadow: ... 0 0 0 2px hsl(var(--primary) / 0.2)` |
| **Group hover** | `group` + `group-hover:scale-105` | `.event-card:hover .event-card-banner-img` |
| **Backdrop blur** | `backdrop-blur-sm` | `backdrop-filter: blur(4px)` |
| **Truncate** | `truncate` | `white-space: nowrap; overflow: hidden; text-overflow: ellipsis;` |
| **Flex shrink** | `shrink-0` | `flex-shrink: 0;` |

---

*Ostatnia aktualizacja: 2026-01-24*
*Źródło: EventsPage.tsx (React)*
