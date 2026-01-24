# 📖 Dokumentacja Stylów Ikon - Medidesk Admin

Kompletna referencyjna lista wszystkich stylów ikon używanych w systemie.

---

## 🎯 Rozmiary Ikon

| Rozmiar | Tailwind | CSS | Użycie |
|---------|----------|-----|--------|
| **XS** | `h-3 w-3` | `12px` | Mikro-ikony w badge'ach |
| **S** | `h-3.5 w-3.5` | `14px` | Metadata (czas, retry), przyciski akcji |
| **M (domyślny)** | `h-4 w-4` | `16px` | Większość ikon UI, tabele, formularze |
| **L** | `h-5 w-5` | `20px` | Nawigacja sidebar, ważne akcje |
| **XL** | `h-6 w-6` | `24px` | Hero ikony, puste stany |

```tsx
// React - rozmiary ikon
<Clock className="h-3.5 w-3.5" />  // S - metadata
<Search className="h-4 w-4" />      // M - standardowa
<Home className="h-5 w-5" />        // L - nawigacja
```

```html
<!-- HTML/Jinja2 - rozmiary ikon -->
<i data-lucide="clock" style="width: 14px; height: 14px;"></i>
<i data-lucide="search" style="width: 16px; height: 16px;"></i>
<i data-lucide="home" style="width: 20px; height: 20px;"></i>
```

---

## 🎨 Kolory Semantyczne

| Token | Tailwind | CSS Variable | Użycie |
|-------|----------|--------------|--------|
| **Primary** | `text-primary` | `var(--primary)` | Akcje główne, linki, branding |
| **Muted** | `text-muted-foreground` | `var(--muted-foreground)` | Metadata, ikony nieaktywne |
| **Destructive** | `text-destructive` | `var(--destructive)` | Błędy krytyczne, kasowanie |
| **Success** | `text-emerald-600` | `var(--success)` | Sukces, opłacone, potwierdzone |
| **Warning** | `text-amber-600` | `var(--warning)` | Ostrzeżenia, oczekujące |
| **Info** | `text-sky-600` | `hsl(195, 100%, 35%)` | Informacje, nowe elementy |

```tsx
// React - kolory semantyczne
<CheckCircle className="h-4 w-4 text-emerald-600" />    // Sukces
<AlertTriangle className="h-4 w-4 text-amber-600" />    // Ostrzeżenie
<XCircle className="h-4 w-4 text-destructive" />        // Błąd
<Clock className="h-4 w-4 text-muted-foreground" />     // Neutralna
```

---

## 📦 Kontenery Ikon

### 1. Stat Icon (Dashboard)
Duży kontener 40×40px dla statystyk.

```css
/* CSS */
.stat-icon {
  width: 2.5rem;      /* 40px */
  height: 2.5rem;
  border-radius: var(--radius);
  display: flex;
  align-items: center;
  justify-content: center;
}

.stat-icon i {
  width: 1.25rem;     /* 20px */
  height: 1.25rem;
}

/* Warianty kolorystyczne */
.stat-icon.blue   { background: hsl(212, 100%, 42%, 0.1); color: var(--primary); }
.stat-icon.green  { background: var(--success-bg); color: var(--success); }
.stat-icon.cyan   { background: hsl(195, 100%, 42%, 0.1); color: hsl(195, 100%, 35%); }
.stat-icon.purple { background: hsl(270, 70%, 50%, 0.1); color: hsl(270, 70%, 50%); }
.stat-icon.amber  { background: hsl(45, 90%, 50%, 0.1); color: hsl(45, 90%, 40%); }
.stat-icon.red    { background: hsl(0, 70%, 50%, 0.1); color: var(--destructive); }
```

```tsx
// React equivalent
<div className="p-2 rounded-lg bg-muted">
  <Icon className="h-4 w-4 text-muted-foreground" />
</div>

// Z kolorem
<div className="p-2.5 rounded-lg bg-primary/10">
  <Icon className="h-5 w-5 text-primary" />
</div>
```

