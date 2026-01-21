"""
Szablony email dla Render - bazowane na Make.com HTML templates.
Obsługuje 3 warianty: osobiste, NIP poprawny, NIP niepoprawny.
"""
from typing import Dict, Any, Optional, List


def format_currency(value: float) -> str:
    """Formatuje kwotę jako PLN (np. 1 234,56 zł)."""
    return f"{value:,.2f}".replace(",", " ").replace(".", ",") + " zł"


def calculate_vat(gross: float, vat_rate: float = 0.23) -> Dict[str, float]:
    """Oblicza netto i VAT z kwoty brutto."""
    net = gross / (1 + vat_rate)
    vat = gross - net
    return {"gross": gross, "net": net, "vat": vat}


def generate_tickets_table_rows(tickets: List[Dict[str, Any]], color_gradient_1: str = "#2563eb") -> str:
    """
    Generuje wiersze tabeli z biletami w stylu profesjonalnym.
    
    Zawiera:
    - Nagłówek kolumn (Nazwa / Ilość / Cena jedn.)
    - Alternujące tła wierszy (parzyste: szare, nieparzyste: białe)
    - Neutralna kolorystyka Bootstrap-inspired
    """
    if not tickets:
        return ""
    
    # Kolory neutralne (Bootstrap gray scale)
    COLOR_HEADER_BG = "#F1F3F5"      # gray-200 - tło nagłówka kolumn
    COLOR_HEADER_TEXT = "#495057"    # gray-700 - tekst nagłówka
    COLOR_HEADER_BORDER = "#DEE2E6"  # gray-400 - obramowanie nagłówka
    COLOR_ROW_ODD_BG = "#FFFFFF"     # biały - wiersze nieparzyste
    COLOR_ROW_EVEN_BG = "#F8F9FA"    # gray-100 - wiersze parzyste
    COLOR_ROW_TEXT = "#212529"       # dark - tekst wierszy
    COLOR_ROW_BORDER = "#E9ECEF"     # gray-300 - obramowanie wierszy
    
    rows = []
    
    # Nagłówek kolumn
    rows.append(f'''
                      <tr>
                        <td style="font-size: 13px; font-weight: bold; padding: 8px 6px; background-color: {COLOR_HEADER_BG}; color: {COLOR_HEADER_TEXT}; border-bottom: 1px solid {COLOR_HEADER_BORDER};">Nazwa</td>
                        <td style="font-size: 13px; font-weight: bold; padding: 8px 6px; background-color: {COLOR_HEADER_BG}; color: {COLOR_HEADER_TEXT}; border-bottom: 1px solid {COLOR_HEADER_BORDER}; text-align: center; width: 60px;">Ilość</td>
                        <td style="font-size: 13px; font-weight: bold; padding: 8px 6px; background-color: {COLOR_HEADER_BG}; color: {COLOR_HEADER_TEXT}; border-bottom: 1px solid {COLOR_HEADER_BORDER}; text-align: right; width: 100px;">Cena jedn.</td>
                      </tr>''')
    
    # Wiersze biletów z alternującym tłem
    for idx, ticket in enumerate(tickets):
        name = ticket.get("name", "Rezerwacja")
        qty = ticket.get("quantity", 1)
        price = ticket.get("price", 0)
        
        # Alternujące tło: idx=0 (nieparzyste w widoku) = białe, idx=1 (parzyste w widoku) = szare
        bg_color = COLOR_ROW_ODD_BG if idx % 2 == 0 else COLOR_ROW_EVEN_BG
        
        rows.append(f'''
                      <tr>
                        <td style="font-size: 14px; padding: 8px 6px; background-color: {bg_color}; color: {COLOR_ROW_TEXT}; border-bottom: 1px solid {COLOR_ROW_BORDER};">{name}</td>
                        <td style="font-size: 14px; padding: 8px 6px; background-color: {bg_color}; color: {COLOR_ROW_TEXT}; border-bottom: 1px solid {COLOR_ROW_BORDER}; text-align: center;">{qty}</td>
                        <td style="font-size: 14px; padding: 8px 6px; background-color: {bg_color}; color: {COLOR_ROW_TEXT}; border-bottom: 1px solid {COLOR_ROW_BORDER}; text-align: right;">{format_currency(price)}</td>
                      </tr>''')
    
    return "".join(rows)


def get_default_event_config() -> Dict[str, Any]:
    """Domyślna konfiguracja eventu jeśli brak w bazie."""
    return {
        "color_gradient_1": "#2563eb",
        "color_gradient_2": "#1e40af",
        "md_email_kontakt": "konferencje@medidesk.com",
        "url_event": "https://medidesk.com",
        "event_mail_link_top_banner": "https://via.placeholder.com/598x200/2563eb/ffffff?text=Medidesk+Event",
        "event_day_text_1": "",
        "event_time_text": "",
        "event_location_place": "",
        "event_location_address": "",
        "event_location_zip": "",
        "event_location_city": "",
    }


# ---------------------------------------------------------------------------
# SZABLON: Stripe Payment Link - Osoba fizyczna (bez NIP)
# ---------------------------------------------------------------------------

TEMPLATE_STRIPE_PERSONAL = '''<!doctype html>
<html lang="pl">
<head>
  <meta charset="UTF-8" />
  <title>Potwierdzenie rejestracji – {event_name}</title>
  <style type="text/css">
    p, h1, h2, h3, h4, h5, h6, ul {{margin: 0;}}
    @media screen and (max-width: 620px) {{
      .wrapper {{ padding: 8px !important; }}
      .main-table {{ width: 100% !important; max-width: 100% !important; }}
      .inner-table {{ width: 100% !important; }}
      .content-cell {{ padding-left: 16px !important; padding-right: 16px !important; }}
      .two-column td {{ display: block !important; width: 100% !important; border-right: none !important; }}
    }}
  </style>
</head>
<body>
  <div style="display: none; max-height: 0; overflow: hidden;">
    Dokończ rejestrację na {event_name} – opłać {total_gross_formatted}
  </div>

  <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border: 1px solid #E3E3E3; background-color: transparent;" dir="ltr">
    <tr>
      <td class="wrapper" style="padding: 32px">
        <table border="0" width="600" cellpadding="0" cellspacing="0" class="main-table" style="width: 600px; margin: auto; max-width: 600px;">
          <tr>
            <td>
              <table border="0" cellpadding="0" cellspacing="0" class="inner-table" style="font-family: Arial, Helvetica, sans-serif; padding:0; color: #000; width: 600px; line-height: 22px; background-color: #fff; font-size: 14px; text-align: left; box-sizing: content-box; border-collapse: collapse; border: 1px solid #DEDEDE;">
                
                <!-- TOP BANNER -->
                <tr>
                  <td valign="top" style="padding: 0;">
                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="min-width:100%!important; background-color: #FFFFFF;">
                      <tr>
                        <td style="padding: 0; line-height: 0;">
                          <a href="{url_event}">
                            <img src="{event_mail_link_top_banner}" alt="{event_name}" width="598" style="width: 100%; max-width: 100%; display: block;">
                          </a>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

                <!-- TREŚĆ GŁÓWNA -->
                <tr>
                  <td valign="top" style="padding: 12px 24px 24px 24px; background-color: #FFFFFF;">
                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="min-width:100%!important;">
                      <tr>
                        <td style="padding: 0;">
                          <h2 style="font-size: 22px; margin: 0;">Cześć <strong>{purchaser_first_name}</strong></h2>
                        </td>
                      </tr>
                      <tr><td style="height: 24px;"></td></tr>
                      <tr>
                        <td style="padding: 0;">
                          <p>Dziękujemy za rejestrację na <strong>{event_name}</strong>. Aby dokończyć rejestrację i zarezerwować miejsce, wymagane jest dokonanie płatności.</p>
                        </td>
                      </tr>
                      <tr><td style="height: 24px;"></td></tr>
                      
                      <!-- DATA -->
                      {event_datetime_section}
                      
                      <!-- LOKALIZACJA -->
                      {event_location_section}
                      
                      <tr><td style="height: 24px;"></td></tr>
                      
                      <!-- PRZYCISK PŁATNOŚCI -->
                      <tr>
                        <td style="padding: 0;">
                          <table border="0" cellpadding="0" cellspacing="0">
                            <tr>
                              <td style="display: inline-block; border-radius: 8px; background-color: {color_gradient_1};">
                                <a href="{stripe_payment_url}" target="_blank" rel="noopener noreferrer" style="display: block; padding: 12px 16px; color: #ffffff; text-decoration: none; font-size: 16px; font-weight: bold; text-align: center;">Opłać rezerwację</a>
                              </td>
                            </tr>
                          </table>
                        </td>
                      </tr>
                      
                      <tr><td style="height: 24px;"></td></tr>
                    </table>
                  </td>
                </tr>

                <!-- SZCZEGÓŁY ZAMÓWIENIA -->
                <tr>
                  <td style="padding: 0 24px 8px 24px;">
                    <table cellpadding="0" cellspacing="0" style="min-width:100%!important; border-collapse: collapse; width: 100%; border: 1px solid #DEE2E6;">
                      <tr>
                        <td colspan="3" style="font-size: 16px; font-weight: bold; line-height: 24px; padding: 10px 6px; color: {color_gradient_1};">Szczegóły zamówienia</td>
                      </tr>
                      {tickets_rows}
                      <tr>
                        <td colspan="2" style="font-size: 14px; padding: 8px 6px; background-color: #F1F3F5; color: #495057; border-top: 2px solid {color_gradient_2};">Kwota netto</td>
                        <td style="font-size: 14px; padding: 8px 6px; background-color: #F1F3F5; color: #495057; border-top: 2px solid {color_gradient_2}; text-align: right;">{total_net_formatted}</td>
                      </tr>
                      <tr>
                        <td colspan="2" style="font-size: 14px; padding: 8px 6px; background-color: #F1F3F5; color: #495057;">VAT (23%)</td>
                        <td style="font-size: 14px; padding: 8px 6px; background-color: #F1F3F5; color: #495057; text-align: right;">{total_vat_formatted}</td>
                      </tr>
                      <tr>
                        <td colspan="2" style="font-weight: bold; font-size: 16px; padding: 10px 6px; background-color: #F1F3F5; color: #333333; border-top: 2px solid {color_gradient_1};">Razem do zapłaty</td>
                        <td style="font-weight: bold; font-size: 16px; padding: 10px 6px; background-color: #F1F3F5; color: #333333; border-top: 2px solid {color_gradient_1}; text-align: right;">{total_gross_formatted}</td>
                      </tr>
                    </table>
                  </td>
                </tr>

                <!-- DANE ROZLICZENIOWE -->
                <tr>
                  <td style="padding: 0 24px 16px 24px;">
                    <table cellpadding="0" cellspacing="0" style="min-width:100%!important; border-collapse: collapse; width: 100%; border: 1px solid #DEE2E6;">
                      <tr>
                        <td colspan="2" style="font-size: 16px; font-weight: bold; line-height: 24px; padding: 10px 6px; color: {color_gradient_1};">Dane rozliczeniowe</td>
                      </tr>
                      <tr class="two-column">
                        <td style="font-size: 14px; padding: 8px 6px; vertical-align: top; width: 100%;">
                          <p style="margin-bottom: 2px; font-weight: bold;">{purchaser_full_name}</p>
                          <p style="margin-bottom: 2px;">{purchaser_email}</p>
                          <p>{purchaser_phone}</p>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

                <!-- INFO: Faktura na osobę fizyczną -->
                <tr>
                  <td style="padding: 0 24px 16px 24px;">
                    <table cellpadding="0" cellspacing="0" style="min-width:100%!important; border-collapse: collapse; width: 100%; border: 1px solid #2196F3;">
                      <tr>
                        <td style="font-size: 13px; padding: 8px 6px; background-color: #E3F2FD;">
                          <p style="margin: 0; color: #1565C0;">Faktura zostanie wystawiona na osobę fizyczną zgodnie z podanymi danymi rozliczeniowymi.</p>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

                <!-- FOOTER -->
                <tr>
                  <td valign="top">
                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="min-width:100%!important; background-color: #F8F9FA;">
                      <tr>
                        <td style="padding: 16px 24px;">
                          <p style="text-align: center; color: #666666; font-size: 13px; margin: 0;">Masz pytania? Skontaktuj się z nami: <a href="mailto:{md_email_kontakt}" style="color: {color_gradient_1}; text-decoration: underline;">{md_email_kontakt}</a></p>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

              </table>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>'''


