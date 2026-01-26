-- Aktualizacja nazwy placówki na identyfikator (badge_name) w JSONB data
-- Na podstawie CSV Attendee_update.csv

UPDATE participants SET 
  data = jsonb_set(COALESCE(data, '{}'::jsonb), '{badge_name}', '"Mea Clinic"')
WHERE ticket_id = '243110000008240971';

UPDATE participants SET 
  data = jsonb_set(COALESCE(data, '{}'::jsonb), '{badge_name}', '"KRAJMED CENTRUM MEDYCZNE"')
WHERE ticket_id = '243110000008290181';

UPDATE participants SET 
  data = jsonb_set(COALESCE(data, '{}'::jsonb), '{badge_name}', E'"NZOZ \u0141omianki"')
WHERE ticket_id = '243110000008240741';

UPDATE participants SET 
  data = jsonb_set(COALESCE(data, '{}'::jsonb), '{badge_name}', E'"Centrum Medyczne \u201e\u017belazna\u201d"')
WHERE ticket_id = '243110000007980371';

UPDATE participants SET 
  data = jsonb_set(COALESCE(data, '{}'::jsonb), '{badge_name}', E'"Centrum Medyczne \u201e\u017belazna\u201d"')
WHERE ticket_id = '243110000007980372';

UPDATE participants SET 
  data = jsonb_set(COALESCE(data, '{}'::jsonb), '{badge_name}', E'"NZOZ \u0141omianki"')
WHERE ticket_id = '243110000008030751';

UPDATE participants SET 
  data = jsonb_set(COALESCE(data, '{}'::jsonb), '{badge_name}', '"Samodzielny Publiczny Kliniczny Szpital Okulistyczny"')
WHERE ticket_id = '243110000008030541';

UPDATE participants SET 
  data = jsonb_set(COALESCE(data, '{}'::jsonb), '{badge_name}', '"CM Medicers"')
WHERE ticket_id = '243110000008030311';

UPDATE participants SET 
  data = jsonb_set(COALESCE(data, '{}'::jsonb), '{badge_name}', '"Mimedica"')
WHERE ticket_id = '243110000008030101';

UPDATE participants SET 
  data = jsonb_set(COALESCE(data, '{}'::jsonb), '{badge_name}', E'"CM \u017belazna"')
WHERE ticket_id = '243110000007980091';

UPDATE participants SET 
  data = jsonb_set(COALESCE(data, '{}'::jsonb), '{badge_name}', E'"Szpital Po\u0142udniowy"')
WHERE ticket_id = '243110000007950301';

UPDATE participants SET 
  data = jsonb_set(COALESCE(data, '{}'::jsonb), '{badge_name}', '"Medispace"')
WHERE ticket_id = '243110000007950091';

-- Weryfikacja
SELECT email, first_name, last_name, ticket_id, data->>'badge_name' as badge_name
FROM participants
WHERE ticket_id IN (
    '243110000008240971', '243110000008290181', '243110000008240741',
    '243110000007980371', '243110000007980372', '243110000008030751',
    '243110000008030541', '243110000008030311', '243110000008030101',
    '243110000007980091', '243110000007950301', '243110000007950091'
)
ORDER BY email;
