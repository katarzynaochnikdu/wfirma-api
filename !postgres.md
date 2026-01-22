 psql "postgresql://database_backstage_user:CQM3pvq6BLZL9IYxwITctNCyR1xz7Ssa@dpg-d5n08f9r0fns73f94m4g-a.frankfurt-postgres.render.com/backstagedatabase"

Najpierw bez CASCADE:
TRUNCATE TABLE
  backstage_webhook_events,
  mail_log,
  wfirma_documents,
  stripe_sessions,
  participants,
  order_tickets,
  orders
RESTART IDENTITY;

Jeśli dostaniesz błąd o zależnościach FK, użyj wersji z CASCADE:
TRUNCATE TABLE
  backstage_webhook_events,
  mail_log,
  wfirma_documents,
  stripe_sessions,
  participants,
  order_tickets,
  orders
RESTART IDENTITY CASCADE;


Sprawdź, czy jest pusto
SELECT COUNT(*) FROM orders;
SELECT COUNT(*) FROM participants;
SELECT COUNT(*) FROM wfirma_documents;
SELECT COUNT(*) FROM mail_log;

Wyjdz
\q

DELETE FROM backstage_webhook_events     
WHERE dedupe_key = '70cdf3bc07456808b23a737505cb3b01';


SELECT 
  (SELECT COUNT(*) FROM backstage_webhook_events) AS webhook_events,
  (SELECT COUNT(*) FROM mail_log) AS mail_log,
  (SELECT COUNT(*) FROM wfirma_documents) AS wfirma_docs,
  (SELECT COUNT(*) FROM stripe_sessions) AS stripe,
  (SELECT COUNT(*) FROM participants) AS participants,
  (SELECT COUNT(*) FROM order_tickets) AS order_tickets,
  (SELECT COUNT(*) FROM orders) AS orders;


  -- Zamówienia
SELECT order_id, event_id, status, purchaser_email, total_amount, created_at FROM orders ORDER BY created_at DESC;

-- Uczestnicy
SELECT id, order_id, event_id, first_name, last_name, email, ticket_class_id FROM participants ORDER BY id DESC;

-- Bilety w zamówieniach
SELECT id, order_id, ticket_class_id, ticket_name, quantity FROM order_tickets;

-- Sesje Stripe
SELECT id, order_id, stripe_session_id, status, created_at FROM stripe_sessions ORDER BY created_at DESC;

-- Dokumenty wFirma
SELECT id, order_id, document_type, wfirma_id, status, created_at FROM wfirma_documents ORDER BY created_at DESC;

-- Logi maili
SELECT id, event_order_id, direction, template_key, to_email, status, created_at FROM mail_log ORDER BY created_at DESC;

-- Webhooki Backstage
SELECT id, dedupe_key, event_type, processed, created_at FROM backstage_webhook_events ORDER BY created_at DESC;
SELECT id FROM backstage_webhook_events ORDER BY created_at DESC;
