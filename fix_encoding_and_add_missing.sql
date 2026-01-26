-- ============================================================================
-- FIX ENCODING + ADD MISSING - Naprawa i uzupełnienie danych
-- Event: 24311000000687006 (Amoz Connect Warszawa)
-- Na podstawie CSV z Zoho Backstage (26 Jan 2026)
-- ============================================================================

-- ============================================================================
-- CZĘŚĆ 1: NAPRAW KODOWANIE W ISTNIEJĄCYCH REKORDACH
-- ============================================================================

-- 1.1 ORDERS - napraw nazwiska i firmy
-- ----------------------------------------------------------------------------

-- Szafarczyk – Różycka
UPDATE orders SET 
    purchaser_last_name = 'Szafarczyk – Różycka'
WHERE event_order_id = '24311000000824097';

-- Bączek
UPDATE orders SET 
    purchaser_last_name = 'Bączek'
WHERE event_order_id = '24311000000829018';

-- Czepczyński
UPDATE orders SET 
    purchaser_last_name = 'Czepczyński'
WHERE event_order_id = '24311000000803075';

-- Napraw payment_option_name
UPDATE orders SET 
    payment_option_name = 'Online - link do płatności na platformie Stripe na maila'
WHERE event_id = '24311000000687006' 
  AND payment_option_name IS NOT NULL 
  AND payment_option_name LIKE '%Stripe%';

UPDATE orders SET 
    payment_option_name = 'Faktura Pro forma - płatność na konto bankowe'
WHERE event_id = '24311000000687006' 
  AND payment_option_name IS NOT NULL 
  AND payment_option_name LIKE '%Pro forma%';


-- 1.2 PARTICIPANTS - napraw nazwiska i firmy
-- ----------------------------------------------------------------------------

-- Szafarczyk – Różycka
UPDATE participants SET 
    last_name = 'Szafarczyk – Różycka',
    data = jsonb_set(COALESCE(data, '{}'::jsonb), '{company_name}', '"Mea Clinic"')
WHERE email = 'manager@meaclinic.pl';

-- Bączek
UPDATE participants SET 
    last_name = 'Bączek',
    data = jsonb_set(COALESCE(data, '{}'::jsonb), '{company_name}', '"KRAJMED CENTRUM MEDYCZNE"')
WHERE email = 'krzysztof.baczek@poczta.fm';

-- Lenart / NZOZ Łomianki
UPDATE participants SET 
    data = jsonb_set(COALESCE(data, '{}'::jsonb), '{company_name}', '"NZOZ Łomianki"')
WHERE email = 'biuro@nzozlomianki.pl';

-- Hila i Rysiawa - już kompletne w systemie, pomijamy

-- Czepczyński / NZOZ Łomianki
UPDATE participants SET 
    last_name = 'Czepczyński',
    data = jsonb_set(COALESCE(data, '{}'::jsonb), '{company_name}', '"NZOZ Łomianki"')
WHERE email = 'm.czepczynski@nzozlomianki.pl';

-- Rogozińska
UPDATE participants SET 
    last_name = 'Rogozińska',
    data = jsonb_set(COALESCE(data, '{}'::jsonb), '{company_name}', '"Szpital Południowy"')
WHERE email = 'kamila.rogozinska@szpitalpoludniowy.pl';

-- Kostrzewa - Manowiecka
UPDATE participants SET 
    last_name = 'Kostrzewa - Manowiecka',
    data = jsonb_set(COALESCE(data, '{}'::jsonb), '{company_name}', '"Medispace"')
WHERE email = 'karolina.kostrzewska.manowiecka@medispace.pl';


-- ============================================================================
-- CZĘŚĆ 2: DODAJ BRAKUJĄCE ZAMÓWIENIA (których nie ma w bazie)
-- ============================================================================

-- Sprawdź najpierw które zamówienia brakują:
-- SELECT '24311000000803010' WHERE NOT EXISTS (SELECT 1 FROM orders WHERE event_order_id = '24311000000803010');

-- 2.1 Order: 24311000000803010 (anna.tkacz@mimedica.pl) - FOC 100%
INSERT INTO orders (event_order_id, event_id, purchaser_email, purchaser_first_name, purchaser_last_name, 
                    purchaser_phone, promo_code, total, currency, status, raw)
SELECT '24311000000803010', '24311000000687006', 'anna.tkacz@mimedica.pl', 'Anna', 'Tkacz',
       '+48790502422', 'karolina_k_100', 0.0, 'PLN', 'paid', '{}'::jsonb