# ---------------------------------------------------------------------------
# SZABLON: Stripe Payment Link - NIP poprawny (dane z GUS)
# ---------------------------------------------------------------------------

TEMPLATE_STRIPE_NIP_VALID = '''<!doctype html>
<html lang="pl">
<head>
  <meta charset="UTF-8" />
  <title>Potwierdzenie rejestracji – {event_name}</title>
  <style type="text/css">
    p, h1, h2, h3, h4, h5, h6, ul {{margin: 0;}}
    @media screen and (max-width: 620px) {{
      .wrapper {{ padding: 8px !important; }}
      .main-table {{ width: 100% !important; max-width: 100% !important; }}
      .inner-table {{ width: 100% !important; }}
      .two-column td {{ display: block !important; width: 100% !important; }}
    }}
  </style>
</head>
<body>
  <div style="display: none; max-height: 0; overflow: hidden;">
    Dokończ rejestrację na {event_name} – opłać {total_gross_formatted}
  </div>

  <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border: 1px solid #E3E3E3; background-color: transparent;" dir="ltr">
    <tr>
      <td class="wrapper" style="padding: 32px">
        <table border="0" width="600" cellpadding="0" cellspacing="0" class="main-table" style="width: 600px; margin: auto; max-width: 600px;">
          <tr>
            <td>
              <table border="0" cellpadding="0" cellspacing="0" class="inner-table" style="font-family: Arial, Helvetica, sans-serif; padding:0; color: #000; width: 600px; line-height: 22px; background-color: #fff; font-size: 14px; text-align: left; border-collapse: collapse; border: 1px solid #DEDEDE;">
                
                <!-- TOP BANNER -->
                <tr>
                  <td valign="top" style="padding: 0;">
                    <a href="{url_event}">
                      <img src="{event_mail_link_top_banner}" alt="{event_name}" width="598" style="width: 100%; max-width: 100%; display: block;">
                    </a>
                  </td>
                </tr>

                <!-- TREŚĆ GŁÓWNA -->
                <tr>
                  <td valign="top" style="padding: 12px 24px 24px 24px; background-color: #FFFFFF;">
                    <table border="0" cellpadding="0" cellspacing="0" width="100%">
                      <tr>
                        <td><h2 style="font-size: 22px; margin: 0;">Cześć <strong>{purchaser_first_name}</strong></h2></td>
                      </tr>
                      <tr><td style="height: 24px;"></td></tr>
                      <tr>
                        <td><p>Dziękujemy za rejestrację na <strong>{event_name}</strong>. Aby dokończyć rejestrację i zarezerwować miejsce, wymagane jest dokonanie płatności.</p></td>
                      </tr>
                      <tr><td style="height: 24px;"></td></tr>
                      {event_datetime_section}
                      {event_location_section}
                      <tr><td style="height: 24px;"></td></tr>
                      
                      <!-- PRZYCISK PŁATNOŚCI -->
                      <tr>
                        <td>
                          <table border="0" cellpadding="0" cellspacing="0">
                            <tr>
                              <td style="display: inline-block; border-radius: 8px; background-color: {color_gradient_1};">
                                <a href="{stripe_payment_url}" target="_blank" style="display: block; padding: 12px 16px; color: #ffffff; text-decoration: none; font-size: 16px; font-weight: bold;">Opłać rezerwację</a>
                              </td>
                            </tr>
                          </table>
                        </td>
                      </tr>
                      <tr><td style="height: 24px;"></td></tr>
                    </table>
                  </td>
                </tr>

                <!-- SZCZEGÓŁY ZAMÓWIENIA -->
                <tr>
                  <td style="padding: 0 24px 8px 24px;">
                    <table cellpadding="0" cellspacing="0" style="border-collapse: collapse; width: 100%; border: 1px solid #DEE2E6;">
                      <tr>
                        <td colspan="3" style="font-size: 16px; font-weight: bold; padding: 10px 6px; color: {color_gradient_1};">Szczegóły zamówienia</td>
                      </tr>
                      {tickets_rows}
                      <tr>
                        <td colspan="2" style="font-size: 14px; padding: 8px 6px; background-color: #F1F3F5; color: #495057; border-top: 2px solid {color_gradient_2};">Kwota netto</td>
                        <td style="font-size: 14px; padding: 8px 6px; background-color: #F1F3F5; color: #495057; border-top: 2px solid {color_gradient_2}; text-align: right;">{total_net_formatted}</td>
                      </tr>
                      <tr>
                        <td colspan="2" style="font-size: 14px; padding: 8px 6px; background-color: #F1F3F5; color: #495057;">VAT (23%)</td>
                        <td style="font-size: 14px; padding: 8px 6px; background-color: #F1F3F5; color: #495057; text-align: right;">{total_vat_formatted}</td>
                      </tr>
                      <tr>
                        <td colspan="2" style="font-weight: bold; font-size: 16px; padding: 10px 6px; background-color: #F1F3F5; color: #333333; border-top: 2px solid {color_gradient_1};">Razem do zapłaty</td>
                        <td style="font-weight: bold; font-size: 16px; padding: 10px 6px; background-color: #F1F3F5; color: #333333; border-top: 2px solid {color_gradient_1}; text-align: right;">{total_gross_formatted}</td>
                      </tr>
                    </table>
                  </td>
                </tr>

                <!-- DANE ROZLICZENIOWE -->
                <tr>
                  <td style="padding: 0 24px 16px 24px;">
                    <table cellpadding="0" cellspacing="0" style="border-collapse: collapse; width: 100%; border: 1px solid #DEE2E6;">
                      <tr>
                        <td colspan="2" style="font-size: 16px; font-weight: bold; padding: 10px 6px; color: {color_gradient_1};">Dane rozliczeniowe</td>
                      </tr>
                      <tr class="two-column">
                        <td style="font-size: 14px; padding: 8px 6px; vertical-align: top; width: 50%;">
                          <p style="margin-bottom: 2px; font-weight: bold;">{purchaser_full_name}</p>
                          <p style="margin-bottom: 2px;">{purchaser_email}</p>
                          <p>{purchaser_phone}</p>
                        </td>
                        <td style="font-size: 14px; padding: 8px 6px; vertical-align: top; width: 50%;">
                          <p style="margin-bottom: 2px; font-weight: bold;">{gus_company_name}</p>
                          <p style="margin-bottom: 2px;">{gus_address}</p>
                          <p>NIP: {purchaser_nip}</p>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

                <!-- WERYFIKACJA NIP - POPRAWNY -->
                <tr>
                  <td style="padding: 0 24px 16px 24px;">
                    <table cellpadding="0" cellspacing="0" style="border-collapse: collapse; width: 100%; border: 1px solid #4CAF50;">
                      <tr>
                        <td colspan="2" style="font-size: 14px; font-weight: bold; padding: 8px 6px; background-color: #E8F5E9; color: #2E7D32;">
                          Weryfikacja NIP
                        </td>
                      </tr>
                      <tr>
                        <td colspan="2" style="font-size: 13px; padding: 8px 6px; background-color: #F1F8E9;">
                          <p style="margin: 0;"><strong>NIP:</strong> {purchaser_nip} — <span style="color: #2E7D32; font-weight: bold;">POPRAWNY</span></p>
                        </td>
                      </tr>
                      <tr>
                        <td colspan="2" style="font-size: 12px; padding: 8px 6px; color: #666; border-top: 1px dashed #C8E6C9;">
                          <p style="margin: 0 0 2px 0; font-weight: bold; color: #333;">Dane z rejestru GUS:</p>
                          <p style="margin: 0 0 2px 0;">{gus_company_name}</p>
                          <p style="margin: 0 0 2px 0;">{gus_address}</p>
                          <p style="margin: 0;">REGON: {gus_regon}</p>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

                <!-- FOOTER -->
                <tr>
                  <td valign="top">
                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #F8F9FA;">
                      <tr>
                        <td style="padding: 16px 24px;">
                          <p style="text-align: center; color: #666666; font-size: 13px; margin: 0;">Masz pytania? Skontaktuj się z nami: <a href="mailto:{md_email_kontakt}" style="color: {color_gradient_1}; text-decoration: underline;">{md_email_kontakt}</a></p>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

              </table>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>'''


