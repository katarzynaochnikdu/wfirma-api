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