# Send Message Dialog - Specyfikacja Komponentu

## Przeznaczenie
Modal dialogowy do wysyłania wiadomości email do wybranych odbiorców z możliwością wyboru szablonu lub własnej treści.

## Lokalizacja
- **React**: `src/components/admin/SendMessageDialog.tsx`
- **HTML**: `export/_send_message_dialog.html`

---

## Anatomia

```
┌──────────────────────────────────────────────────────────────────────────┐
│  ╔════════════════════════════════════════════════════════════════════╗  │
│  ║ ✉️ Wyślij wiadomość                                           [X] ║  │
│  ║ Wyślij wiadomość do uczestników wydarzenia: Konferencja 2025      ║  │
│  ╠════════════════════════════════════════════════════════════════════╣  │
│  ║                                                                    ║  │
│  ║ 👥 Odbiorcy (12)                                                   ║  │
│  ║ ┌──────────────────────────────────────────────────────────────┐  ║  │
│  ║ │ [Jan Kowalski ×] [Anna Nowak ×] [Piotr Wiśniewski ×]        │  ║  │
│  ║ │ [Maria Kwiatkowska ×] [+8 więcej]                           │  ║  │
│  ║ └──────────────────────────────────────────────────────────────┘  ║  │
│  ║                                                                    ║  │
│  ║ Szablon wiadomości                                                 ║  │
│  ║ ┌──────────────────────────────────────────────────────────────┐  ║  │
│  ║ │ Potwierdzenie rejestracji                              ⌄   │  ║  │
│  ║ └──────────────────────────────────────────────────────────────┘  ║  │
│  ║                                                                    ║  │
│  ║ Treść wiadomości (jeśli "Własna wiadomość")                       ║  │
│  ║ ┌──────────────────────────────────────────────────────────────┐  ║  │
│  ║ │                                                              │  ║  │
│  ║ │ Wprowadź treść wiadomości...                                │  ║  │
│  ║ │                                                              │  ║  │
│  ║ └──────────────────────────────────────────────────────────────┘  ║  │
│  ║                                                                    ║  │
│  ╠════════════════════════════════════════════════════════════════════╣  │
│  ║                              [Anuluj]  [📤 Wyślij wiadomość (12)] ║  │
│  ╚════════════════════════════════════════════════════════════════════╝  │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
       ▲ Backdrop (semi-transparent overlay)
```

---

## Szablony wiadomości

| ID | Nazwa | Opis |
|----|-------|------|
| `confirmation` | Potwierdzenie rejestracji | Domyślna wiadomość potwierdzająca rejestrację |
| `reminder` | Przypomnienie o wydarzeniu | Przypomnienie przed wydarzeniem |
| `ticket` | Bilet elektroniczny | Wysyłka biletu/QR kodu |
| `update` | Aktualizacja informacji | Zmiana szczegółów wydarzenia |
| `custom` | Wiadomość własna | Własna treść (pokazuje textarea) |

---

## CSS Classes