WHERE NOT EXISTS (SELECT 1 FROM orders WHERE event_order_id = '24311000000803010');

-- 2.2 Order: 24311000000798009 (j.kusy@szpitalzelazna.pl) - FOC 100%
INSERT INTO orders (event_order_id, event_id, purchaser_email, purchaser_first_name, purchaser_last_name, 
                    purchaser_phone, purchaser_nip, promo_code, total, currency, status, raw)
SELECT '24311000000798009', '24311000000687006', 'j.kusy@szpitalzelazna.pl', 'Joanna', 'Kusy',
       '+48604970542', '5270104746', 'paulina_100', 0.0, 'PLN', 'paid', '{}'::jsonb
WHERE NOT EXISTS (SELECT 1 FROM orders WHERE event_order_id = '24311000000798009');

-- 2.3 Order: 24311000000795030 (kamila.rogozinska@szpitalpoludniowy.pl) - FOC 100%
INSERT INTO orders (event_order_id, event_id, purchaser_email, purchaser_first_name, purchaser_last_name, 
                    purchaser_phone, purchaser_nip, promo_code, total, currency, status, raw)
SELECT '24311000000795030', '24311000000687006', 'kamila.rogozinska@szpitalpoludniowy.pl', 'Kamila', 'Rogozińska',
       '+48505312363', '5252491419', 'paulina_100', 0.0, 'PLN', 'paid', '{}'::jsonb
WHERE NOT EXISTS (SELECT 1 FROM orders WHERE event_order_id = '24311000000795030');

-- 2.4 Order: 24311000000795009 (karolina.kostrzewska.manowiecka@medispace.pl) - FOC 100%
INSERT INTO orders (event_order_id, event_id, purchaser_email, purchaser_first_name, purchaser_last_name, 
                    purchaser_phone, purchaser_nip, promo_code, total, currency, status, raw)
SELECT '24311000000795009', '24311000000687006', 'karolina.kostrzewska.manowiecka@medispace.pl', 'Karolina', 'Kostrzewa - Manowiecka',
       '+48509680945', '7010485149', 'paulina_100', 0.0, 'PLN', 'paid', '{}'::jsonb
WHERE NOT EXISTS (SELECT 1 FROM orders WHERE event_order_id = '24311000000795009');

-- Anulowane zamówienia - POMIJAMY (na życzenie użytkownika)
-- 24311000000734194 (Kasia T), 24311000000726068 (Daniel Nowy), 
-- 24311000000726008 (Adam Pragacz), 24311000000703117 (Daniel Nowocin)


-- ============================================================================
-- CZĘŚĆ 3: DODAJ BRAKUJĄCYCH UCZESTNIKÓW
-- ============================================================================

-- 3.1 Marta Rysiawa - już kompletna w systemie, pomijamy

-- 3.2 Anna Tkacz
INSERT INTO participants (event_order_id, ticket_id, ticket_class_id, email, first_name, last_name, status, data)
SELECT '24311000000803010', '243110000008030101', '24311000000692096', 
       'anna.tkacz@mimedica.pl', 'Anna', 'Tkacz', 'emailed',
       '{"company_name": "Mimedica", "ticket_name": "Bilet Connect", "promo_code": "karolina_k_100"}'::jsonb
WHERE NOT EXISTS (SELECT 1 FROM participants WHERE ticket_id = '243110000008030101');

-- 3.3 Joanna Kusy
INSERT INTO participants (event_order_id, ticket_id, ticket_class_id, email, first_name, last_name, status, data)
SELECT '24311000000798009', '243110000007980091', '24311000000692096', 
       'j.kusy@szpitalzelazna.pl', 'Joanna', 'Kusy', 'emailed',
       '{"company_name": "CM Żelazna", "ticket_name": "Bilet Connect", "promo_code": "paulina_100"}'::jsonb
WHERE NOT EXISTS (SELECT 1 FROM participants WHERE ticket_id = '243110000007980091');

-- 3.4 Kamila Rogozińska
INSERT INTO participants (event_order_id, ticket_id, ticket_class_id, email, first_name, last_name, status, data)
SELECT '24311000000795030', '243110000007950301', '24311000000692096', 
       'kamila.rogozinska@szpitalpoludniowy.pl', 'Kamila', 'Rogozińska', 'emailed',
       '{"company_name": "Szpital Południowy", "ticket_name": "Bilet Connect", "promo_code": "paulina_100"}'::jsonb
WHERE NOT EXISTS (SELECT 1 FROM participants WHERE ticket_id = '243110000007950301');