```html
<!-- HTML -->
<div class="stat-icon blue">
  <i data-lucide="shopping-cart"></i>
</div>
```

---

### 2. Task Card Icon (Work Queue)
Kontener 40×40px dla kategorii zadań.

```tsx
// React
<div className="shrink-0 p-2.5 rounded-lg bg-muted/60">
  <CategoryIcon className="h-4 w-4 text-destructive" />
</div>
```

```html
<!-- HTML -->
<div style="
  flex-shrink: 0;
  padding: 0.625rem;
  border-radius: var(--radius);
  background: hsl(var(--muted) / 0.6);
">
  <i data-lucide="alert-triangle" style="width: 16px; height: 16px; color: var(--destructive);"></i>
</div>
```

---

### 3. Timeline Icon (Historia)
Okrągły kontener 40×40px dla osi czasu.

```css
/* CSS */
.timeline-v2-icon {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.timeline-v2-icon svg,
.timeline-v2-icon i {
  width: 16px;
  height: 16px;
}

/* Typy wydarzeń */
.timeline-v2-icon.status_change { background: hsl(212, 90%, 94%); color: hsl(212, 100%, 42%); }
.timeline-v2-icon.payment       { background: hsl(160, 70%, 92%); color: hsl(160, 82%, 35%); }
.timeline-v2-icon.document      { background: hsl(270, 70%, 94%); color: hsl(270, 70%, 50%); }
.timeline-v2-icon.email         { background: hsl(45, 90%, 92%);  color: hsl(45, 90%, 40%); }
.timeline-v2-icon.note          { background: hsl(210, 15%, 93%); color: hsl(210, 15%, 45%); }
```

---

### 4. Button Icon (Samodzielny przycisk)
Kwadratowy przycisk 32×32px z ikoną.

```css
/* CSS */
.btn-icon {
  width: 2rem;        /* 32px */
  height: 2rem;
  border: none;
  background: transparent;
  border-radius: var(--radius);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--muted-foreground);
  transition: background 0.15s, color 0.15s;
}

.btn-icon:hover {
  background: var(--muted);
  color: var(--foreground);
}

.btn-icon i {
  width: 1rem;        /* 16px */
  height: 1rem;
}
```

```tsx
// React - użyj Button variant="ghost" size="icon"
<Button variant="ghost" size="icon" className="h-8 w-8">
  <Settings className="h-4 w-4" />
</Button>
```

---

### 5. Avatar Initials
Okrągły kontener 40×40px dla inicjałów.

```css
/* CSS */
.avatar-initials {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: hsl(212, 100%, 42%, 0.1);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--primary);
  flex-shrink: 0;
}

.avatar-initials.small {
  width: 32px;
  height: 32px;
  font-size: 0.75rem;
}

.avatar-initials.company {
  background: hsl(270, 60%, 50%, 0.1);
  color: hsl(270, 60%, 50%);
}
```

---

### 6. Nav Item Icon (Sidebar)
Ikona nawigacji 20×20px.

```css
/* CSS */
.nav-item i {
  width: 1.25rem;     /* 20px */
  height: 1.25rem;
  flex-shrink: 0;
}
```

```tsx
// React
<Icon className="h-5 w-5 shrink-0" />
```

---

### 7. Status Badge Icon
Mała ikona w badge statusu.

```tsx
// React - StatusBadge component
<span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border">
  <Icon className="h-3.5 w-3.5" />
  {label}
</span>
```

```html
<!-- HTML -->
<span class="status-badge status-paid">
  <i data-lucide="check-circle" style="width: 14px; height: 14px;"></i>
  Opłacone
</span>
```

---

## 🔧 Ikony wg Kategorii

### Nawigacja
| Ikona | Nazwa | Użycie |
|-------|-------|--------|
| 🏠 | `Home` | Dashboard / Start |
| 📅 | `Calendar` | Wydarzenia |
| 🛒 | `ShoppingCart` | Zamówienia |
| 👥 | `Users` | Uczestnicy |
| 💬 | `MessageSquare` | Komunikacja |
| ⚙️ | `Settings` | Ustawienia |
| 🔗 | `Link` | Integracje |

