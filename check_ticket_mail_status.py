"""
Skrypt sprawdzający status maili dla ticketu i umożliwiający oznaczenie jako wysłany.
"""
import pg_storage
import sys

def check_and_mark_ticket(order_id: str, mark_as_sent: bool = False):
    """Sprawdza i opcjonalnie oznacza ticket jako posiadający wysłany mail."""
    
    # Sprawdź czy zamówienie istnieje
    order = pg_storage.get_order(order_id)
    if not order:
        print(f'BLAD: Zamowienie {order_id} nie istnieje w bazie')
        return False
    
    print('=== ZAMOWIENIE ===')
    print(f'Order ID: {order.get("event_order_id")}')
    print(f'Status: {order.get("status")}')
    print(f'Email kupujacego: {order.get("purchaser_email")}')
    print(f'Kwota calkowita: {order.get("total_amount")} PLN')
    print(f'Data utworzenia: {order.get("created_at")}')
    
    # Sprawdź czy już jest wpis w mail_log
    mail_exists_payment = pg_storage.mail_log_exists(order_id, 'payment_confirmation', 'purchaser')
    mail_exists_registration = pg_storage.mail_log_exists(order_id, 'registration_confirmation', 'purchaser')
    
    print('\n=== STATUS MAILI ===')
    print(f'Mail "payment_confirmation": {"[V] WYSLANY" if mail_exists_payment else "[X] NIE WYSLANY"}')
    print(f'Mail "registration_confirmation": {"[V] WYSLANY" if mail_exists_registration else "[X] NIE WYSLANY"}')
    
    # Określ jaki typ maila powinien był pójść
    total = float(order.get('total_amount', 0))
    purchaser_email = order.get('purchaser_email', '')
    
    if not purchaser_email:
        print('\nOSTRZEZENIE: Brak emaila kupujacego!')
        return False
    
    if total == 0:
        template_key = 'registration_confirmation'
        subject = f'Potwierdzenie rejestracji - {order.get("event_name", "Wydarzenie")}'
        print(f'\nTyp maila: registration_confirmation (bilet darmowy)')
    else:
        template_key = 'payment_confirmation'
        subject = f'Potwierdzenie platnosci - {order.get("event_name", "Wydarzenie")}'
        print(f'\nTyp maila: payment_confirmation (bilet platny)')
    
    # Sprawdź czy już jest oznaczony
    if pg_storage.mail_log_exists(order_id, template_key, 'purchaser'):
        print(f'\n[INFO] Mail "{template_key}" juz oznaczony jako wyslany!')
        return True
    
    if mark_as_sent:
        print(f'\n=== OZNACZAM MAIL JAKO WYSLANY ===')
        result = pg_storage.save_mail_log(
            event_order_id=order_id,
            direction='purchaser',
            template_key=template_key,
            to_email=purchaser_email,
            subject=subject,
            data={
                'marked_manually': True,
                'reason': 'Email juz wyslany recznie - oznaczenie w bazie',
                'order_status': order.get('status'),
            }
        )
        
        if result and result.get('id'):
            # Zaktualizuj status na 'sent'
            mail_id = result.get('id')
            pg_storage.update_mail_log_status(mail_id, error=None)
            print(f'[SUKCES] Mail oznaczony jako wyslany (mail_log id: {mail_id})')
            print(f'Template: {template_key}')
            print(f'Email: {purchaser_email}')
            return True
        else:
            print('[BLAD] Nie udalo sie zapisac w mail_log')
            return False
    else:
        print(f'\n[INFO] Aby oznaczyc mail jako wyslany, uruchom skrypt z parametrem --mark')
        return False


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Uzycie: python check_ticket_mail_status.py <ticket_id> [--mark]')
        print('Przyklad: python check_ticket_mail_status.py 243110000008240741 --mark')
        sys.exit(1)
    
    ticket_id = sys.argv[1]
    mark = '--mark' in sys.argv
    
    check_and_mark_ticket(ticket_id, mark_as_sent=mark)