# ---------------------------------------------------------------------------
# SZABLON: Stripe Payment Link - NIP niepoprawny (ostrzeżenie)
# ---------------------------------------------------------------------------

TEMPLATE_STRIPE_NIP_INVALID = '''<!doctype html>
<html lang="pl">
<head>
  <meta charset="UTF-8" />
  <title>Potwierdzenie rejestracji – {event_name}</title>
  <style type="text/css">
    p, h1, h2, h3, h4, h5, h6, ul {{margin: 0;}}
    @media screen and (max-width: 620px) {{
      .wrapper {{ padding: 8px !important; }}
      .main-table {{ width: 100% !important; max-width: 100% !important; }}
      .inner-table {{ width: 100% !important; }}
      .two-column td {{ display: block !important; width: 100% !important; }}
    }}
  </style>
</head>
<body>
  <div style="display: none; max-height: 0; overflow: hidden;">
    Dokończ rejestrację na {event_name} – opłać {total_gross_formatted}
  </div>

  <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border: 1px solid #E3E3E3; background-color: transparent;" dir="ltr">
    <tr>
      <td class="wrapper" style="padding: 32px">
        <table border="0" width="600" cellpadding="0" cellspacing="0" class="main-table" style="width: 600px; margin: auto; max-width: 600px;">
          <tr>
            <td>
              <table border="0" cellpadding="0" cellspacing="0" class="inner-table" style="font-family: Arial, Helvetica, sans-serif; padding:0; color: #000; width: 600px; line-height: 22px; background-color: #fff; font-size: 14px; text-align: left; border-collapse: collapse; border: 1px solid #DEDEDE;">
                
                <!-- TOP BANNER -->
                <tr>
                  <td valign="top" style="padding: 0;">
                    <a href="{url_event}">
                      <img src="{event_mail_link_top_banner}" alt="{event_name}" width="598" style="width: 100%; max-width: 100%; display: block;">
                    </a>
                  </td>
                </tr>

                <!-- TREŚĆ GŁÓWNA -->
                <tr>
                  <td valign="top" style="padding: 12px 24px 24px 24px; background-color: #FFFFFF;">
                    <table border="0" cellpadding="0" cellspacing="0" width="100%">
                      <tr>
                        <td><h2 style="font-size: 22px; margin: 0;">Cześć <strong>{purchaser_first_name}</strong></h2></td>
                      </tr>
                      <tr><td style="height: 24px;"></td></tr>
                      <tr>
                        <td><p>Dziękujemy za rejestrację na <strong>{event_name}</strong>. Aby dokończyć rejestrację i zarezerwować miejsce, wymagane jest dokonanie płatności.</p></td>
                      </tr>
                      <tr><td style="height: 24px;"></td></tr>
                      {event_datetime_section}
                      {event_location_section}
                      <tr><td style="height: 24px;"></td></tr>
                      
                      <!-- PRZYCISK PŁATNOŚCI -->
                      <tr>
                        <td>
                          <table border="0" cellpadding="0" cellspacing="0">
                            <tr>
                              <td style="display: inline-block; border-radius: 8px; background-color: {color_gradient_1};">
                                <a href="{stripe_payment_url}" target="_blank" style="display: block; padding: 12px 16px; color: #ffffff; text-decoration: none; font-size: 16px; font-weight: bold;">Opłać rezerwację</a>
                              </td>
                            </tr>
                          </table>
                        </td>
                      </tr>
                      <tr><td style="height: 24px;"></td></tr>
                    </table>
                  </td>
                </tr>

                <!-- SZCZEGÓŁY ZAMÓWIENIA -->
                <tr>
                  <td style="padding: 0 24px 8px 24px;">
                    <table cellpadding="0" cellspacing="0" style="border-collapse: collapse; width: 100%; border: 1px solid #DEE2E6;">
                      <tr>
                        <td colspan="3" style="font-size: 16px; font-weight: bold; padding: 10px 6px; color: {color_gradient_1};">Szczegóły zamówienia</td>
                      </tr>
                      {tickets_rows}
                      <tr>
                        <td colspan="2" style="font-size: 14px; padding: 8px 6px; background-color: #F1F3F5; color: #495057; border-top: 2px solid {color_gradient_2};">Kwota netto</td>
                        <td style="font-size: 14px; padding: 8px 6px; background-color: #F1F3F5; color: #495057; border-top: 2px solid {color_gradient_2}; text-align: right;">{total_net_formatted}</td>
                      </tr>
                      <tr>
                        <td colspan="2" style="font-size: 14px; padding: 8px 6px; background-color: #F1F3F5; color: #495057;">VAT (23%)</td>
                        <td style="font-size: 14px; padding: 8px 6px; background-color: #F1F3F5; color: #495057; text-align: right;">{total_vat_formatted}</td>
                      </tr>
                      <tr>
                        <td colspan="2" style="font-weight: bold; font-size: 16px; padding: 10px 6px; background-color: #F1F3F5; color: #333333; border-top: 2px solid {color_gradient_1};">Razem do zapłaty</td>
                        <td style="font-weight: bold; font-size: 16px; padding: 10px 6px; background-color: #F1F3F5; color: #333333; border-top: 2px solid {color_gradient_1}; text-align: right;">{total_gross_formatted}</td>
                      </tr>
                    </table>
                  </td>
                </tr>

                <!-- DANE ROZLICZENIOWE -->
                <tr>
                  <td style="padding: 0 24px 16px 24px;">
                    <table cellpadding="0" cellspacing="0" style="border-collapse: collapse; width: 100%; border: 1px solid #DEE2E6;">
                      <tr>
                        <td colspan="2" style="font-size: 16px; font-weight: bold; padding: 10px 6px; color: {color_gradient_1};">Dane rozliczeniowe</td>
                      </tr>
                      <tr class="two-column">
                        <td style="font-size: 14px; padding: 8px 6px; vertical-align: top; width: 50%;">
                          <p style="margin-bottom: 2px; font-weight: bold;">{purchaser_full_name}</p>
                          <p style="margin-bottom: 2px;">{purchaser_email}</p>
                          <p>{purchaser_phone}</p>
                        </td>
                        <td style="font-size: 14px; padding: 8px 6px; vertical-align: top; width: 50%;">
                          <p>NIP: {purchaser_nip}</p>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

                <!-- WERYFIKACJA NIP - NIEPOPRAWNY -->
                <tr>
                  <td style="padding: 0 24px 16px 24px;">
                    <table cellpadding="0" cellspacing="0" style="border-collapse: collapse; width: 100%; border: 1px solid #FF9800;">
                      <tr>
                        <td style="font-size: 14px; font-weight: bold; padding: 8px 6px; background-color: #FFF3E0; color: #E65100;">
                          Weryfikacja NIP
                        </td>
                      </tr>
                      <tr>
                        <td style="font-size: 13px; padding: 8px 6px; background-color: #FFF8E1;">
                          <p style="margin: 0;"><strong>NIP:</strong> {purchaser_nip} — <span style="color: #E65100; font-weight: bold;">NIEPOPRAWNY</span></p>
                          <p style="margin: 4px 0 0 0; font-size: 12px; color: #666;">Podany NIP nie przeszedł walidacji. Prosimy o weryfikację numeru.</p>
                        </td>
                      </tr>
                      <tr>
                        <td style="font-size: 12px; padding: 8px 6px; background-color: #FFF8E1; border-top: 1px dashed #FFE0B2;">
                          <p style="margin: 0 0 8px 0; color: #E65100;"><strong>Jeśli dokonasz płatności z tego linka</strong>, faktura zostanie wystawiona na osobę fizyczną.</p>
                          <p style="margin: 0; color: #333;">Jeśli chcesz otrzymać fakturę na firmę, zarejestruj się ponownie z poprawnym NIP:</p>
                        </td>
                      </tr>
                      <tr>
                        <td style="padding: 12px 6px; background-color: #FFF8E1; text-align: center;">
                          <a href="{url_event}" target="_blank" style="display: inline-block; padding: 10px 20px; background-color: #E65100; color: #ffffff; text-decoration: none; font-size: 14px; font-weight: bold; border-radius: 6px;">Zarejestruj się ponownie</a>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

                <!-- FOOTER -->
                <tr>
                  <td valign="top">
                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #F8F9FA;">
                      <tr>
                        <td style="padding: 16px 24px;">
                          <p style="text-align: center; color: #666666; font-size: 13px; margin: 0;">Masz pytania? Skontaktuj się z nami: <a href="mailto:{md_email_kontakt}" style="color: {color_gradient_1}; text-decoration: underline;">{md_email_kontakt}</a></p>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

              </table>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>'''