-- 3.5 Karolina Kostrzewa - Manowiecka
INSERT INTO participants (event_order_id, ticket_id, ticket_class_id, email, first_name, last_name, status, data)
SELECT '24311000000795009', '243110000007950091', '24311000000692096', 
       'karolina.kostrzewska.manowiecka@medispace.pl', 'Karolina', 'Kostrzewa - Manowiecka', 'emailed',
       '{"company_name": "Medispace", "ticket_name": "Bilet Connect", "promo_code": "paulina_100"}'::jsonb
WHERE NOT EXISTS (SELECT 1 FROM participants WHERE ticket_id = '243110000007950091');

-- Anulowani uczestnicy - POMIJAMY (na życzenie użytkownika)
-- Kasia T, Daniel Nowy, Adam Pragacz, Daniel Nowocin


-- ============================================================================
-- CZĘŚĆ 4: DODAJ WPISY MAIL_LOG (blokada auto-wysyłki)
-- ============================================================================

-- Dla nowych zamówień FOC (paid) - dodaj mail_log jako wysłane
INSERT INTO mail_log (event_order_id, direction, template_key, to_email, subject, status, data)
SELECT o.event_order_id, 'purchaser', 'registration_confirmation', o.purchaser_email, 
       '[IMPORT] Potwierdzenie rejestracji', 'sent', 
       '{"import_note": "Zaimportowane z Zoho - mail już wysłany"}'::jsonb
FROM orders o
WHERE o.event_id = '24311000000687006'
  AND o.status = 'paid'
  AND NOT EXISTS (
    SELECT 1 FROM mail_log ml 
    WHERE ml.event_order_id = o.event_order_id 
      AND ml.template_key = 'registration_confirmation'
  );

-- Dla uczestników FOC - dodaj participant_ticket jako wysłane
INSERT INTO mail_log (event_order_id, direction, template_key, to_email, subject, status, data)
SELECT p.event_order_id, 'participant', 'participant_ticket', p.email, 
       '[IMPORT] Bilet uczestnika', 'sent', 
       '{"import_note": "Zaimportowane z Zoho - bilet już wysłany", "ticket_id": "' || p.ticket_id || '"}'::jsonb
FROM participants p
JOIN orders o ON o.event_order_id = p.event_order_id
WHERE o.event_id = '24311000000687006'
  AND p.status = 'emailed'
  AND NOT EXISTS (
    SELECT 1 FROM mail_log ml 
    WHERE ml.event_order_id = p.event_order_id 
      AND ml.template_key = 'participant_ticket'
      AND ml.to_email = p.email
  );


-- ============================================================================
-- CZĘŚĆ 5: SPRAWDŹ WYNIKI
-- ============================================================================

SELECT '=== ORDERS dla eventu ===' as info;
SELECT event_order_id, purchaser_email, purchaser_first_name, purchaser_last_name, 
       promo_code, total, status
FROM orders 
WHERE event_id = '24311000000687006'
ORDER BY created_at DESC;

SELECT '=== PARTICIPANTS dla eventu ===' as info;
SELECT p.id, p.event_order_id, p.ticket_id, p.email, p.first_name, p.last_name, 
       p.status, p.data->>'company_name' as company, p.data->>'promo_code' as promo
FROM participants p
JOIN orders o ON o.event_order_id = p.event_order_id
WHERE o.event_id = '24311000000687006'
ORDER BY p.created_at DESC;

SELECT '=== PODSUMOWANIE ===' as info;
SELECT 
    (SELECT COUNT(*) FROM orders WHERE event_id = '24311000000687006') as orders_total,
    (SELECT COUNT(*) FROM orders WHERE event_id = '24311000000687006' AND status = 'paid') as orders_paid,
    (SELECT COUNT(*) FROM orders WHERE event_id = '24311000000687006' AND status = 'cancelled') as orders_cancelled,
    (SELECT COUNT(*) FROM orders WHERE event_id = '24311000000687006' AND status = 'pending_payment') as orders_pending,
    (SELECT COUNT(*) FROM participants p JOIN orders o ON o.event_order_id = p.event_order_id WHERE o.event_id = '24311000000687006') as participants_total,
    (SELECT COUNT(*) FROM participants p JOIN orders o ON o.event_order_id = p.event_order_id WHERE o.event_id = '24311000000687006' AND p.status = 'emailed') as participants_emailed,
    (SELECT COUNT(*) FROM participants p JOIN orders o ON o.event_order_id = p.event_order_id WHERE o.event_id = '24311000000687006' AND p.status = 'cancelled') as participants_cancelled;