```css
/* Modal Backdrop */
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  animation: fadeIn 0.15s ease;
}

.modal-backdrop.hidden {
  display: none;
}

/* Modal Content */
.modal-content {
  background: var(--card);
  border-radius: var(--radius-lg, 0.75rem);
  width: 100%;
  max-width: 500px;
  max-height: 90vh;
  overflow: hidden;
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
  animation: slideUp 0.2s ease;
}

.modal-lg {
  max-width: 600px;
}

/* Modal Header */
.modal-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 1.25rem 1.5rem;
  border-bottom: 1px solid var(--border);
}

.modal-header-content {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.modal-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 1.125rem;
  font-weight: 600;
  color: var(--foreground);
  margin: 0;
}

.modal-title i {
  width: 20px;
  height: 20px;
}

.modal-description {
  font-size: 0.875rem;
  color: var(--muted-foreground);
  margin: 0;
}

.modal-close {
  width: 2rem;
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

.modal-close:hover {
  background: var(--muted);
  color: var(--foreground);
}

.modal-close i {
  width: 1rem;
  height: 1rem;
}

/* Modal Body */
.modal-body {
  padding: 1.5rem;
  overflow-y: auto;
  max-height: calc(90vh - 180px);
}

/* Modal Footer */
.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  padding: 1rem 1.5rem;
  border-top: 1px solid var(--border);
  background: var(--muted);
}

/* Recipients Tags */
.recipients-container {
  margin-bottom: 1rem;
}

.recipients-label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--foreground);
  margin-bottom: 0.5rem;
}

.recipients-label i {
  width: 16px;
  height: 16px;
  color: var(--muted-foreground);
}

.recipients-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.375rem;
  padding: 0.75rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: hsl(210, 40%, 96%, 0.5);
  min-height: 56px;
  max-height: 96px;
  overflow-y: auto;
}

.recipient-tag {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.25rem 0.5rem;
  background: var(--secondary);
  border-radius: 9999px;
  font-size: 0.75rem;
  font-weight: 500;
  color: var(--foreground);
}

.recipient-tag-remove {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 1rem;
  height: 1rem;
  border: none;
  background: transparent;
  border-radius: 50%;
  cursor: pointer;
  color: var(--muted-foreground);
  transition: background 0.15s, color 0.15s;
  padding: 0;
}

.recipient-tag-remove:hover {
  background: var(--destructive);
  color: white;
}

.recipient-tag-remove i {
  width: 0.75rem;
  height: 0.75rem;
}

.recipient-tag-more {
  background: transparent;
  border: 1px dashed var(--border);
  color: var(--muted-foreground);
}

/* Form Group */
.form-group {
  margin-bottom: 1rem;
}

.form-group:last-child {
  margin-bottom: 0;
}

.form-label {
  display: block;
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--foreground);
  margin-bottom: 0.5rem;
}

.form-select {
  width: 100%;
  padding: 0.625rem 2.25rem 0.625rem 0.75rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  font-size: 0.875rem;
  background: var(--background);
  color: var(--foreground);
  cursor: pointer;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 0.75rem center;
}

.form-select:focus {
  outline: none;
  border-color: var(--ring);
  box-shadow: 0 0 0 3px hsl(212, 100%, 42%, 0.1);
}

.form-textarea {
  width: 100%;
  padding: 0.75rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  font-size: 0.875rem;
  font-family: inherit;
  background: var(--background);
  color: var(--foreground);
  resize: vertical;
  min-height: 100px;
}

.form-textarea:focus {
  outline: none;
  border-color: var(--ring);
  box-shadow: 0 0 0 3px hsl(212, 100%, 42%, 0.1);
}

.form-textarea::placeholder {
  color: var(--muted-foreground);
}

/* Animations */
@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes slideUp {
  from {
    opacity: 0;
    transform: translateY(16px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* Button states */
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn.loading {
  position: relative;
  color: transparent;
}

.btn.loading::after {
  content: '';
  position: absolute;
  width: 1rem;
  height: 1rem;
  border: 2px solid currentColor;
  border-right-color: transparent;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
```

---

## HTML Template (Jinja2)

```html
<!-- SEND MESSAGE MODAL -->
<div id="send-message-modal" class="modal-backdrop hidden">
  <div class="modal-content modal-lg">
    <div class="modal-header">
      <div class="modal-header-content">
        <h3 class="modal-title">
          <i data-lucide="mail"></i>
          Wyślij wiadomość
        </h3>
        <p class="modal-description" id="modal-event-name">
          Wyślij wiadomość do wybranych odbiorców
        </p>
      </div>
      <button class="modal-close" onclick="closeSendMessageModal()">
        <i data-lucide="x"></i>
      </button>
    </div>
    
    <div class="modal-body">
      <!-- Recipients -->
      <div class="recipients-container">
        <label class="recipients-label">
          <i data-lucide="users"></i>
          Odbiorcy (<span id="recipient-count">0</span>)
        </label>
        <div id="recipients-list" class="recipients-tags">
          <!-- Recipients will be inserted here by JS -->
        </div>
      </div>
      
      <!-- Template Select -->
      <div class="form-group">
        <label class="form-label" for="message-template">Szablon wiadomości</label>
        <select id="message-template" class="form-select" onchange="handleTemplateChange()">
          <option value="" disabled selected>Wybierz szablon...</option>
          <option value="confirmation">Potwierdzenie rejestracji</option>
          <option value="reminder">Przypomnienie o wydarzeniu</option>
          <option value="ticket">Bilet elektroniczny</option>
          <option value="update">Aktualizacja informacji</option>
          <option value="custom">Wiadomość własna</option>
        </select>
      </div>
      
      <!-- Custom Message (conditional) -->
      <div id="custom-message-section" class="form-group" style="display: none;">
        <label class="form-label" for="custom-message">Treść wiadomości</label>
        <textarea id="custom-message" class="form-textarea" rows="6" placeholder="Wprowadź treść wiadomości..."></textarea>
      </div>
    </div>
    
    <div class="modal-footer">
      <button class="btn btn-outline" onclick="closeSendMessageModal()">Anuluj</button>
      <button id="send-message-btn" class="btn btn-primary" onclick="sendMessage()" disabled>
        <i data-lucide="send"></i>
        <span id="send-btn-text">Wyślij wiadomość</span>
      </button>
    </div>
  </div>
</div>
```

---

## JavaScript

