-- ============================================
-- CZĘŚĆ 1: UZUPEŁNIJ TICKET_ID i TELEFONY
-- ============================================

-- Marta Szafarczyk-Różycka
UPDATE participants SET 
  ticket_id = '243110000008240971', 
  ticket_class_id = '24311000000692096',
  phone = '+48693520927'
WHERE event_order_id = '24311000000824097' AND email = 'manager@meaclinic.pl';

-- Krzysztof Bączek  
UPDATE participants SET 
  ticket_id = '243110000008290181', 
  ticket_class_id = '24311000000692096',
  phone = '+48692914102'
WHERE event_order_id = '24311000000829018' AND email = 'krzysztof.baczek@poczta.fm';

-- Anna Lenart
UPDATE participants SET 
  ticket_id = '243110000008240741', 
  ticket_class_id = '24311000000692096',
  phone = '+48501025620'
WHERE event_order_id = '24311000000824074' AND email = 'biuro@nzozlomianki.pl';

-- Romana Hila
UPDATE participants SET 
  ticket_id = '243110000007980371', 
  ticket_class_id = '24311000000692095',
  phone = '+48880349927'
WHERE event_order_id = '24311000000798037' AND email = 'r.hila@szpitalzelazna.pl';

-- Marta Rysiawa
UPDATE participants SET 
  ticket_id = '243110000007980372', 
  ticket_class_id = '24311000000692095',
  phone = '+48880349927'
WHERE event_order_id = '24311000000798037' AND email = 'm.rysiawa@szpitalzelazna.pl';

-- Mariusz Czepczyński
UPDATE participants SET 
  ticket_id = '243110000008030751', 
  ticket_class_id = '24311000000692096',
  phone = '+48608488269'
WHERE event_order_id = '24311000000803075' AND email = 'm.czepczynski@nzozlomianki.pl';

-- Justyna Jurak
UPDATE participants SET 
  ticket_id = '243110000008030541', 
  ticket_class_id = '24311000000692096',
  phone = '+48574594002'
WHERE event_order_id = '24311000000803054' AND email = 'justyna.jurak@spkso.waw.pl';

-- Dorota Siwak
UPDATE participants SET 
  ticket_id = '243110000008030311', 
  ticket_class_id = '24311000000692096',
  phone = '+48694430304'
WHERE event_order_id = '24311000000803031' AND email = 'd.siwak@medicers.eu';

-- Anna Tkacz
UPDATE participants SET 
  ticket_id = '243110000008030101', 
  ticket_class_id = '24311000000692096',
  phone = '+48790502422'
WHERE event_order_id = '24311000000803010' AND email = 'anna.tkacz@mimedica.pl';

-- Joanna Kusy
UPDATE participants SET 
  ticket_id = '243110000007980091', 
  ticket_class_id = '24311000000692096',
  phone = '+48604970542'
WHERE event_order_id = '24311000000798009' AND email = 'j.kusy@szpitalzelazna.pl';

-- Kamila Rogozińska
UPDATE participants SET 
  ticket_id = '243110000007950301', 
  ticket_class_id = '24311000000692096',
  phone = '+48505312363'
WHERE event_order_id = '24311000000795030' AND email = 'kamila.rogozinska@szpitalpoludniowy.pl';

-- Karolina Kostrzewa-Manowiecka
UPDATE participants SET 
  ticket_id = '243110000007950091', 
  ticket_class_id = '24311000000692096',
  phone = '+48509680945'
WHERE event_order_id = '24311000000795009' AND email = 'karolina.kostrzewska.manowiecka@medispace.pl';

-- ============================================
-- CZĘŚĆ 2: DODAJ KOLUMNĘ PROMO_CODE (jeśli nie istnieje)
-- ============================================

ALTER TABLE participants ADD COLUMN IF NOT EXISTS promo_code TEXT;

-- ============================================
-- CZĘŚĆ 3: UZUPEŁNIJ KODY RABATOWE
-- ============================================

-- karolina_k_100 (100% zniżka)
UPDATE participants SET promo_code = 'karolina_k_100'
WHERE event_order_id = '24311000000824097' AND email = 'manager@meaclinic.pl';

UPDATE participants SET promo_code = 'karolina_k_100'
WHERE event_order_id = '24311000000803075' AND email = 'm.czepczynski@nzozlomianki.pl';

UPDATE participants SET promo_code = 'karolina_k_100'
WHERE event_order_id = '24311000000803054' AND email = 'justyna.jurak@spkso.waw.pl';

UPDATE participants SET promo_code = 'karolina_k_100'
WHERE event_order_id = '24311000000803031' AND email = 'd.siwak@medicers.eu';

UPDATE participants SET promo_code = 'karolina_k_100'
WHERE event_order_id = '24311000000803010' AND email = 'anna.tkacz@mimedica.pl';

-- karolina_k_15 (15% zniżka)
UPDATE participants SET promo_code = 'karolina_k_15'
WHERE event_order_id = '24311000000824074' AND email = 'biuro@nzozlomianki.pl';

-- paulina_15 (15% zniżka)
UPDATE participants SET promo_code = 'paulina_15'
WHERE event_order_id = '24311000000798037' AND email = 'r.hila@szpitalzelazna.pl';

UPDATE participants SET promo_code = 'paulina_15'
WHERE event_order_id = '24311000000798037' AND email = 'm.rysiawa@szpitalzelazna.pl';

-- paulina_100 (100% zniżka)
UPDATE participants SET promo_code = 'paulina_100'
WHERE event_order_id = '24311000000798009' AND email = 'j.kusy@szpitalzelazna.pl';

UPDATE participants SET promo_code = 'paulina_100'
WHERE event_order_id = '24311000000795030' AND email = 'kamila.rogozinska@szpitalpoludniowy.pl';

UPDATE participants SET promo_code = 'paulina_100'
WHERE event_order_id = '24311000000795009' AND email = 'karolina.kostrzewska.manowiecka@medispace.pl';

-- Brak kodu rabatowego (pełna cena)
-- Krzysztof Bączek - order 24311000000829018 - bez kodu

-- ============================================
-- CZĘŚĆ 4: SPRAWDŹ WYNIKI
-- ============================================

SELECT 
  email, 
  first_name, 
  last_name, 
  phone, 
  ticket_id,
  promo_code
FROM participants 
WHERE event_order_id IN (
  '24311000000824097',
  '24311000000829018',
  '24311000000824074',
  '24311000000798037',
  '24311000000803075',
  '24311000000803054',
  '24311000000803031',
  '24311000000803010',
  '24311000000798009',
  '24311000000795030',
  '24311000000795009'
)
ORDER BY email;