# ---------------------------------------------------------------------------
# GENEROWANIE HTML
# ---------------------------------------------------------------------------

def _build_event_datetime_section(event_config: Dict[str, Any]) -> str:
    """Buduje sekcję daty/godziny eventu."""
    day_text = event_config.get("event_day_text_1", "")
    time_text = event_config.get("event_time_text", "")
    if not day_text and not time_text:
        return ""
    datetime_str = f"{day_text}, {time_text}".strip(", ")
    return f'''
                      <tr>
                        <td style="padding: 0;">
                          <table align="left" border="0" cellpadding="0" cellspacing="0" width="100%">
                            <tr>
                              <td style="width: 20px; vertical-align: middle;">
                                <img src="https://static.zohocdn.com/backstage/v1.0/images/date_time-icon-c5bd02a43dbfa5720976303479fa3071.png" alt="Data" width="20" style="width: 20px;">
                              </td>
                              <td style="padding-left: 5px; vertical-align: middle;">
                                <p>{datetime_str}</p>
                              </td>
                            </tr>
                          </table>
                        </td>
                      </tr>'''


def _build_event_location_section(event_config: Dict[str, Any]) -> str:
    """Buduje sekcję lokalizacji eventu."""
    place = event_config.get("event_location_place", "")
    address = event_config.get("event_location_address", "")
    zip_code = event_config.get("event_location_zip", "")
    city = event_config.get("event_location_city", "")
    if not place and not address:
        return ""
    address_line = f"{address}, {zip_code} {city}".strip(", ")
    return f'''
                      <tr>
                        <td style="padding: 0;">
                          <table align="left" border="0" cellpadding="0" cellspacing="0" width="100%">
                            <tr>
                              <td style="width: 20px; vertical-align: top;">
                                <img src="https://static.zohocdn.com/backstage/v1.0/images/mini_location-icon-cabc9c63a7da9a671cee8477f28c09c4.png" alt="Lokalizacja" width="20" style="width: 20px;">
                              </td>
                              <td style="padding-left: 5px; vertical-align: top;">
                                <p style="font-weight: bold;">{place}</p>
                                <p>{address_line}</p>
                              </td>
                            </tr>
                          </table>
                        </td>
                      </tr>'''