### Statusy
| Ikona | Nazwa | Status | Kolor |
|-------|-------|--------|-------|
| ✅ | `CheckCircle` | Opłacone / Sukces | `text-emerald-600` |
| ⏱️ | `Clock` | Oczekuje | `text-amber-600` |
| 📥 | `Inbox` | Otrzymane | `text-sky-600` |
| ❌ | `XCircle` | Anulowane | `text-red-500` |
| 🔄 | `RotateCcw` | Zwrócone | `text-slate-500` |
| 👤+ | `UserPlus` | Zarejestrowany | `text-sky-600` |
| ✉️ | `Mail` | Powiadomiony | `text-emerald-600` |
| 👤✓ | `UserCheck` | Zameldowany | `text-violet-600` |

### Work Queue - Kategorie Błędów
| Ikona | Nazwa | Kategoria | Kolor |
|-------|-------|-----------|-------|
| ⚠️ | `AlertTriangle` | Błąd krytyczny | `text-destructive` |
| 💳 | `CreditCard` | Płatności | `text-amber-600` |
| ✉️ | `Mail` | Email | `text-sky-600` |
| 📄 | `FileText` | Dokumenty | `text-violet-600` |
| 🔗 | `Link` | Integracje | `text-orange-600` |
| ⚡ | `Zap` | Automatyzacje | `text-emerald-600` |

### Akcje
| Ikona | Nazwa | Akcja |
|-------|-------|-------|
| ➕ | `Plus` | Dodaj nowy |
| ✏️ | `Pencil` | Edytuj |
| 🗑️ | `Trash2` | Usuń |
| 📥 | `Download` | Pobierz |
| 📤 | `Upload` | Wyślij |
| 🔄 | `RefreshCw` | Odśwież / Ponów |
| 👁️ | `Eye` | Podgląd |
| 🔍 | `Search` | Szukaj |
| 📋 | `Copy` | Kopiuj |
| ↗️ | `ExternalLink` | Otwórz zewnętrznie |

---

## ⚠️ Typowe Problemy

### 1. Ikony nie renderują się (HTML)
```html
<!-- Dodaj na końcu body -->
<script>
document.addEventListener('DOMContentLoaded', () => {
  lucide.createIcons();
});
</script>
```

### 2. Ikony są za duże/małe
```tsx
// ❌ Źle - brak rozmiaru
<Clock />

// ✅ Dobrze - zawsze podawaj rozmiar
<Clock className="h-4 w-4" />
```

### 3. Ikona nie wyrównuje się z tekstem
```tsx
// ✅ Użyj flex + items-center + gap
<span className="flex items-center gap-1.5">
  <Clock className="h-3.5 w-3.5" />
  2h temu
</span>
```

### 4. Kontener ikony się kurczy
```tsx
// ✅ Dodaj shrink-0 do kontenera
<div className="shrink-0 p-2 rounded-lg bg-muted">
  <Icon className="h-4 w-4" />
</div>
```

---

## 📐 Quick Reference - Kombinacje

```tsx
// Metadata z ikoną (czas, licznik)
<span className="text-muted-foreground flex items-center gap-1">
  <Clock className="h-3.5 w-3.5" />
  2h temu
</span>

// Ikona w kontenerze (kategoria, typ)
<div className="shrink-0 p-2.5 rounded-lg bg-muted/60">
  <Icon className="h-4 w-4 text-primary" />
</div>

// Przycisk z ikoną
<Button variant="outline" size="sm">
  <Download className="h-3.5 w-3.5 mr-1.5" />
  Eksport
</Button>

// Badge ze statusem
<span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-50 text-emerald-600 border border-emerald-200">
  <CheckCircle className="h-3.5 w-3.5" />
  Opłacone
</span>
```

---

*Ostatnia aktualizacja: Styczeń 2026*
