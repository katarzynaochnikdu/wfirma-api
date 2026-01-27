-- Oznaczenie ticketu 243110000008240741 jako posiadającego wysłany mail potwierdzający
-- 
-- UWAGA: Przed uruchomieniem sprawdź:
-- 1. Jaki typ maila powinien być (payment_confirmation vs registration_confirmation)
-- 2. Email kupującego
-- 3. Czy wpis już nie istnieje w mail_log

-- KROK 1: Sprawdź szczegóły zamówienia
SELECT 
    event_order_id,
    status,
    purchaser_email,
    total_amount,
    event_name,
    created_at,
    CASE 
        WHEN total_amount = 0 THEN 'registration_confirmation'
        ELSE 'payment_confirmation'
    END as recommended_template
FROM event_orders
WHERE event_order_id = '243110000008240741';

-- KROK 2: Sprawdź czy mail już jest oznaczony
SELECT 
    id,
    event_order_id,
    direction,
    template_key,
    to_email,
    status,
    created_at
FROM mail_log
WHERE event_order_id = '243110000008240741';

-- KROK 3: Oznacz mail jako wysłany (WYKONAJ TO ZAPYTANIE PO SPRAWDZENIU POWYŻSZYCH)
-- 
-- Dla biletu PŁATNEGO (total_amount > 0):
-- INSERT INTO mail_log (event_order_id, direction, template_key, to_email, subject, status, data)
-- SELECT 
--     '243110000008240741',
--     'purchaser',
--     'payment_confirmation',
--     purchaser_email,
--     'Potwierdzenie platnosci - ' || event_name,
--     'sent',
--     jsonb_build_object(
--         'marked_manually', true,
--         'reason', 'Email juz wyslany - oznaczenie w bazie',
--         'marked_at', NOW()
--     )
-- FROM event_orders
-- WHERE event_order_id = '243110000008240741'
--   AND purchaser_email IS NOT NULL
--   AND NOT EXISTS (
--       SELECT 1 FROM mail_log 
--       WHERE event_order_id = '243110000008240741' 
--         AND template_key = 'payment_confirmation'
--         AND direction = 'purchaser'
--   );
--
-- Dla biletu DARMOWEGO (total_amount = 0):
-- INSERT INTO mail_log (event_order_id, direction, template_key, to_email, subject, status, data)
-- SELECT 
--     '243110000008240741',
--     'purchaser',
--     'registration_confirmation',
--     purchaser_email,
--     'Potwierdzenie rejestracji - ' || event_name,
--     'sent',
--     jsonb_build_object(
--         'marked_manually', true,
--         'reason', 'Email juz wyslany - oznaczenie w bazie',
--         'marked_at', NOW()
--     )
-- FROM event_orders
-- WHERE event_order_id = '243110000008240741'
--   AND purchaser_email IS NOT NULL
--   AND NOT EXISTS (
--       SELECT 1 FROM mail_log 
--       WHERE event_order_id = '243110000008240741' 
--         AND template_key = 'registration_confirmation'
--         AND direction = 'purchaser'
--   );

-- KROK 4: Weryfikacja - sprawdź czy wpis został dodany
SELECT 
    id,
    event_order_id,
    direction,
    template_key,
    to_email,
    status,
    data,
    created_at
FROM mail_log
WHERE event_order_id = '243110000008240741'
ORDER BY created_at DESC;
