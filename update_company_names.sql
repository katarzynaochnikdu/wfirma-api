-- Aktualizacja nazw placówek (company) na podstawie CSV Attendee_update.csv
-- Użycie Unicode escape dla polskich znaków

UPDATE participants SET company = 'Mea Clinic' WHERE ticket_id = '243110000008240971';
UPDATE participants SET company = 'KRAJMED CENTRUM MEDYCZNE' WHERE ticket_id = '243110000008290181';
UPDATE participants SET company = E'NZOZ \u0141omianki' WHERE ticket_id = '243110000008240741';
UPDATE participants SET company = E'Centrum Medyczne \u201e\u017belazna\u201d' WHERE ticket_id = '243110000007980371';
UPDATE participants SET company = E'Centrum Medyczne \u201e\u017belazna\u201d' WHERE ticket_id = '243110000007980372';
UPDATE participants SET company = E'NZOZ \u0141omianki' WHERE ticket_id = '243110000008030751';
UPDATE participants SET company = 'Samodzielny Publiczny Kliniczny Szpital Okulistyczny' WHERE ticket_id = '243110000008030541';
UPDATE participants SET company = 'CM Medicers' WHERE ticket_id = '243110000008030311';
UPDATE participants SET company = 'Mimedica' WHERE ticket_id = '243110000008030101';
UPDATE participants SET company = E'CM \u017belazna' WHERE ticket_id = '243110000007980091';
UPDATE participants SET company = E'Szpital Po\u0142udniowy' WHERE ticket_id = '243110000007950301';
UPDATE participants SET company = 'Medispace' WHERE ticket_id = '243110000007950091';

-- Weryfikacja
SELECT email, first_name, last_name, ticket_id, company
FROM participants
WHERE ticket_id IN (
    '243110000008240971', '243110000008290181', '243110000008240741',
    '243110000007980371', '243110000007980372', '243110000008030751',
    '243110000008030541', '243110000008030311', '243110000008030101',
    '243110000007980091', '243110000007950301', '243110000007950091'
)
ORDER BY email;