def render_stripe_payment_email(
    template_type: str,
    event_name: str,
    purchaser_first_name: str,
    purchaser_last_name: str,
    purchaser_email: str,
    purchaser_phone: str,
    purchaser_nip: Optional[str],
    total_gross: float,
    stripe_payment_url: str,
    event_config: Optional[Dict[str, Any]] = None,
    tickets: Optional[List[Dict[str, Any]]] = None,
    gus_data: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Renderuje email z linkiem do płatności Stripe.
    
    Args:
        template_type: "personal" | "nip_valid" | "nip_invalid"
        event_name: Nazwa eventu
        purchaser_*: Dane kupującego
        total_gross: Kwota brutto
        stripe_payment_url: Link do płatności Stripe
        event_config: Konfiguracja eventu (kolory, banery, itp.)
        tickets: Lista biletów [{name, quantity, price}]
        gus_data: Dane z GUS (dla nip_valid) {name, street, zip, city, regon}
    
    Returns:
        Gotowy HTML email
    """
    # Defaults
    event_config = event_config or get_default_event_config()
    tickets = tickets or []
    gus_data = gus_data or {}

    # Normalizuj bilety do formatu oczekiwanego przez generate_tickets_table_rows:
    # [{name, quantity, price}] gdzie price = cena jedn. brutto
    normalized_tickets: List[Dict[str, Any]] = []
    for t in tickets:
        try:
            name = (
                t.get("name")
                or t.get("ticket_name")
                or t.get("ticketName")
                or "Bilet"
            )
            qty = t.get("quantity", 1)
            try:
                qty_num = int(qty) if qty is not None else 1
            except (ValueError, TypeError):
                qty_num = 1

            price = t.get("price")
            if price is None:
                price = t.get("unit_price_gross")
            if price is None:
                price = t.get("unit_price")
            if price is None:
                # fallback: jeśli mamy total_gross, przelicz na jednostkową
                total_gross = t.get("total_gross")
                if total_gross is not None and qty_num > 0:
                    try:
                        price = float(total_gross) / float(qty_num)
                    except (ValueError, TypeError):
                        price = 0

            try:
                price_num = float(price) if price is not None else 0.0
            except (ValueError, TypeError):
                price_num = 0.0

            normalized_tickets.append({
                "name": str(name),
                "quantity": qty_num,
                "price": price_num,
            })
        except Exception:
            # Nie blokuj renderu emaila przez jeden błędny rekord biletu
            continue
    
    # Oblicz wartości
    vat_calc = calculate_vat(total_gross)
    
    # Przygotuj dane do szablonu
    data = {
        "event_name": event_name,
        "purchaser_first_name": purchaser_first_name or "Uczestnik",
        "purchaser_full_name": f"{purchaser_first_name} {purchaser_last_name}".strip(),
        "purchaser_email": purchaser_email,
        "purchaser_phone": purchaser_phone or "",
        "purchaser_nip": purchaser_nip or "",
        "total_gross_formatted": format_currency(vat_calc["gross"]),
        "total_net_formatted": format_currency(vat_calc["net"]),
        "total_vat_formatted": format_currency(vat_calc["vat"]),
        "stripe_payment_url": stripe_payment_url,
        "tickets_rows": generate_tickets_table_rows(normalized_tickets, event_config.get("color_gradient_1", "#2563eb")),
        "event_datetime_section": _build_event_datetime_section(event_config),
        "event_location_section": _build_event_location_section(event_config),
        # Event config
        "color_gradient_1": event_config.get("color_gradient_1", "#2563eb"),
        "color_gradient_2": event_config.get("color_gradient_2", "#1e40af"),
        "md_email_kontakt": event_config.get("md_email_kontakt", "konferencje@medidesk.com"),
        "url_event": event_config.get("url_event", "https://medidesk.com"),
        "event_mail_link_top_banner": event_config.get("event_mail_link_top_banner", "https://via.placeholder.com/598x200/2563eb/ffffff?text=Event"),
        # GUS data (dla nip_valid)
        "gus_company_name": gus_data.get("name", ""),
        "gus_address": f"{gus_data.get('street', '')}, {gus_data.get('zip', '')} {gus_data.get('city', '')}".strip(", "),
        "gus_regon": gus_data.get("regon", ""),
    }
    
    # Wybierz szablon
    if template_type == "nip_valid":
        template = TEMPLATE_STRIPE_NIP_VALID
    elif template_type == "nip_invalid":
        template = TEMPLATE_STRIPE_NIP_INVALID
    else:
        template = TEMPLATE_STRIPE_PERSONAL
    
    return template.format(**data)


# ---------------------------------------------------------------------------
# SZABLON: FOC (Free of Charge) - Potwierdzenie rezerwacji (100% rabat = opłacone)
# ---------------------------------------------------------------------------

TEMPLATE_FOC_CONFIRMATION = '''<!doctype html>
<html lang="pl">
<head>
  <meta charset="UTF-8" />
  <title>Potwierdzenie rezerwacji – {event_name}</title>
  <style type="text/css">
    p, h1, h2, h3, h4, h5, h6, ul {{margin: 0;}}
    @media screen and (max-width: 620px) {{
      .wrapper {{ padding: 8px !important; }}
      .main-table {{ width: 100% !important; max-width: 100% !important; }}
      .inner-table {{ width: 100% !important; }}
      .content-cell {{ padding-left: 16px !important; padding-right: 16px !important; }}
    }}
  </style>
</head>
<body>
  <div style="display: none; max-height: 0; overflow: hidden;">
    Twoja rezerwacja na {event_name} została potwierdzona!
  </div>

  <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border: 1px solid #E3E3E3; background-color: transparent;" dir="ltr">
    <tr>
      <td class="wrapper" style="padding: 32px">
        <table border="0" width="600" cellpadding="0" cellspacing="0" class="main-table" style="width: 600px; margin: auto; max-width: 600px;">
          <tr>
            <td>
              <table border="0" cellpadding="0" cellspacing="0" class="inner-table" style="font-family: Arial, Helvetica, sans-serif; padding:0; color: #000; width: 600px; line-height: 22px; background-color: #fff; font-size: 14px; text-align: left; box-sizing: content-box; border-collapse: collapse; border: 1px solid #DEDEDE;">
                
                <!-- TOP BANNER -->
                <tr>
                  <td valign="top" style="padding: 0;">
                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="min-width:100%!important; background-color: #FFFFFF;">
                      <tr>
                        <td style="padding: 0; line-height: 0;">
                          <a href="{url_event}">
                            <img src="{event_mail_link_top_banner}" alt="{event_name}" width="598" style="width: 100%; max-width: 100%; display: block;">
                          </a>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

                <!-- TREŚĆ GŁÓWNA -->
                <tr>
                  <td valign="top" style="padding: 12px 24px 24px 24px; background-color: #FFFFFF;">
                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="min-width:100%!important;">
                      <tr>
                        <td style="padding: 0;">
                          <h2 style="font-size: 22px; margin: 0;">Cześć <strong>{purchaser_first_name}</strong></h2>
                        </td>
                      </tr>
                      <tr><td style="height: 24px;"></td></tr>
                      <tr>
                        <td style="padding: 0;">
                          <p>Dziękujemy za rezerwację miejsca na <strong>{event_name}</strong>!</p>
                        </td>
                      </tr>
                      <tr><td style="height: 12px;"></td></tr>
                      <tr>
                        <td style="padding: 0;">
                          <p style="font-size: 16px; color: #2E7D32; font-weight: bold;">✅ Twoja rezerwacja została potwierdzona.</p>
                        </td>
                      </tr>
                      <tr><td style="height: 24px;"></td></tr>
                      
                      <!-- DATA -->
                      {event_datetime_section}
                      
                      <!-- LOKALIZACJA -->
                      {event_location_section}
                      
                      <tr><td style="height: 24px;"></td></tr>
                    </table>
                  </td>
                </tr>

                <!-- SZCZEGÓŁY ZAMÓWIENIA -->
                <tr>
                  <td style="padding: 0 24px 8px 24px;">
                    <table cellpadding="0" cellspacing="0" style="min-width:100%!important; border-collapse: collapse; width: 100%; border: 1px solid #DEE2E6;">
                      <tr>
                        <td colspan="3" style="font-size: 16px; font-weight: bold; line-height: 24px; padding: 10px 6px; color: {color_gradient_1};">Szczegóły rezerwacji</td>
                      </tr>
                      {tickets_rows}
                      <tr>
                        <td colspan="2" style="font-weight: bold; font-size: 16px; padding: 10px 6px; background-color: #E8F5E9; color: #2E7D32;">Status</td>
                        <td style="font-weight: bold; font-size: 16px; padding: 10px 6px; background-color: #E8F5E9; color: #2E7D32; text-align: right;">BEZPŁATNE ✓</td>
                      </tr>
                    </table>
                  </td>
                </tr>

                <!-- DANE UCZESTNIKA -->
                <tr>
                  <td style="padding: 0 24px 16px 24px;">
                    <table cellpadding="0" cellspacing="0" style="min-width:100%!important; border-collapse: collapse; width: 100%; border: 1px solid #DEE2E6;">
                      <tr>
                        <td colspan="2" style="font-size: 16px; font-weight: bold; line-height: 24px; padding: 10px 6px; color: {color_gradient_1};">Dane uczestnika</td>
                      </tr>
                      <tr>
                        <td style="font-size: 14px; padding: 8px 6px; vertical-align: top; width: 100%;">
                          <p style="margin-bottom: 2px; font-weight: bold;">{purchaser_full_name}</p>
                          <p style="margin-bottom: 2px;">{purchaser_email}</p>
                          <p>{purchaser_phone}</p>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

                <!-- FOOTER -->
                <tr>
                  <td valign="top">
                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="min-width:100%!important; background-color: #F8F9FA;">
                      <tr>
                        <td style="padding: 16px 24px;">
                          <p style="text-align: center; color: #666666; font-size: 13px; margin: 0;">Masz pytania? Skontaktuj się z nami: <a href="mailto:{md_email_kontakt}" style="color: {color_gradient_1}; text-decoration: underline;">{md_email_kontakt}</a></p>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

              </table>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>'''


def render_foc_confirmation_email(
    event_name: str,
    purchaser_first_name: str,
    purchaser_last_name: str,
    purchaser_email: str,
    purchaser_phone: str,
    event_config: Optional[Dict[str, Any]] = None,
    tickets: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Renderuje email z potwierdzeniem rezerwacji FOC (Free of Charge = opłacone od razu).
    
    Args:
        event_name: Nazwa eventu
        purchaser_*: Dane kupującego
        event_config: Konfiguracja eventu (kolory, banery, itp.)
        tickets: Lista biletów [{name, quantity}]
    
    Returns:
        Gotowy HTML email
    """
    # Defaults
    event_config = event_config or get_default_event_config()
    tickets = tickets or []

    # Normalizuj bilety - dla FOC cena = 0
    normalized_tickets: List[Dict[str, Any]] = []
    for t in tickets:
        try:
            name = (
                t.get("name")
                or t.get("ticket_name")
                or t.get("ticketName")
                or "Bilet"
            )
            qty = t.get("quantity", 1)
            try:
                qty_num = int(qty) if qty is not None else 1
            except (ValueError, TypeError):
                qty_num = 1

            normalized_tickets.append({
                "name": str(name),
                "quantity": qty_num,
                "price": 0.0,  # FOC = bezpłatne
            })
        except Exception:
            continue
    
    # Przygotuj dane do szablonu
    data = {
        "event_name": event_name,
        "purchaser_first_name": purchaser_first_name or "Uczestnik",
        "purchaser_full_name": f"{purchaser_first_name} {purchaser_last_name}".strip(),
        "purchaser_email": purchaser_email,
        "purchaser_phone": purchaser_phone or "",
        "tickets_rows": generate_tickets_table_rows(normalized_tickets, event_config.get("color_gradient_1", "#2563eb")),
        "event_datetime_section": _build_event_datetime_section(event_config),
        "event_location_section": _build_event_location_section(event_config),
        # Event config
        "color_gradient_1": event_config.get("color_gradient_1", "#2563eb"),
        "color_gradient_2": event_config.get("color_gradient_2", "#1e40af"),
        "md_email_kontakt": event_config.get("md_email_kontakt", "konferencje@medidesk.com"),
        "url_event": event_config.get("url_event", "https://medidesk.com"),
        "event_mail_link_top_banner": event_config.get("event_mail_link_top_banner", "https://via.placeholder.com/598x200/2563eb/ffffff?text=Event"),
    }
    
    return TEMPLATE_FOC_CONFIRMATION.format(**data)


# ---------------------------------------------------------------------------
# SZABLON: PROFORMA - potwierdzenie rejestracji + informacja o pro-formie (mail z Backstage)
# ---------------------------------------------------------------------------

TEMPLATE_PROFORMA_RESERVATION = '''<!doctype html>
<html lang="pl">
<head>
  <meta charset="UTF-8" />
  <title>Potwierdzenie rejestracji – {event_name}</title>
  <style type="text/css">
    p, h1, h2, h3, h4, h5, h6, ul {{margin: 0;}}
    @media screen and (max-width: 620px) {{
      .wrapper {{ padding: 8px !important; }}
      .main-table {{ width: 100% !important; max-width: 100% !important; }}
      .inner-table {{ width: 100% !important; }}
      .content-cell {{ padding-left: 16px !important; padding-right: 16px !important; }}
    }}
  </style>
</head>
<body>
  <div style="display: none; max-height: 0; overflow: hidden;">
    Twoja rejestracja na {event_name} jest potwierdzona. Pro-forma zostanie wysłana mailem.
  </div>

  <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border: 1px solid #E3E3E3; background-color: transparent;" dir="ltr">
    <tr>
      <td class="wrapper" style="padding: 32px">
        <table border="0" width="600" cellpadding="0" cellspacing="0" class="main-table" style="width: 600px; margin: auto; max-width: 600px;">
          <tr>
            <td>
              <table border="0" cellpadding="0" cellspacing="0" class="inner-table" style="font-family: Arial, Helvetica, sans-serif; padding:0; color: #000; width: 600px; line-height: 22px; background-color: #fff; font-size: 14px; text-align: left; box-sizing: content-box; border-collapse: collapse; border: 1px solid #DEDEDE;">

                <!-- TOP BANNER -->
                <tr>
                  <td valign="top" style="padding: 0;">
                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="min-width:100%!important; background-color: #FFFFFF;">
                      <tr>
                        <td style="padding: 0; line-height: 0;">
                          <a href="{url_event}">
                            <img src="{event_mail_link_top_banner}" alt="{event_name}" width="598" style="width: 100%; max-width: 100%; display: block;">
                          </a>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

                <!-- TREŚĆ GŁÓWNA -->
                <tr>
                  <td valign="top" style="padding: 12px 24px 24px 24px; background-color: #FFFFFF;">
                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="min-width:100%!important;">
                      <tr>
                        <td style="padding: 0;">
                          <h2 style="font-size: 22px; margin: 0;">Cześć <strong>{purchaser_first_name}</strong></h2>
                        </td>
                      </tr>
                      <tr><td style="height: 24px;"></td></tr>
                      <tr>
                        <td style="padding: 0;">
                          <p>Potwierdzamy rejestrację na <strong>{event_name}</strong>.</p>
                        </td>
                      </tr>
                      <tr><td style="height: 12px;"></td></tr>
                      <tr>
                        <td style="padding: 0;">
                          <p style="font-size: 16px; color: #1F2937; font-weight: bold;">✅ Twoja rejestracja jest potwierdzona.</p>
                        </td>
                      </tr>
                      <tr><td style="height: 16px;"></td></tr>
                      <tr>
                        <td style="padding: 0;">
                          <p><strong>Pro-forma</strong>{proforma_number_inline} zostanie wysłana na ten adres email z systemu wFirma.</p>
                          <p style="margin-top: 8px; font-size: 14px; color: #6B7280;">Po opłaceniu pro-formy Twoje miejsce zostanie zarezerwowane.</p>
                        </td>
                      </tr>
                      <tr><td style="height: 16px;"></td></tr>

                      <!-- INFO BOX -->
                      <tr>
                        <td style="padding: 0;">
                          <table cellpadding="0" cellspacing="0" style="width: 100%; background-color: #F3F4F6; border: 1px solid #E5E7EB; border-radius: 8px;">
                            <tr>
                              <td style="padding: 12px 16px;">
                                <p style="margin: 0; font-size: 14px; color: #374151;">
                                  Jeśli nie otrzymasz maila z pro-formą w ciągu <strong>24 godzin</strong>, sprawdź folder SPAM i skontaktuj się z nami: <a href="mailto:{md_email_kontakt}" style="color: {color_gradient_1}; text-decoration: underline;">{md_email_kontakt}</a>.
                                </p>
                              </td>
                            </tr>
                          </table>
                        </td>
                      </tr>

                      <tr><td style="height: 24px;"></td></tr>

                      <!-- DATA -->
                      {event_datetime_section}

                      <!-- LOKALIZACJA -->
                      {event_location_section}

                      <tr><td style="height: 24px;"></td></tr>
                    </table>
                  </td>
                </tr>

                <!-- SZCZEGÓŁY ZAMÓWIENIA -->
                <tr>
                  <td style="padding: 0 24px 8px 24px;">
                    <table cellpadding="0" cellspacing="0" style="min-width:100%!important; border-collapse: collapse; width: 100%; border: 1px solid #DEE2E6;">
                      <tr>
                        <td colspan="3" style="font-size: 16px; font-weight: bold; line-height: 24px; padding: 10px 6px; color: {color_gradient_1};">Szczegóły rejestracji</td>
                      </tr>
                      {tickets_rows}
                      <tr>
                        <td colspan="2" style="font-size: 14px; padding: 10px 6px; background-color: #F8F9FA; color: #495057;">Status</td>
                        <td style="font-size: 14px; padding: 10px 6px; background-color: #F8F9FA; text-align: right;">
                          <span style="display: inline-block; padding: 2px 8px; border-radius: 999px; background-color: #FFF3E0; color: #B45309; font-weight: 600;">
                            Oczekuje na płatność
                          </span>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

                <!-- DANE UCZESTNIKA -->
                <tr>
                  <td style="padding: 0 24px 16px 24px;">
                    <table cellpadding="0" cellspacing="0" style="min-width:100%!important; border-collapse: collapse; width: 100%; border: 1px solid #DEE2E6;">
                      <tr>
                        <td colspan="2" style="font-size: 16px; font-weight: bold; line-height: 24px; padding: 10px 6px; color: {color_gradient_1};">Dane kupującego</td>
                      </tr>
                      <tr>
                        <td style="font-size: 14px; padding: 8px 6px; vertical-align: top; width: 100%;">
                          <p style="margin-bottom: 2px; font-weight: bold;">{purchaser_full_name}</p>
                          <p style="margin-bottom: 2px;">{purchaser_email}</p>
                          <p>{purchaser_phone}</p>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

                <!-- FOOTER -->
                <tr>
                  <td valign="top">
                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="min-width:100%!important; background-color: #F8F9FA;">
                      <tr>
                        <td style="padding: 16px 24px;">
                          <p style="text-align: center; color: #666666; font-size: 13px; margin: 0;">Masz pytania? Skontaktuj się z nami: <a href="mailto:{md_email_kontakt}" style="color: {color_gradient_1}; text-decoration: underline;">{md_email_kontakt}</a></p>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

              </table>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>'''


def render_proforma_reservation_email(
    event_name: str,
    purchaser_first_name: str,
    purchaser_last_name: str,
    purchaser_email: str,
    purchaser_phone: str,
    event_config: Optional[Dict[str, Any]] = None,
    tickets: Optional[List[Dict[str, Any]]] = None,
    proforma_number: Optional[str] = None,
) -> str:
    """
    Email BACKSTAGE dla flow PROFORMA: potwierdzenie rejestracji + informacja o pro-formie z wFirma.
    """
    event_config = event_config or get_default_event_config()
    tickets = tickets or []

    normalized_tickets: List[Dict[str, Any]] = []
    for t in tickets:
        try:
            name = (
                t.get("name")
                or t.get("ticket_name")
                or t.get("ticketName")
                or "Bilet"
            )
            qty = t.get("quantity", 1)
            try:
                qty_num = int(qty) if qty is not None else 1
            except (ValueError, TypeError):
                qty_num = 1

            normalized_tickets.append({
                "name": str(name),
                "quantity": qty_num,
            })
        except Exception:
            continue

    proforma_number_inline = f" ({proforma_number})" if proforma_number else ""

    data = {
        "event_name": event_name,
        "purchaser_first_name": purchaser_first_name or "Uczestnik",
        "purchaser_full_name": f"{purchaser_first_name} {purchaser_last_name}".strip(),
        "purchaser_email": purchaser_email,
        "purchaser_phone": purchaser_phone or "",
        "proforma_number_inline": proforma_number_inline,
        "tickets_rows": generate_tickets_table_rows(normalized_tickets, event_config.get("color_gradient_1", "#2563eb")),
        "event_datetime_section": _build_event_datetime_section(event_config),
        "event_location_section": _build_event_location_section(event_config),
        "color_gradient_1": event_config.get("color_gradient_1", "#2563eb"),
        "color_gradient_2": event_config.get("color_gradient_2", "#1e40af"),
        "md_email_kontakt": event_config.get("md_email_kontakt", "konferencje@medidesk.com"),
        "url_event": event_config.get("url_event", "https://medidesk.com"),
        "event_mail_link_top_banner": event_config.get("event_mail_link_top_banner", "https://via.placeholder.com/598x200/2563eb/ffffff?text=Event"),
    }

    return TEMPLATE_PROFORMA_RESERVATION.format(**data)


# ---------------------------------------------------------------------------
# SZABLON: Potwierdzenie płatności (po Stripe checkout)
# ---------------------------------------------------------------------------

TEMPLATE_PAYMENT_CONFIRMATION = '''<!doctype html>
<html lang="pl">
<head>
  <meta charset="UTF-8" />
  <title>Potwierdzenie płatności – {event_name}</title>
  <style type="text/css">
    p, h1, h2, h3, h4, h5, h6, ul {{margin: 0;}}
    @media screen and (max-width: 620px) {{
      .wrapper {{ padding: 8px !important; }}
      .main-table {{ width: 100% !important; max-width: 100% !important; }}
      .inner-table {{ width: 100% !important; }}
      .content-cell {{ padding-left: 16px !important; padding-right: 16px !important; }}
    }}
  </style>
</head>
<body>
  <div style="display: none; max-height: 0; overflow: hidden;">
    Dziękujemy za płatność – {event_name}
  </div>

  <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border: 1px solid #E3E3E3; background-color: transparent;" dir="ltr">
    <tr>
      <td class="wrapper" style="padding: 32px">
        <table border="0" width="600" cellpadding="0" cellspacing="0" class="main-table" style="width: 600px; margin: auto; max-width: 600px;">
          <tr>
            <td>
              <table border="0" cellpadding="0" cellspacing="0" class="inner-table" style="font-family: Arial, Helvetica, sans-serif; padding:0; color: #000; width: 600px; line-height: 22px; background-color: #fff; font-size: 14px; text-align: left; box-sizing: content-box; border-collapse: collapse; border: 1px solid #DEDEDE;">
                
                <!-- TOP BANNER -->
                <tr>
                  <td valign="top" style="padding: 0;">
                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="min-width:100%!important; background-color: #FFFFFF;">
                      <tr>
                        <td style="padding: 0; line-height: 0;">
                          <a href="{url_event}">
                            <img src="{event_mail_link_top_banner}" alt="{event_name}" width="598" style="width: 100%; max-width: 100%; display: block;">
                          </a>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

                <!-- TREŚĆ GŁÓWNA -->
                <tr>
                  <td valign="top" style="padding: 12px 24px 24px 24px; background-color: #FFFFFF;">
                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="min-width:100%!important;">
                      <tr>
                        <td style="padding: 0;">
                          <h2 style="font-size: 22px; margin: 0;">Cześć <strong>{purchaser_first_name}</strong></h2>
                        </td>
                      </tr>
                      <tr><td style="height: 24px;"></td></tr>
                      <tr>
                        <td style="padding: 0;">
                          <p style="font-size: 18px; color: #2E7D32; font-weight: bold;">✅ Dziękujemy za dokonanie płatności!</p>
                        </td>
                      </tr>
                      <tr><td style="height: 12px;"></td></tr>
                      <tr>
                        <td style="padding: 0;">
                          <p>Potwierdzamy otrzymanie płatności za udział w wydarzeniu <strong>{event_name}</strong>.</p>
                        </td>
                      </tr>
                      <tr><td style="height: 24px;"></td></tr>
                      
                      <!-- DATA -->
                      {event_datetime_section}
                      
                      <!-- LOKALIZACJA -->
                      {event_location_section}
                      
                      <tr><td style="height: 24px;"></td></tr>
                    </table>
                  </td>
                </tr>

                <!-- SZCZEGÓŁY ZAMÓWIENIA -->
                <tr>
                  <td style="padding: 0 24px 8px 24px;">
                    <table cellpadding="0" cellspacing="0" style="min-width:100%!important; border-collapse: collapse; width: 100%; border: 1px solid #DEE2E6;">
                      <tr>
                        <td colspan="3" style="font-size: 16px; font-weight: bold; line-height: 24px; padding: 10px 6px; color: {color_gradient_1};">Szczegóły zamówienia</td>
                      </tr>
                      {tickets_rows}
                      <tr>
                        <td colspan="2" style="font-size: 14px; padding: 8px 6px; background-color: #F1F3F5; color: #495057; border-top: 2px solid {color_gradient_2};">Kwota netto</td>
                        <td style="font-size: 14px; padding: 8px 6px; background-color: #F1F3F5; color: #495057; border-top: 2px solid {color_gradient_2}; text-align: right;">{total_net_formatted}</td>
                      </tr>
                      <tr>
                        <td colspan="2" style="font-size: 14px; padding: 8px 6px; background-color: #F1F3F5; color: #495057;">VAT (23%)</td>
                        <td style="font-size: 14px; padding: 8px 6px; background-color: #F1F3F5; color: #495057; text-align: right;">{total_vat_formatted}</td>
                      </tr>
                      <tr>
                        <td colspan="2" style="font-weight: bold; font-size: 16px; padding: 10px 6px; background-color: #E8F5E9; color: #2E7D32; border-top: 2px solid #4CAF50;">Razem zapłacono</td>
                        <td style="font-weight: bold; font-size: 16px; padding: 10px 6px; background-color: #E8F5E9; color: #2E7D32; border-top: 2px solid #4CAF50; text-align: right;">{total_gross_formatted}</td>
                      </tr>
                    </table>
                  </td>
                </tr>

                <!-- DANE ROZLICZENIOWE -->
                <tr>
                  <td style="padding: 0 24px 16px 24px;">
                    <table cellpadding="0" cellspacing="0" style="min-width:100%!important; border-collapse: collapse; width: 100%; border: 1px solid #DEE2E6;">
                      <tr>
                        <td colspan="2" style="font-size: 16px; font-weight: bold; line-height: 24px; padding: 10px 6px; color: {color_gradient_1};">Dane rozliczeniowe</td>
                      </tr>
                      <tr>
                        <td style="font-size: 14px; padding: 8px 6px; vertical-align: top; width: 100%;">
                          <p style="margin-bottom: 2px; font-weight: bold;">{purchaser_full_name}</p>
                          <p style="margin-bottom: 2px;">{purchaser_email}</p>
                          <p>{purchaser_phone}</p>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

                <!-- INFO: Faktura -->
                <tr>
                  <td style="padding: 0 24px 16px 24px;">
                    <table cellpadding="0" cellspacing="0" style="min-width:100%!important; border-collapse: collapse; width: 100%; border: 1px solid #4CAF50;">
                      <tr>
                        <td style="font-size: 13px; padding: 8px 6px; background-color: #E8F5E9;">
                          <p style="margin: 0; color: #2E7D32;"><strong>Faktura VAT</strong> zostanie wysłana na podany adres email w ciągu 24h.</p>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

                <!-- FOOTER -->
                <tr>
                  <td valign="top">
                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="min-width:100%!important; background-color: #F8F9FA;">
                      <tr>
                        <td style="padding: 16px 24px;">
                          <p style="text-align: center; color: #666666; font-size: 13px; margin: 0;">Masz pytania? Skontaktuj się z nami: <a href="mailto:{md_email_kontakt}" style="color: {color_gradient_1}; text-decoration: underline;">{md_email_kontakt}</a></p>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

              </table>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>'''


def render_payment_confirmation_email(
    event_name: str,
    purchaser_first_name: str,
    purchaser_last_name: str,
    purchaser_email: str,
    purchaser_phone: str,
    total_gross: float,
    event_config: Optional[Dict[str, Any]] = None,
    tickets: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Renderuje email z potwierdzeniem płatności (po Stripe checkout).
    
    Args:
        event_name: Nazwa eventu
        purchaser_*: Dane kupującego
        total_gross: Kwota brutto
        event_config: Konfiguracja eventu (kolory, banery, itp.)
        tickets: Lista biletów [{name, quantity, price}]
    
    Returns:
        Gotowy HTML email
    """
    # Defaults
    event_config = event_config or get_default_event_config()
    tickets = tickets or []

    # Normalizuj bilety
    normalized_tickets: List[Dict[str, Any]] = []
    for t in tickets:
        try:
            name = (
                t.get("name")
                or t.get("ticket_name")
                or t.get("ticketName")
                or "Bilet"
            )
            qty = t.get("quantity", 1)
            try:
                qty_num = int(qty) if qty is not None else 1
            except (ValueError, TypeError):
                qty_num = 1

            price = t.get("price")
            if price is None:
                price = t.get("unit_price_gross")
            if price is None:
                price = t.get("unit_price")
            if price is None:
                tg = t.get("total_gross")
                if tg is not None and qty_num > 0:
                    try:
                        price = float(tg) / float(qty_num)
                    except (ValueError, TypeError):
                        price = 0

            try:
                price_num = float(price) if price is not None else 0.0
            except (ValueError, TypeError):
                price_num = 0.0

            normalized_tickets.append({
                "name": str(name),
                "quantity": qty_num,
                "price": price_num,
            })
        except Exception:
            continue
    
    # Oblicz wartości
    vat_calc = calculate_vat(total_gross)
    
    # Przygotuj dane do szablonu
    data = {
        "event_name": event_name,
        "purchaser_first_name": purchaser_first_name or "Uczestnik",
        "purchaser_full_name": f"{purchaser_first_name} {purchaser_last_name}".strip(),
        "purchaser_email": purchaser_email,
        "purchaser_phone": purchaser_phone or "",
        "total_gross_formatted": format_currency(vat_calc["gross"]),
        "total_net_formatted": format_currency(vat_calc["net"]),
        "total_vat_formatted": format_currency(vat_calc["vat"]),
        "tickets_rows": generate_tickets_table_rows(normalized_tickets, event_config.get("color_gradient_1", "#2563eb")),
        "event_datetime_section": _build_event_datetime_section(event_config),
        "event_location_section": _build_event_location_section(event_config),
        # Event config
        "color_gradient_1": event_config.get("color_gradient_1", "#2563eb"),
        "color_gradient_2": event_config.get("color_gradient_2", "#1e40af"),
        "md_email_kontakt": event_config.get("md_email_kontakt", "konferencje@medidesk.com"),
        "url_event": event_config.get("url_event", "https://medidesk.com"),
        "event_mail_link_top_banner": event_config.get("event_mail_link_top_banner", "https://via.placeholder.com/598x200/2563eb/ffffff?text=Event"),
    }
    
    return TEMPLATE_PAYMENT_CONFIRMATION.format(**data)


# =============================================================================
# SZABLON: Potwierdzenie rezerwacji dla UCZESTNIKA (indywidualny email)
# =============================================================================

TEMPLATE_PARTICIPANT_TICKET = '''<!doctype html>
<html lang="pl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Potwierdzenie rezerwacji – {event_name}</title>
</head>
<body style="margin: 0; padding: 0; min-width: 100%; background-color: #f5f5f5;">
  <table border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #f5f5f5;">
    <tr>
      <td align="center" style="padding: 20px 0;">
        <table border="0" cellpadding="0" cellspacing="0" width="600" style="background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
          <tr>
            <td>
              <table border="0" cellpadding="0" cellspacing="0" width="100%">
                
                <!-- TOP BANNER -->
                <tr>
                  <td valign="top">
                    <a href="{url_event}" target="_blank">
                      <img src="{event_mail_link_top_banner}" alt="{event_name}" style="display: block; width: 100%; max-width: 600px; height: auto;">
                    </a>
                  </td>
                </tr>

                <!-- HEADER: Potwierdzenie rezerwacji - BEZ GRADIENTU -->
                <tr>
                  <td style="padding: 24px 24px 16px 24px;">
                    <h1 style="margin: 0; font-size: 22px; color: #333333; font-weight: bold;">
                      Twoja rezerwacja jest potwierdzona!
                    </h1>
                  </td>
                </tr>

                <!-- GREETING -->
                <tr>
                  <td style="padding: 0 24px 20px 24px;">
                    <p style="margin: 0 0 12px 0; font-size: 16px; color: #333;">Cześć <strong>{participant_first_name}</strong>!</p>
                    <p style="margin: 0; font-size: 15px; color: #555; line-height: 1.5;">
                      Twoje miejsce na wydarzeniu <strong>{event_name}</strong> zostało potwierdzone. 
                      Poniżej znajdziesz szczegóły swojej rezerwacji.
                    </p>
                  </td>
                </tr>

                <!-- DANE WYDARZENIA - jasne tło -->
                <tr>
                  <td style="padding: 0 24px 16px 24px;">
                    <table cellpadding="0" cellspacing="0" style="width: 100%; background-color: #F8F9FA; border-radius: 8px;">
                      <tr>
                        <td style="padding: 16px;">
                          <p style="margin: 0 0 4px 0; font-size: 12px; color: #888; text-transform: uppercase; letter-spacing: 0.5px;">Wydarzenie</p>
                          <p style="margin: 0; font-size: 18px; color: #333; font-weight: bold;">{event_name}</p>
                          <p style="margin: 8px 0 0 0; font-size: 14px; color: {color_gradient_1}; font-weight: 500;">{ticket_name}</p>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

                <!-- EVENT DETAILS (data, lokalizacja) -->
                {event_datetime_section}
                {event_location_section}

                <!-- DANE UCZESTNIKA - białe tło z obramowaniem -->
                <tr>
                  <td style="padding: 0 24px 16px 24px;">
                    <table cellpadding="0" cellspacing="0" style="width: 100%; border: 1px solid #e0e0e0; border-radius: 8px;">
                      <tr>
                        <td style="padding: 16px;">
                          <p style="margin: 0 0 4px 0; font-size: 12px; color: #888; text-transform: uppercase; letter-spacing: 0.5px;">Uczestnik</p>
                          <p style="margin: 0; font-size: 16px; color: #333; font-weight: 500;">{participant_full_name}</p>
                          <p style="margin: 4px 0 0 0; font-size: 14px; color: #555;">{participant_email}</p>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

                <!-- WARTOŚĆ REZERWACJI -->
                <tr>
                  <td style="padding: 0 24px 16px 24px;">
                    <table cellpadding="0" cellspacing="0" style="width: 100%;">
                      <tr>
                        <td style="padding: 12px 0; border-top: 1px solid #e0e0e0;">
                          <span style="font-size: 13px; color: #888;">Wartość rezerwacji:</span>
                          <span style="font-size: 16px; color: #333; font-weight: bold; margin-left: 8px;">{ticket_price_formatted}</span>
                          {discount_info}
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

                <!-- NUMER POTWIERDZENIA -->
                <tr>
                  <td style="padding: 0 24px 20px 24px;">
                    <p style="margin: 0; font-size: 11px; color: #888;">
                      Numer potwierdzenia: <span style="font-family: monospace; color: #666;">{ticket_id}</span>
                    </p>
                  </td>
                </tr>

                <!-- FOOTER - jasne tło, ciemny tekst -->
                <tr>
                  <td valign="top">
                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #F8F9FA;">
                      <tr>
                        <td style="padding: 16px 24px;">
                          <p style="text-align: center; color: #666666; font-size: 13px; margin: 0;">
                            Masz pytania? Napisz do nas: <a href="mailto:{md_email_kontakt}" style="color: {color_gradient_1}; text-decoration: underline;">{md_email_kontakt}</a>
                          </p>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

              </table>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>'''


def render_participant_ticket_email(
    event_name: str,
    participant_first_name: str,
    participant_last_name: str,
    participant_email: str,
    ticket_name: str,
    ticket_id: str,
    ticket_price: float,
    discount_amount: float = 0.0,
    event_config: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Renderuje email z potwierdzeniem rezerwacji dla UCZESTNIKA (nie purchasera).
    
    Każdy uczestnik dostaje swój własny email z informacją o swojej rezerwacji.
    Bilety z kodami QR będą wysyłane osobno przed wydarzeniem.
    
    Args:
        event_name: Nazwa eventu
        participant_*: Dane uczestnika
        ticket_name: Nazwa/typ rezerwacji
        ticket_id: Numer potwierdzenia rezerwacji
        ticket_price: Wartość rezerwacji (brutto)
        discount_amount: Kwota rabatu (jeśli był)
        event_config: Konfiguracja eventu
    
    Returns:
        Gotowy HTML email
    """
    event_config = event_config or get_default_event_config()
    
    # Discount info
    discount_info = ""
    if discount_amount and discount_amount > 0:
        discount_info = f'<br><span style="font-size: 12px; color: #4CAF50;">Uwzględniono rabat: -{format_currency(discount_amount)}</span>'
    
    # Free ticket
    if ticket_price <= 0:
        price_formatted = "BEZPŁATNY"
    else:
        price_formatted = format_currency(ticket_price)
    
    data = {
        "event_name": event_name,
        "participant_first_name": participant_first_name or "Uczestnik",
        "participant_full_name": f"{participant_first_name} {participant_last_name}".strip() or "Uczestnik",
        "participant_email": participant_email,
        "ticket_name": ticket_name or "Rezerwacja",
        "ticket_id": ticket_id or "-",
        "ticket_price_formatted": price_formatted,
        "discount_info": discount_info,
        "event_datetime_section": _build_event_datetime_section(event_config),
        "event_location_section": _build_event_location_section(event_config),
        # Event config
        "color_gradient_1": event_config.get("color_gradient_1", "#2563eb"),
        "color_gradient_2": event_config.get("color_gradient_2", "#1e40af"),
        "md_email_kontakt": event_config.get("md_email_kontakt", "konferencje@medidesk.com"),
        "url_event": event_config.get("url_event", "https://medidesk.com"),
        "event_mail_link_top_banner": event_config.get("event_mail_link_top_banner", "https://via.placeholder.com/598x200/2563eb/ffffff?text=Event"),
    }
    
    return TEMPLATE_PARTICIPANT_TICKET.format(**data)