```javascript
// State
let messageRecipients = [];

// Open modal with recipients
function openSendMessageModal(recipients, eventName) {
  messageRecipients = recipients;
  
  const modal = document.getElementById('send-message-modal');
  const eventNameEl = document.getElementById('modal-event-name');
  const countEl = document.getElementById('recipient-count');
  const listEl = document.getElementById('recipients-list');
  const sendBtn = document.getElementById('send-message-btn');
  const sendBtnText = document.getElementById('send-btn-text');
  
  // Set event name
  if (eventName) {
    eventNameEl.innerHTML = `Wyślij wiadomość do uczestników wydarzenia: <strong>${eventName}</strong>`;
  } else {
    eventNameEl.textContent = 'Wyślij wiadomość do wybranych odbiorców';
  }
  
  // Set count
  countEl.textContent = recipients.length;
  sendBtnText.textContent = `Wyślij wiadomość (${recipients.length})`;
  
  // Render recipients (max 10, then +X więcej)
  listEl.innerHTML = '';
  const displayRecipients = recipients.slice(0, 10);
  
  displayRecipients.forEach((recipient, index) => {
    const tag = document.createElement('span');
    tag.className = 'recipient-tag';
    tag.innerHTML = `
      ${recipient.name || recipient.email}
      <button class="recipient-tag-remove" onclick="removeRecipient(${index})">
        <i data-lucide="x"></i>
      </button>
    `;
    listEl.appendChild(tag);
  });
  
  if (recipients.length > 10) {
    const moreTag = document.createElement('span');
    moreTag.className = 'recipient-tag recipient-tag-more';
    moreTag.textContent = `+${recipients.length - 10} więcej`;
    listEl.appendChild(moreTag);
  }
  
  // Reset form
  document.getElementById('message-template').value = '';
  document.getElementById('custom-message').value = '';
  document.getElementById('custom-message-section').style.display = 'none';
  sendBtn.disabled = true;
  
  // Show modal
  modal.classList.remove('hidden');
  
  // Reinitialize Lucide icons
  if (typeof lucide !== 'undefined') {
    lucide.createIcons();
  }
}

// Close modal
function closeSendMessageModal() {
  const modal = document.getElementById('send-message-modal');
  modal.classList.add('hidden');
  messageRecipients = [];
}

// Remove a recipient
function removeRecipient(index) {
  messageRecipients.splice(index, 1);
  
  if (messageRecipients.length === 0) {
    closeSendMessageModal();
    return;
  }
  
  // Re-render
  const eventName = document.getElementById('modal-event-name').querySelector('strong')?.textContent;
  openSendMessageModal(messageRecipients, eventName);
}

// Handle template change
function handleTemplateChange() {
  const template = document.getElementById('message-template').value;
  const customSection = document.getElementById('custom-message-section');
  const sendBtn = document.getElementById('send-message-btn');
  
  if (template === 'custom') {
    customSection.style.display = 'block';
    sendBtn.disabled = document.getElementById('custom-message').value.trim() === '';
  } else {
    customSection.style.display = 'none';
    sendBtn.disabled = !template;
  }
}

// Handle custom message input
document.getElementById('custom-message')?.addEventListener('input', function() {
  const sendBtn = document.getElementById('send-message-btn');
  sendBtn.disabled = this.value.trim() === '';
});

// Send message
function sendMessage() {
  const template = document.getElementById('message-template').value;
  const customMessage = document.getElementById('custom-message').value;
  const sendBtn = document.getElementById('send-message-btn');
  
  if (!template) {
    showToast('Wybierz szablon wiadomości', 'error');
    return;
  }
  
  if (template === 'custom' && !customMessage.trim()) {
    showToast('Wprowadź treść wiadomości', 'error');
    return;
  }
  
  // Set loading state
  sendBtn.classList.add('loading');
  sendBtn.disabled = true;
  
  const recipientIds = messageRecipients.map(r => r.id);
  
  fetch('/api/messages/send', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      template,
      custom_message: template === 'custom' ? customMessage : null,
      recipient_ids: recipientIds
    })
  })
  .then(response => response.json())
  .then(data => {
    showToast(`Wiadomość wysłana do ${recipientIds.length} odbiorców`, 'success');
    closeSendMessageModal();
  })
  .catch(err => {
    showToast('Błąd wysyłki wiadomości', 'error');
    sendBtn.classList.remove('loading');
    sendBtn.disabled = false;
  });
}

// Close on backdrop click
document.getElementById('send-message-modal')?.addEventListener('click', function(e) {
  if (e.target === this) {
    closeSendMessageModal();
  }
});

// Close on Escape key
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    closeSendMessageModal();
  }
});
```

---

## Ikony Lucide

| Element | Ikona |
|---------|-------|
| Modal title | `mail` |
| Recipients label | `users` |
| Remove recipient | `x` |
| Close button | `x` |
| Send button | `send` |

---

## Integracja

### Wywołanie z przycisków

```html
<!-- Z listy uczestników -->
<button class="btn btn-outline" onclick="openSendMessageModal(selectedParticipants, '{{ event.event_name }}')">
  <i data-lucide="mail"></i>
  Wyślij wiadomość
</button>

<!-- Z pojedynczego uczestnika -->
<button class="btn-icon" onclick="openSendMessageModal([{id: '{{ p.id }}', email: '{{ p.email }}', name: '{{ p.first_name }} {{ p.last_name }}'}])">
  <i data-lucide="mail"></i>
</button>
```

### Include w szablonach

```html
{% include 'admin_v2/_send_message_dialog.html' %}
```
