-- Check event_ticket_classes for event
SELECT 'event_ticket_classes:' as table_name;
SELECT * FROM event_ticket_classes WHERE event_id = '24311000000687006';

-- Check participants ticket_class_id
SELECT 'participants ticket_class_id:' as table_name;
SELECT id, ticket_class_id, email FROM participants 
WHERE event_order_id IN (SELECT event_order_id FROM orders WHERE event_id = '24311000000687006');

-- List all ticket_class_ids in event_ticket_classes
SELECT 'all ticket classes:' as table_name;
SELECT event_id, ticket_class_id, ticket_name FROM event_ticket_classes ORDER BY event_id;
