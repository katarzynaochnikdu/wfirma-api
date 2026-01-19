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
        name = ticket.get("name", "Bilet")
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
    Potwierdź rezerwację na {event_name} – zapłać {total_gross_formatted}
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
                          <p>Dziękujemy za rejestrację na <strong>{event_name}</strong>. Aby potwierdzić rezerwację miejsca, wymagane jest dokonanie płatności.</p>
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
                        <td colspan="2" style="font-weight: bold; font-size: 16px; padding: 10px 6px; background-color: {color_gradient_2}; color: #ffffff;">Razem do zapłaty</td>
                        <td style="font-weight: bold; font-size: 16px; padding: 10px 6px; background-color: {color_gradient_2}; color: #ffffff; text-align: right;">{total_gross_formatted}</td>
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
                          <p style="margin: 0; color: #1565C0;">📄 <strong>Faktura zostanie wystawiona na osobę fizyczną</strong> zgodnie z podanymi danymi rozliczeniowymi.</p>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

                <!-- FOOTER -->
                <tr>
                  <td valign="top">
                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="min-width:100%!important; background-color: {color_gradient_1};">
                      <tr>
                        <td style="padding: 10px 24px;">
                          <p style="text-align: center; color: #ffffff; font-size: 14px;">Masz pytania? Skontaktuj się z nami: <a href="mailto:{md_email_kontakt}" style="color: #ffffff; text-decoration: underline;">{md_email_kontakt}</a></p>
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
    Potwierdź rezerwację na {event_name} – zapłać {total_gross_formatted}
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
                        <td><p>Dziękujemy za rejestrację na <strong>{event_name}</strong>. Aby potwierdzić rezerwację miejsca, wymagane jest dokonanie płatności.</p></td>
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
                        <td colspan="2" style="font-weight: bold; font-size: 16px; padding: 10px 6px; background-color: {color_gradient_2}; color: #ffffff;">Razem do zapłaty</td>
                        <td style="font-weight: bold; font-size: 16px; padding: 10px 6px; background-color: {color_gradient_2}; color: #ffffff; text-align: right;">{total_gross_formatted}</td>
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
                          ✅ Weryfikacja NIP
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
                          <p style="margin: 0 0 2px 0;">🏢 {gus_company_name}</p>
                          <p style="margin: 0 0 2px 0;">📍 {gus_address}</p>
                          <p style="margin: 0;">📋 REGON: {gus_regon}</p>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

                <!-- FOOTER -->
                <tr>
                  <td valign="top">
                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: {color_gradient_1};">
                      <tr>
                        <td style="padding: 10px 24px;">
                          <p style="text-align: center; color: #ffffff; font-size: 14px;">Masz pytania? Skontaktuj się z nami: <a href="mailto:{md_email_kontakt}" style="color: #ffffff; text-decoration: underline;">{md_email_kontakt}</a></p>
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
    Potwierdź rezerwację na {event_name} – zapłać {total_gross_formatted}
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
                        <td><p>Dziękujemy za rejestrację na <strong>{event_name}</strong>. Aby potwierdzić rezerwację miejsca, wymagane jest dokonanie płatności.</p></td>
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
                        <td colspan="2" style="font-weight: bold; font-size: 16px; padding: 10px 6px; background-color: {color_gradient_2}; color: #ffffff;">Razem do zapłaty</td>
                        <td style="font-weight: bold; font-size: 16px; padding: 10px 6px; background-color: {color_gradient_2}; color: #ffffff; text-align: right;">{total_gross_formatted}</td>
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
                          ⚠️ Weryfikacja NIP
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
                          <p style="margin: 0 0 8px 0; color: #E65100;">📄 <strong>Jeśli dokonasz płatności z tego linka</strong>, faktura zostanie wystawiona na osobę fizyczną.</p>
                          <p style="margin: 0; color: #333;">Jeśli chcesz otrzymać fakturę na firmę, zarejestruj się ponownie z poprawnym NIP:</p>
                        </td>
                      </tr>
                      <tr>
                        <td style="padding: 12px 6px; background-color: #FFF8E1; text-align: center;">
                          <a href="{url_event}" target="_blank" style="display: inline-block; padding: 10px 20px; background-color: #E65100; color: #ffffff; text-decoration: none; font-size: 14px; font-weight: bold; border-radius: 6px;">🔄 Zarejestruj się ponownie</a>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

                <!-- FOOTER -->
                <tr>
                  <td valign="top">
                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: {color_gradient_1};">
                      <tr>
                        <td style="padding: 10px 24px;">
                          <p style="text-align: center; color: #ffffff; font-size: 14px;">Masz pytania? Skontaktuj się z nami: <a href="mailto:{md_email_kontakt}" style="color: #ffffff; text-decoration: underline;">{md_email_kontakt}</a></p>
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
        "tickets_rows": generate_tickets_table_rows(tickets, event_config.get("color_gradient_1", "#2563eb")),
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
