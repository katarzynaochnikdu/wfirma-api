import json
import os
import csv
import io
from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, Response, abort, redirect, render_template_string, request, url_for

from pg_storage import (
    delete_event,
    get_event,
    get_ticket_classes,
    list_events,
    parse_kv_lines,
    replace_ticket_classes,
    upsert_event,
    # Payment rules
    list_payment_rules,
    get_payment_rule,
    upsert_payment_rule,
    delete_payment_rule,
    # Orders
    list_orders,
    get_order,
    update_order_status,
    get_wfirma_documents,
)


admin_bp = Blueprint("admin_bp", __name__)


ADMIN_PANEL_TOKEN = os.environ.get("ADMIN_PANEL_TOKEN")  # ustaw w Render ENV


# Definicje pól dla marketingu (label, opis, placeholder).
# Te klucze trafiają do events.data (JSONB). Panel ma być prosty i przewidywalny.
FIELD_DEFS: List[Dict[str, str]] = [
    {"key": "eventName", "label": "Nazwa wydarzenia", "hint": "np. Dental Practice Academy", "kind": "text"},
    {"key": "eventId", "label": "Event ID (Backstage)", "hint": "np. 24311000000651079", "kind": "text"},
    {"key": "md_email_kontakt", "label": "Email kontaktowy", "hint": "np. eventy@medidesk.com", "kind": "email"},
    {"key": "md_mobile_kontakt", "label": "Telefon kontaktowy", "hint": "np. +48 123 456 789", "kind": "phone"},
    {"key": "md_email_techniczny", "label": "Email techniczny", "hint": "np. adminzoho@medidesk.com", "kind": "email"},
    {"key": "md_mobile_techniczny", "label": "Telefon techniczny", "hint": "np. +48 123 456 789", "kind": "phone"},

    {"key": "event_location_google_link", "label": "Link Google Maps", "hint": "https://maps.app.goo.gl/…", "kind": "url"},
    {"key": "event_location_place", "label": "Miejsce", "hint": "np. Regent Warsaw Hotel", "kind": "text"},
    {"key": "event_location_address", "label": "Adres", "hint": "np. ul. Belwederska 23", "kind": "text"},
    {"key": "event_location_zip", "label": "Kod pocztowy", "hint": "np. 00-761", "kind": "text"},
    {"key": "event_location_city", "label": "Miasto", "hint": "np. Warszawa", "kind": "text"},
    {"key": "event_country", "label": "Kraj", "hint": "np. Polska", "kind": "text"},

    {"key": "event_date_time", "label": "Data i czas (ISO)", "hint": "np. 2026-02-05T09:00:00.000Z", "kind": "text"},
    {"key": "event_day", "label": "Dzień (liczba)", "hint": "np. 6", "kind": "text"},
    {"key": "event_month_number", "label": "Miesiąc (liczba)", "hint": "np. 2", "kind": "text"},
    {"key": "event_month_text", "label": "Miesiąc (tekst)", "hint": "np. luty", "kind": "text"},
    {"key": "event_month_text_odmiana", "label": "Miesiąc (odmiana)", "hint": "np. lutego", "kind": "text"},
    {"key": "event_year", "label": "Rok", "hint": "np. 2026", "kind": "text"},
    {"key": "event_time_text", "label": "Godzina (tekst)", "hint": "np. 10:00", "kind": "text"},
    {"key": "event_day_text_1", "label": "Data (tekst 1)", "hint": "np. 6 lutego 2026", "kind": "text"},
    {"key": "event_day_text_2", "label": "Data (tekst 2)", "hint": "opcjonalnie", "kind": "text"},

    {"key": "color_gradient_1", "label": "Kolor 1 (hex)", "hint": "np. #269571", "kind": "color"},
    {"key": "color_gradient_2", "label": "Kolor 2 (hex)", "hint": "np. #47005f", "kind": "color"},
    {"key": "color_gradient_angle", "label": "Kąt gradientu", "hint": "np. 90", "kind": "text"},

    {"key": "event_mapa_hotel_link", "label": "Link mapa hotel (grafika)", "hint": "https://…", "kind": "url"},
    {"key": "event_logo_link", "label": "Logo (link)", "hint": "https://…", "kind": "url"},
    {"key": "event_logo_link_white", "label": "Logo (białe) link", "hint": "https://…", "kind": "url"},
    {"key": "event_logo_link_color", "label": "Logo (kolor) link", "hint": "https://…", "kind": "url"},
    {"key": "event_picture_1_link", "label": "Zdjęcie 1 (link)", "hint": "https://…", "kind": "url"},
    {"key": "event_mail_link_top_banner", "label": "Baner mail (góra) link", "hint": "https://…", "kind": "url"},
    {"key": "event_mail_link_bottom_banner", "label": "Baner mail (dół) link", "hint": "https://…", "kind": "url"},

    {"key": "url_event", "label": "URL wydarzenia (public)", "hint": "https://…", "kind": "url"},
    {"key": "url_success", "label": "URL success", "hint": "https://…", "kind": "url"},
    {"key": "url_cancel", "label": "URL cancel", "hint": "https://…", "kind": "url"},
    {"key": "event_config_link", "label": "Link konfiguracji (Backstage)", "hint": "https://…", "kind": "url"},
    {"key": "event_orders_link", "label": "Link orders (Backstage)", "hint": "https://…", "kind": "url"},
    {"key": "event_attendees_link", "label": "Link attendees (Backstage)", "hint": "https://…", "kind": "url"},
]


def _require_admin_token() -> str:
    if not ADMIN_PANEL_TOKEN:
        abort(500, description="Brak ADMIN_PANEL_TOKEN w konfiguracji serwera")

    token = (
        (request.args.get("token") or "").strip()
        or (request.form.get("token") or "").strip()
        or (request.headers.get("X-Admin-Token") or "").strip()
    )
    if not token:
        abort(401, description="Brak tokenu admina (parametr token / header X-Admin-Token)")
    if token != ADMIN_PANEL_TOKEN:
        abort(403, description="Nieprawidłowy token admina")
    return token


def _safe_json_loads(s: str) -> Tuple[Optional[Any], Optional[str]]:
    try:
        return json.loads(s), None
    except Exception as e:
        return None, str(e)


def _field_name(key: str) -> str:
    return f"field__{key}"


def _is_http_url(value: str) -> bool:
    v = (value or "").strip().lower()
    return v.startswith("http://") or v.startswith("https://")


def _is_hex_color(value: str) -> bool:
    v = (value or "").strip()
    if not v.startswith("#"):
        return False
    if len(v) not in (4, 7):
        return False
    allowed = "0123456789abcdefABCDEF"
    return all(ch in allowed for ch in v[1:])


def _detect_delimiter(sample: str) -> str:
    # Prosty heurystyczny wybór dla CSV z Make (często ';')
    if sample.count(";") >= sample.count(","):
        return ";"
    return ","


def _parse_pivot_csv(content: bytes) -> List[Dict[str, str]]:
    """
    Parser dla formatu 'pivot' jak Twoje CSV z Make:
      - pierwszy wiersz to nagłówki: key;Rekord 1;Rekord 2;...
      - kolejne wiersze: pole;v1;v2;...
    Zwraca listę rekordów (dict key->value) o długości N (liczba kolumn rekordów).
    """
    text = content.decode("utf-8-sig", errors="replace")
    first_line = (text.splitlines() or [""])[0]
    delim = _detect_delimiter(first_line)
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    rows = list(reader)
    if not rows or len(rows[0]) < 2:
        return []

    # liczba rekordów = liczba kolumn - 1 (kolumna 0 to nazwa pola)
    record_count = max(0, len(rows[0]) - 1)
    records: List[Dict[str, str]] = [dict() for _ in range(record_count)]

    for r in rows[1:]:
        if not r:
            continue
        key = (r[0] or "").strip()
        if not key:
            continue
        for i in range(record_count):
            val = r[i + 1] if (i + 1) < len(r) else ""
            records[i][key] = (val or "").strip()

    # usuń rekordy całkiem puste
    records = [rec for rec in records if any(v for v in rec.values())]
    return records


def _parse_bilety_csv(content: bytes) -> List[Dict[str, str]]:
    """
    Parser dla Bilety.csv (pivot) – zwraca listę rekordów:
      {eventId, ticketClassId, ticketName, eventName}
    """
    records = _parse_pivot_csv(content)
    out: List[Dict[str, str]] = []
    for rec in records:
        event_id = (rec.get("eventId") or "").strip()
        ticket_class_id = (rec.get("ticketClassId") or "").strip()
        if not event_id or not ticket_class_id:
            continue
        out.append(
            {
                "eventId": event_id,
                "eventName": (rec.get("eventName") or "").strip(),
                "ticketClassId": ticket_class_id,
                "ticketName": (rec.get("ticketName") or "").strip(),
            }
        )
    return out


BASE_HTML = """
<!doctype html>
<html lang="pl">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{{ title }}</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 24px; color: #111; }
    a { color: #0b57d0; text-decoration: none; }
    a:hover { text-decoration: underline; }
    .row { display: flex; gap: 16px; }
    .card { border: 1px solid #ddd; border-radius: 8px; padding: 14px; background: #fff; }
    .muted { color: #666; font-size: 12px; }
    .pill { display:inline-block; padding: 2px 10px; border-radius: 999px; background: #f3f4f6; font-size: 12px; }
    input[type=text], textarea { width: 100%; padding: 10px; border-radius: 8px; border: 1px solid #ccc; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
    textarea { min-height: 260px; }
    .btn { display:inline-block; padding: 10px 14px; border-radius: 8px; border: 1px solid #ccc; background: #f8f9fa; color: #111; cursor: pointer; }
    .btnPrimary { border-color: #0b57d0; background: #0b57d0; color: #fff; }
    .btnDanger { border-color: #b42318; background: #b42318; color: #fff; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    .kv { display: grid; grid-template-columns: 220px 1fr; gap: 8px 14px; font-size: 14px; }
    .kv > div { padding: 6px 0; border-bottom: 1px dashed #eee; }
    code { background: #f3f4f6; padding: 2px 6px; border-radius: 6px; }
    .banner { width: 100%; max-width: 900px; border: 1px solid #eee; border-radius: 10px; overflow: hidden; }
    img { max-width: 100%; height: auto; display: block; }
    .warn { background: #fff8e1; border: 1px solid #ffe082; padding: 10px 12px; border-radius: 8px; }
    .error { background: #fff5f5; border: 1px solid #fecaca; padding: 10px 12px; border-radius: 8px; }
    .ok { background: #ecfdf3; border: 1px solid #bbf7d0; padding: 10px 12px; border-radius: 8px; }
    .formGrid { display: grid; grid-template-columns: 280px 1fr; gap: 10px 14px; align-items: start; }
    .formLabel { font-size: 13px; color: #111; padding-top: 10px; }
    .formHint { font-size: 12px; color: #666; margin-top: 4px; }
    .swatch { width: 28px; height: 18px; border: 1px solid #ddd; border-radius: 5px; display: inline-block; vertical-align: middle; margin-left: 10px; }
    details { border: 1px solid #eee; border-radius: 8px; padding: 10px 12px; background: #fafafa; }
    summary { cursor: pointer; font-weight: 700; }
  </style>
</head>
<body>
  <div class="row" style="justify-content: space-between; align-items: baseline;">
    <div>
      <h2 style="margin:0;">{{ title }}</h2>
      <div class="muted">Panel admin (Postgres) – zabezpieczony tokenem</div>
    </div>
    <div class="muted">token: <code>***</code></div>
  </div>
  <hr style="border:none;border-top:1px solid #eee;margin:16px 0;" />
  {{ body|safe }}
</body>
</html>
"""


def _page(title: str, body: str) -> str:
    return render_template_string(BASE_HTML, title=title, body=body)


@admin_bp.route("/", methods=["GET"])
def admin_root():
    token = _require_admin_token()
    return redirect(url_for("admin_bp.events_list", token=token))


@admin_bp.route("/import", methods=["GET"])
def import_page():
    token = _require_admin_token()
    body = f"""
    <div style="margin-bottom:12px;">
      <a class="btn" href="{url_for('admin_bp.events_list', token=token)}">← Lista wydarzeń</a>
    </div>
    <div class="card">
      <div style="font-weight:700; margin-bottom:10px;">Import konfiguracji z CSV (Make)</div>
      <div class="muted">
        Wgraj <code>Wydarzenia.csv</code> i <code>Bilety.csv</code>. Import zrobi:
        <ul>
          <li>upsert eventów (po <code>eventId</code>)</li>
          <li>replace klas biletów dla eventów z pliku</li>
        </ul>
        <div class="warn">
          <b>Uwaga:</b> bilety zostaną zaimportowane tylko dla eventów, które istnieją w <code>Wydarzenia.csv</code>.
          Dzięki temu archiwalne eventy z <code>Bilety.csv</code> nie wywalą importu (FK w bazie).
        </div>
      </div>
      <form method="post" action="{url_for('admin_bp.import_run')}" enctype="multipart/form-data" style="margin-top:12px;">
        <input type="hidden" name="token" value="{token}" />
        <div class="muted">Wydarzenia.csv</div>
        <input type="file" name="wydarzenia" accept=".csv" />
        <div style="height:10px;"></div>
        <div class="muted">Bilety.csv</div>
        <input type="file" name="bilety" accept=".csv" />
        <div style="height:14px;"></div>
        <label class="muted"><input type="checkbox" name="confirm" value="yes" /> Potwierdzam import (nadpisze klasy biletów dla eventów z pliku)</label>
        <div style="height:14px;"></div>
        <button class="btn btnPrimary" type="submit">Importuj</button>
      </form>
    </div>
    """
    return _page("Import CSV", body)


@admin_bp.route("/import", methods=["POST"])
def import_run():
    token = _require_admin_token()
    confirm = (request.form.get("confirm") or "").strip().lower() == "yes"
    if not confirm:
        body = f"<div class='error'>Zaznacz potwierdzenie importu.</div><p><a class='btn' href='{url_for('admin_bp.import_page', token=token)}'>Wróć</a></p>"
        return _page("Błąd importu", body), 400

    wydarzenia_file = request.files.get("wydarzenia")
    bilety_file = request.files.get("bilety")

    if not wydarzenia_file or not wydarzenia_file.filename:
        body = f"<div class='error'>Brak pliku Wydarzenia.csv</div><p><a class='btn' href='{url_for('admin_bp.import_page', token=token)}'>Wróć</a></p>"
        return _page("Błąd importu", body), 400

    wydarzenia_records = _parse_pivot_csv(wydarzenia_file.read())
    bilety_records: List[Dict[str, str]] = []
    if bilety_file and bilety_file.filename:
        bilety_records = _parse_bilety_csv(bilety_file.read())

    # Import events
    imported_events = 0
    event_ids: List[str] = []
    for rec in wydarzenia_records:
        event_id = (rec.get("eventId") or rec.get("eventID") or rec.get("event_id") or "").strip()
        event_name = (rec.get("eventName") or "").strip()
        status = (rec.get("Status wprowadzenia do MAKE") or rec.get("Status") or "").strip()
        notes = (rec.get("UWAGI") or "").strip()
        if not event_id or not event_name:
            continue

        # dane w JSONB: wszystkie pola poza metadanymi
        data: Dict[str, Any] = {}
        for k, v in rec.items():
            if k in ("Status wprowadzenia do MAKE", "UWAGI"):
                continue
            data[k] = v
        # fallback
        data.setdefault("eventId", event_id)
        data.setdefault("eventName", event_name)

        upsert_event(event_id=event_id, event_name=event_name, status=status, notes=notes, data=data)
        imported_events += 1
        event_ids.append(event_id)

    # Import ticket classes grouped by event
    imported_ticket_classes = 0
    skipped_ticket_events: List[str] = []
    if bilety_records:
        event_id_set = set(event_ids)
        by_event: Dict[str, List[Dict[str, Any]]] = {}
        for r in bilety_records:
            eid = (r.get("eventId") or "").strip()
            if not eid:
                continue
            # Importuj bilety tylko dla eventów, które istnieją w Wydarzenia.csv
            if eid not in event_id_set:
                skipped_ticket_events.append(eid)
                continue
            by_event.setdefault(eid, []).append(
                {
                    "ticket_class_id": (r.get("ticketClassId") or "").strip(),
                    "ticket_name": (r.get("ticketName") or "").strip(),
                    "data": {},
                }
            )

        for eid, classes in by_event.items():
            replace_ticket_classes(eid, classes)
            imported_ticket_classes += len(classes)

    skipped_html = ""
    if skipped_ticket_events:
        uniq = sorted(set(skipped_ticket_events))
        skipped_html = (
            "<div class='warn' style='margin-top:12px;'>"
            "<b>Pominięte bilety dla eventów (brak w Wydarzenia.csv):</b><br/>"
            + " ".join(f"<code>{x}</code>" for x in uniq[:50])
            + ("<div class='muted' style='margin-top:6px;'>… (ucięto listę)</div>" if len(uniq) > 50 else "")
            + "</div>"
        )

    body = f"""
    <div class="ok"><b>Import zakończony.</b></div>
    <div style="height:10px;"></div>
    <div class="card">
      <div class="kv">
        <div class="muted">Zaimportowane eventy</div><div><b>{imported_events}</b></div>
        <div class="muted">Zaimportowane klasy biletów</div><div><b>{imported_ticket_classes}</b></div>
      </div>
    </div>
    {skipped_html}
    <div style="height:12px;"></div>
    <a class="btn btnPrimary" href="{url_for('admin_bp.events_list', token=token)}">Przejdź do listy wydarzeń</a>
    """
    return _page("Import OK", body)


@admin_bp.route("/events", methods=["GET"])
def events_list():
    token = _require_admin_token()
    events = list_events(limit=500)

    rows = []
    for e in events:
        rows.append(
            f"""
            <div class="card">
              <div style="display:flex; justify-content: space-between; gap: 10px;">
                <div>
                  <div style="font-weight:700;">{e.get('event_name','')}</div>
                  <div class="muted"><code>{e.get('event_id','')}</code></div>
                </div>
                <div>
                  <span class="pill">{(e.get('status') or '—')}</span>
                </div>
              </div>
              <div style="margin-top:10px; display:flex; gap:10px; flex-wrap:wrap;">
                <a class="btn" href="{url_for('admin_bp.event_edit', event_id=e.get('event_id',''), token=token)}">Edytuj</a>
                <a class="btn" href="{url_for('admin_bp.event_preview', event_id=e.get('event_id',''), token=token)}">Podgląd</a>
              </div>
            </div>
            """
        )

    body = f"""
    <div style="margin-bottom:14px;">
      <a class="btn btnPrimary" href="{url_for('admin_bp.event_new', token=token)}">+ Nowe wydarzenie</a>
      <a class="btn" style="margin-left:10px;" href="{url_for('admin_bp.import_page', token=token)}">Import CSV</a>
      <a class="btn" style="margin-left:10px; background:#e3f2fd;" href="{url_for('admin_bp.orders_list', token=token)}">Zamówienia</a>
      <span class="muted" style="margin-left:10px;">Zalecane: trzymaj token tylko u adminów.</span>
    </div>
    <div class="grid">
      {''.join(rows) if rows else '<div class="muted">Brak wydarzeń</div>'}
    </div>
    """
    return _page("Admin – wydarzenia", body)


@admin_bp.route("/events/new", methods=["GET"])
def event_new():
    token = _require_admin_token()
    return _event_form_page(token=token, event=None, tickets=[])


@admin_bp.route("/events/<event_id>/edit", methods=["GET"])
def event_edit(event_id: str):
    token = _require_admin_token()
    ev = get_event(event_id)
    if not ev:
        abort(404, description="Nie znaleziono eventu")
    tickets = get_ticket_classes(event_id)
    return _event_form_page(token=token, event=ev, tickets=tickets)


@admin_bp.route("/events/save", methods=["POST"])
def event_save():
    token = _require_admin_token()

    event_id = (request.form.get("event_id") or "").strip()
    event_name = (request.form.get("event_name") or "").strip()
    status = (request.form.get("status") or "").strip()
    notes = (request.form.get("notes") or "").strip()

    data_json = (request.form.get("data_json") or "").strip()
    kv_paste = (request.form.get("kv_paste") or "").strip()
    ticket_classes_json = (request.form.get("ticket_classes_json") or "").strip()

    if not event_id or not event_name:
        body = f'<div class="error">Wymagane: event_id i event_name</div><p><a class="btn" href="{url_for("admin_bp.event_new", token=token)}">Wróć</a></p>'
        return _page("Błąd", body), 400

    data: Dict[str, Any] = {}

    if data_json:
        parsed, err = _safe_json_loads(data_json)
        if err or not isinstance(parsed, dict):
            body = f'<div class="error">Niepoprawny JSON w data_json: {err}</div><p><a class="btn" href="{url_for("admin_bp.event_edit", event_id=event_id, token=token)}">Wróć</a></p>'
            return _page("Błąd", body), 400
        data = parsed

    if kv_paste:
        data.update(parse_kv_lines(kv_paste))

    # Pola formularza (marketing) – zawsze bierzemy wartości z inputów.
    # Dla istniejących eventów pola są prefill, więc zapisuje "cały formularz".
    for fd in FIELD_DEFS:
        k = fd["key"]
        data[k] = (request.form.get(_field_name(k)) or "").strip()

    # Fallback: jeśli ktoś nie wypełni eventId/eventName w data, uzupełnij.
    if not data.get("eventId"):
        data["eventId"] = event_id
    if not data.get("eventName"):
        data["eventName"] = event_name

    # Ticket classes
    ticket_classes: List[Dict[str, Any]] = []
    if ticket_classes_json:
        parsed, err = _safe_json_loads(ticket_classes_json)
        if err or not isinstance(parsed, list):
            body = f'<div class="error">Niepoprawny JSON w ticket_classes_json: {err}</div><p><a class="btn" href="{url_for("admin_bp.event_edit", event_id=event_id, token=token)}">Wróć</a></p>'
            return _page("Błąd", body), 400
        for item in parsed:
            if not isinstance(item, dict):
                continue
            ticket_classes.append(
                {
                    "ticket_class_id": item.get("ticket_class_id"),
                    "ticket_name": item.get("ticket_name"),
                    "data": item.get("data") or {},
                }
            )

    upsert_event(event_id=event_id, event_name=event_name, status=status, notes=notes, data=data)
    if ticket_classes_json:
        replace_ticket_classes(event_id, ticket_classes)

    return redirect(url_for("admin_bp.event_edit", event_id=event_id, token=token))


@admin_bp.route("/events/<event_id>/delete", methods=["POST"])
def event_delete(event_id: str):
    token = _require_admin_token()
    delete_event(event_id)
    return redirect(url_for("admin_bp.events_list", token=token))


def _render_event_preview(token: str, event_id: str, event_name: str, data: Dict[str, Any]) -> str:
    def _val(k: str) -> str:
        v = data.get(k)
        return (str(v).strip() if v is not None else "")

    banner = _val("event_mail_link_top_banner") or _val("event_mail_link_bottom_banner")
    logo = _val("event_logo_link") or _val("event_logo_link_white") or _val("event_logo_link_color")
    color1 = _val("color_gradient_1")
    color2 = _val("color_gradient_2")

    missing = [fd["key"] for fd in FIELD_DEFS if not _val(fd["key"])]
    missing_html = ""
    if missing:
        missing_html = (
            "<div class='warn'><b>Brakuje pól:</b> "
            + ", ".join(f"<code>{k}</code>" for k in missing)
            + "</div>"
        )
    else:
        missing_html = "<div class='ok'><b>OK:</b> wszystkie pola są wypełnione.</div>"

    warnings = []
    for fd in FIELD_DEFS:
        k = fd["key"]
        kind = fd.get("kind")
        v = _val(k)
        if not v:
            continue
        if kind == "url" and not _is_http_url(v):
            warnings.append(f"<div class='warn'>Pole <code>{k}</code> nie wygląda jak URL (brak http/https).</div>")
        if kind == "color" and not _is_hex_color(v):
            warnings.append(f"<div class='warn'>Pole <code>{k}</code> nie wygląda jak kolor hex (np. #269571).</div>")

    warn_html = "".join(warnings)

    def _fmt_value(fd: Dict[str, str]) -> str:
        k = fd["key"]
        v = _val(k)
        if not v:
            return "—"
        kind = fd.get("kind")
        if kind == "url" and _is_http_url(v):
            return f'<a href="{v}" target="_blank" rel="noopener noreferrer">{v}</a>'
        if kind == "color" and _is_hex_color(v):
            return f'{v}<span class="swatch" style="background:{v};"></span>'
        return v

    kv_html = "".join(
        f"<div class='muted'>{fd['label']}<div class='formHint'><code>{fd['key']}</code></div></div>"
        f"<div>{_fmt_value(fd)}</div>"
        for fd in FIELD_DEFS
    )

    body = f"""
    <div style="margin-bottom:12px;">
      <a class="btn" href="{url_for('admin_bp.event_edit', event_id=event_id, token=token)}">← Wróć do edycji</a>
      <a class="btn" href="{url_for('admin_bp.events_list', token=token)}">Lista wydarzeń</a>
    </div>
    {missing_html}
    {warn_html}
    <div class="card" style="margin-top:12px;">
      <div style="font-weight:700; font-size:18px;">{event_name}</div>
      <div class="muted"><code>{event_id}</code></div>
    </div>
    <div class="grid" style="margin-top:16px;">
      <div class="card">
        <div style="font-weight:700; margin-bottom:10px;">Podgląd (baner/logo/kolory)</div>
        <div class="banner">
          {'<img src="'+banner+'" alt="banner" />' if banner else '<div class="muted" style="padding:12px;">Brak banera</div>'}
        </div>
        <div style="margin-top:10px; display:flex; gap:12px; align-items:center;">
          <div style="width:72px; height:72px; border:1px solid #eee; border-radius:12px; overflow:hidden;">
            {'<img src="'+logo+'" alt="logo" />' if logo else '<div class="muted" style="padding:10px;">Brak logo</div>'}
          </div>
          <div>
            <div class="muted">color_gradient_1 / color_gradient_2</div>
            <div style="display:flex; gap:8px; margin-top:4px;">
              <div style="width:42px;height:26px;border-radius:6px;border:1px solid #eee;background:{(color1 if _is_hex_color(color1) else '#fff')}"></div>
              <div style="width:42px;height:26px;border-radius:6px;border:1px solid #eee;background:{(color2 if _is_hex_color(color2) else '#fff')}"></div>
            </div>
          </div>
        </div>
      </div>

      <div class="card">
        <div style="font-weight:700; margin-bottom:10px;">Pola (pełna lista)</div>
        <div class="kv">{kv_html}</div>
      </div>
    </div>
    """
    return _page("Podgląd wydarzenia", body)


@admin_bp.route("/events/<event_id>/preview", methods=["GET"])
def event_preview(event_id: str):
    token = _require_admin_token()
    ev = get_event(event_id)
    if not ev:
        abort(404, description="Nie znaleziono eventu")

    data = ev.get("data") or {}
    if not isinstance(data, dict):
        data = {}
    return _render_event_preview(
        token=token,
        event_id=str(ev.get("event_id") or event_id),
        event_name=str(ev.get("event_name") or ""),
        data=data,
    )


@admin_bp.route("/events/preview-draft", methods=["POST"])
def preview_draft():
    """Podgląd bez zapisu – przydatne dla marketingu."""
    token = _require_admin_token()

    event_id = (request.form.get("event_id") or "").strip()
    event_name = (request.form.get("event_name") or "").strip()
    if not event_id or not event_name:
        abort(400, description="Wymagane: event_id i event_name")

    data: Dict[str, Any] = {}
    data_json = (request.form.get("data_json") or "").strip()
    kv_paste = (request.form.get("kv_paste") or "").strip()
    if data_json:
        parsed, err = _safe_json_loads(data_json)
        if not err and isinstance(parsed, dict):
            data = parsed
    if kv_paste:
        data.update(parse_kv_lines(kv_paste))
    for fd in FIELD_DEFS:
        k = fd["key"]
        data[k] = (request.form.get(_field_name(k)) or "").strip()

    if not data.get("eventId"):
        data["eventId"] = event_id
    if not data.get("eventName"):
        data["eventName"] = event_name

    return _render_event_preview(token=token, event_id=event_id, event_name=event_name, data=data)


def _event_form_page(token: str, event: Optional[Dict[str, Any]], tickets: List[Dict[str, Any]]) -> str:
    is_new = event is None
    event_id = "" if is_new else (event.get("event_id") or "")
    event_name = "" if is_new else (event.get("event_name") or "")
    status = "" if is_new else (event.get("status") or "")
    notes = "" if is_new else (event.get("notes") or "")
    data = {} if is_new else (event.get("data") or {})
    if not isinstance(data, dict):
        data = {}

    # Ticket classes -> JSON array (proste do wklejenia)
    ticket_classes_payload: List[Dict[str, Any]] = []
    for t in tickets or []:
        ticket_classes_payload.append(
            {
                "ticket_class_id": t.get("ticket_class_id"),
                "ticket_name": t.get("ticket_name"),
                "data": t.get("data") or {},
            }
        )
    ticket_classes_json = json.dumps(ticket_classes_payload, ensure_ascii=False, indent=2)

    data_json = json.dumps(data, ensure_ascii=False, indent=2)

    # Prefill wartości pól
    field_values: Dict[str, str] = {}
    for fd in FIELD_DEFS:
        k = fd["key"]
        v = data.get(k)
        field_values[k] = (str(v) if v is not None else "")

    fields_html = []
    for fd in FIELD_DEFS:
        k = fd["key"]
        label = fd["label"]
        hint = fd.get("hint", "")
        kind = fd.get("kind", "text")
        raw_val = field_values.get(k) or ""
        safe_val = raw_val.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        swatch = ""
        if kind == "color" and _is_hex_color(raw_val):
            swatch = f'<span class="swatch" style="background:{raw_val};"></span>'
        fields_html.append(
            f"""
            <div class="formLabel">{label}<div class="formHint"><code>{k}</code> {swatch}</div></div>
            <div>
              <input type="text" name="{_field_name(k)}" value="{safe_val}" placeholder="{hint}" />
            </div>
            """
        )

    preview_link = ""
    rules_link = ""
    if event_id:
        preview_link = f'<a class="btn" href="{url_for("admin_bp.event_preview", event_id=event_id, token=token)}">Podgląd</a>'
        rules_link = f'<a class="btn" style="background:#e3f2fd;" href="{url_for("admin_bp.payment_rules_list", event_id=event_id, token=token)}">Reguły płatności</a>'

    delete_form = ""
    if event_id:
        delete_form = f"""
        <form method="post" action="{url_for('admin_bp.event_delete', event_id=event_id)}" onsubmit="return confirm('Usunąć wydarzenie {event_id}?');" style="display:inline;">
          <input type="hidden" name="token" value="{token}" />
          <button class="btn btnDanger" type="submit">Usuń</button>
        </form>
        """

    body = f"""
    <div style="margin-bottom:12px;">
      <a class="btn" href="{url_for('admin_bp.events_list', token=token)}">← Lista wydarzeń</a>
      {preview_link}
      {rules_link}
      {delete_form}
    </div>

    <div class="grid">
      <div class="card">
        <div style="font-weight:700; margin-bottom:10px;">Dane wydarzenia</div>
        <form method="post" action="{url_for('admin_bp.event_save')}">
          <input type="hidden" name="token" value="{token}" />
          <div class="muted">event_id</div>
          <input type="text" name="event_id" value="{event_id}" placeholder="np. 24311000000651079" {'readonly' if (not is_new) else ''} />
          <div style="height:10px;"></div>

          <div class="muted">event_name</div>
          <input type="text" name="event_name" value="{event_name}" placeholder="np. Dental Practice Academy" />
          <div style="height:10px;"></div>

          <div class="muted">status (opcjonalnie)</div>
          <input type="text" name="status" value="{status}" placeholder="np. w systemie" />
          <div style="height:10px;"></div>

          <div class="muted">notes (opcjonalnie)</div>
          <input type="text" name="notes" value="{notes}" placeholder="np. DPA" />
          <div style="height:10px;"></div>

          <div class="muted" style="margin: 8px 0 6px 0;">Pola do wypełnienia (marketing)</div>
          <div class="formGrid">
            {''.join(fields_html)}
          </div>

          <div style="height:10px;"></div>
          <div style="display:flex; gap:10px; flex-wrap:wrap;">
            <button class="btn" type="submit" formaction="{url_for('admin_bp.preview_draft')}" formmethod="post">Podgląd (bez zapisu)</button>
            <button class="btn btnPrimary" type="submit">Zapisz</button>
          </div>

          <div style="height:10px;"></div>
          <details>
            <summary>Zaawansowane (dla technicznych): JSON / wklejka / bilety</summary>
            <div style="height:10px;"></div>
            <div class="muted">data_json (pełny JSON – jeśli potrzebujesz)</div>
            <textarea name="data_json">{data_json}</textarea>
            <div style="height:10px;"></div>
            <div class="muted">Szybkie wklejenie (key TAB value / key: value). Nadpisuje/uzupełnia data_json.</div>
            <textarea name="kv_paste" placeholder="event_location_place<TAB>Regent Warsaw Hotel"></textarea>
            <div style="height:10px;"></div>
            <div class="muted">ticket_classes_json (lista) – opcjonalnie</div>
            <textarea name="ticket_classes_json">{ticket_classes_json}</textarea>
          </details>
        </form>
      </div>

      <div class="card">
        <div style="font-weight:700; margin-bottom:10px;">Instrukcja dla marketingu</div>
        <div class="muted">
          1) Wypełnij pola po lewej.<br/>
          2) Linki zawsze zaczynaj od <code>https://</code>.<br/>
          3) Kolory wpisuj jako hex, np. <code>#269571</code>.<br/>
          4) Kliknij <b>Podgląd (bez zapisu)</b> – sprawdzisz baner/logo/linki zanim zapiszesz.
        </div>
        <div style="height:10px;"></div>
        <div class="muted"><b>Uwaga:</b> token w URL trafia do logów. Docelowo możemy zrobić logowanie (cookie), żeby token nie był w adresie.</div>
      </div>
    </div>
    """
    return _page("Edytuj wydarzenie" if not is_new else "Nowe wydarzenie", body)


# ---------------------------------------------------------------------------
# PAYMENT RULES MANAGEMENT
# ---------------------------------------------------------------------------

FLOW_OPTIONS = ["FOC", "PROFORMA", "STRIPE"]
WFIRMA_DOC_TYPES = ["proforma", "normal", "proforma_bill"]


@admin_bp.route("/events/<event_id>/rules", methods=["GET"])
def payment_rules_list(event_id: str):
    """Lista reguł płatności dla eventu."""
    token = _require_admin_token()
    ev = get_event(event_id)
    if not ev:
        abort(404, description="Nie znaleziono eventu")

    rules = list_payment_rules(event_id)

    rows = []
    for r in rules:
        flow = r.get("flow", "")
        flow_class = {
            "FOC": "background:#ecfdf3;",
            "PROFORMA": "background:#fff8e1;",
            "STRIPE": "background:#e3f2fd;",
        }.get(flow, "")

        pattern = r.get("payment_option_name_pattern") or ""
        ptype = r.get("payment_type")
        is_default = r.get("is_default")

        match_desc = []
        if pattern:
            match_desc.append(f'nazwa zawiera: <code>{pattern}</code>')
        if ptype is not None:
            match_desc.append(f'payment_type = <code>{ptype}</code>')
        if is_default:
            match_desc.append('<span class="pill" style="background:#fef3c7;">DOMYŚLNA</span>')
        if not match_desc:
            match_desc.append('<span class="muted">brak warunków</span>')

        rows.append(f"""
            <div class="card" style="margin-bottom:10px;">
              <div style="display:flex; justify-content:space-between; align-items:start; gap:10px;">
                <div>
                  <div style="font-weight:700;">
                    <span class="pill" style="{flow_class}">{flow}</span>
                  </div>
                  <div class="muted" style="margin-top:6px;">
                    Dopasowanie: {' | '.join(match_desc)}
                  </div>
                  <div class="muted" style="margin-top:4px;">
                    wFirma: {r.get('wfirma_document_type') or '—'} / seria: {r.get('wfirma_series_name') or '—'}
                  </div>
                </div>
                <div style="display:flex; gap:8px;">
                  <a class="btn" href="{url_for('admin_bp.payment_rule_edit', event_id=event_id, rule_id=r.get('id'), token=token)}">Edytuj</a>
                  <form method="post" action="{url_for('admin_bp.payment_rule_delete', event_id=event_id, rule_id=r.get('id'))}" onsubmit="return confirm('Usunąć regułę?');" style="display:inline;">
                    <input type="hidden" name="token" value="{token}" />
                    <button class="btn btnDanger" type="submit">Usuń</button>
                  </form>
                </div>
              </div>
            </div>
        """)

    body = f"""
    <div style="margin-bottom:12px;">
      <a class="btn" href="{url_for('admin_bp.event_edit', event_id=event_id, token=token)}">← Wróć do eventu</a>
      <a class="btn" href="{url_for('admin_bp.events_list', token=token)}">Lista wydarzeń</a>
    </div>

    <div class="card" style="margin-bottom:16px;">
      <div style="font-weight:700;">{ev.get('event_name', '')}</div>
      <div class="muted"><code>{event_id}</code></div>
    </div>

    <div style="margin-bottom:14px;">
      <a class="btn btnPrimary" href="{url_for('admin_bp.payment_rule_new', event_id=event_id, token=token)}">+ Nowa reguła płatności</a>
    </div>

    <div class="muted" style="margin-bottom:10px;">
      <b>Jak działa routing?</b><br/>
      1. Jeśli <code>total = 0</code> → zawsze <b>FOC</b> (Free of Charge)<br/>
      2. Inaczej: dopasuj regułę po <code>payment_option_name</code> (zawiera) lub <code>payment_type</code><br/>
      3. Jeśli brak dopasowania → użyj reguły domyślnej
    </div>

    {''.join(rows) if rows else '<div class="muted">Brak reguł. Dodaj pierwszą regułę płatności.</div>'}
    """
    return _page(f"Reguły płatności – {ev.get('event_name', '')}", body)


@admin_bp.route("/events/<event_id>/rules/new", methods=["GET"])
def payment_rule_new(event_id: str):
    """Formularz nowej reguły płatności."""
    token = _require_admin_token()
    ev = get_event(event_id)
    if not ev:
        abort(404, description="Nie znaleziono eventu")
    return _payment_rule_form(token, ev, rule=None)


@admin_bp.route("/events/<event_id>/rules/<int:rule_id>/edit", methods=["GET"])
def payment_rule_edit(event_id: str, rule_id: int):
    """Formularz edycji reguły płatności."""
    token = _require_admin_token()
    ev = get_event(event_id)
    if not ev:
        abort(404, description="Nie znaleziono eventu")
    rule = get_payment_rule(rule_id)
    if not rule or rule.get("event_id") != event_id:
        abort(404, description="Nie znaleziono reguły")
    return _payment_rule_form(token, ev, rule=rule)


@admin_bp.route("/events/<event_id>/rules/save", methods=["POST"])
def payment_rule_save(event_id: str):
    """Zapisuje regułę płatności."""
    token = _require_admin_token()
    ev = get_event(event_id)
    if not ev:
        abort(404, description="Nie znaleziono eventu")

    rule_id_str = (request.form.get("rule_id") or "").strip()
    rule_id = int(rule_id_str) if rule_id_str else None

    flow = (request.form.get("flow") or "").strip().upper()
    if flow not in FLOW_OPTIONS:
        body = f'<div class="error">Nieprawidłowy flow: {flow}</div><p><a class="btn" href="{url_for("admin_bp.payment_rules_list", event_id=event_id, token=token)}">Wróć</a></p>'
        return _page("Błąd", body), 400

    payment_option_name_pattern = (request.form.get("payment_option_name_pattern") or "").strip() or None
    payment_type_str = (request.form.get("payment_type") or "").strip()
    payment_type = int(payment_type_str) if payment_type_str else None
    is_default = (request.form.get("is_default") or "").lower() == "on"

    wfirma_company = (request.form.get("wfirma_company") or "").strip() or None
    wfirma_series_name = (request.form.get("wfirma_series_name") or "").strip() or None
    wfirma_document_type = (request.form.get("wfirma_document_type") or "").strip() or None
    wfirma_payment_due_days_str = (request.form.get("wfirma_payment_due_days") or "").strip()
    wfirma_payment_due_days = int(wfirma_payment_due_days_str) if wfirma_payment_due_days_str else None

    upsert_payment_rule(
        event_id=event_id,
        flow=flow,
        rule_id=rule_id,
        payment_option_id=None,
        payment_type=payment_type,
        payment_option_name_pattern=payment_option_name_pattern,
        is_default=is_default,
        wfirma_company=wfirma_company,
        wfirma_series_name=wfirma_series_name,
        wfirma_document_type=wfirma_document_type,
        wfirma_payment_due_days=wfirma_payment_due_days,
    )

    return redirect(url_for("admin_bp.payment_rules_list", event_id=event_id, token=token))


@admin_bp.route("/events/<event_id>/rules/<int:rule_id>/delete", methods=["POST"])
def payment_rule_delete(event_id: str, rule_id: int):
    """Usuwa regułę płatności."""
    token = _require_admin_token()
    delete_payment_rule(rule_id)
    return redirect(url_for("admin_bp.payment_rules_list", event_id=event_id, token=token))


def _payment_rule_form(token: str, event: Dict[str, Any], rule: Optional[Dict[str, Any]]) -> str:
    """Renderuje formularz reguły płatności."""
    is_new = rule is None
    event_id = event.get("event_id", "")
    event_name = event.get("event_name", "")

    rule_id = "" if is_new else (rule.get("id") or "")
    flow = "" if is_new else (rule.get("flow") or "")
    payment_option_name_pattern = "" if is_new else (rule.get("payment_option_name_pattern") or "")
    payment_type = "" if is_new else (rule.get("payment_type") if rule.get("payment_type") is not None else "")
    is_default = False if is_new else bool(rule.get("is_default"))
    wfirma_company = "" if is_new else (rule.get("wfirma_company") or "")
    wfirma_series_name = "" if is_new else (rule.get("wfirma_series_name") or "")
    wfirma_document_type = "" if is_new else (rule.get("wfirma_document_type") or "")
    wfirma_payment_due_days = "" if is_new else (rule.get("wfirma_payment_due_days") if rule.get("wfirma_payment_due_days") is not None else "")

    flow_options_html = "".join(
        f'<option value="{f}" {"selected" if f == flow else ""}>{f}</option>'
        for f in FLOW_OPTIONS
    )

    doc_type_options_html = '<option value="">— (domyślny)</option>' + "".join(
        f'<option value="{d}" {"selected" if d == wfirma_document_type else ""}>{d}</option>'
        for d in WFIRMA_DOC_TYPES
    )

    body = f"""
    <div style="margin-bottom:12px;">
      <a class="btn" href="{url_for('admin_bp.payment_rules_list', event_id=event_id, token=token)}">← Wróć do listy reguł</a>
    </div>

    <div class="card" style="margin-bottom:16px;">
      <div style="font-weight:700;">{event_name}</div>
      <div class="muted"><code>{event_id}</code></div>
    </div>

    <div class="grid">
      <div class="card">
        <div style="font-weight:700; margin-bottom:10px;">{'Nowa reguła' if is_new else 'Edytuj regułę'}</div>
        <form method="post" action="{url_for('admin_bp.payment_rule_save', event_id=event_id)}">
          <input type="hidden" name="token" value="{token}" />
          <input type="hidden" name="rule_id" value="{rule_id}" />

          <div class="muted">Flow (typ przepływu) *</div>
          <select name="flow" style="width:100%; padding:10px; border-radius:8px; border:1px solid #ccc;">
            <option value="">— wybierz —</option>
            {flow_options_html}
          </select>
          <div class="formHint">
            <b>FOC</b> = Free of Charge (darmowe, tylko mail)<br/>
            <b>PROFORMA</b> = wystawiamy proformę w wFirma, czekamy na przelew<br/>
            <b>STRIPE</b> = generujemy link do płatności online
          </div>
          <div style="height:14px;"></div>

          <div class="muted">Dopasowanie: payment_option_name zawiera</div>
          <input type="text" name="payment_option_name_pattern" value="{payment_option_name_pattern}" placeholder="np. Pro-forma lub online" />
          <div class="formHint">Jeśli nazwa opcji płatności (z Backstage) zawiera ten tekst → reguła pasuje.</div>
          <div style="height:10px;"></div>

          <div class="muted">Dopasowanie: payment_type (opcjonalnie)</div>
          <input type="text" name="payment_type" value="{payment_type}" placeholder="np. 4" />
          <div class="formHint">Dokładna wartość payment_type z Backstage (liczbowa).</div>
          <div style="height:10px;"></div>

          <div>
            <label>
              <input type="checkbox" name="is_default" {"checked" if is_default else ""} />
              Reguła domyślna (fallback)
            </label>
          </div>
          <div class="formHint">Użyta gdy żadna inna reguła nie pasuje.</div>
          <div style="height:14px;"></div>

          <div style="border-top:1px solid #eee; padding-top:14px; margin-top:10px;">
            <div class="muted" style="font-weight:700;">Ustawienia wFirma (dla PROFORMA / STRIPE)</div>
          </div>
          <div style="height:10px;"></div>

          <div class="muted">wfirma_company</div>
          <input type="text" name="wfirma_company" value="{wfirma_company}" placeholder="np. md lub test" />
          <div class="formHint">Który zestaw tokenów wFirma (md/test/md_test).</div>
          <div style="height:10px;"></div>

          <div class="muted">wfirma_series_name</div>
          <input type="text" name="wfirma_series_name" value="{wfirma_series_name}" placeholder="np. FV/2026" />
          <div class="formHint">Seria numeracji faktury/proformy.</div>
          <div style="height:10px;"></div>

          <div class="muted">wfirma_document_type</div>
          <select name="wfirma_document_type" style="width:100%; padding:10px; border-radius:8px; border:1px solid #ccc;">
            {doc_type_options_html}
          </select>
          <div class="formHint">Typ dokumentu: proforma / normal / proforma_bill.</div>
          <div style="height:10px;"></div>

          <div class="muted">wfirma_payment_due_days</div>
          <input type="text" name="wfirma_payment_due_days" value="{wfirma_payment_due_days}" placeholder="np. 14" />
          <div class="formHint">Termin płatności w dniach.</div>
          <div style="height:14px;"></div>

          <button class="btn btnPrimary" type="submit">Zapisz</button>
        </form>
      </div>

      <div class="card">
        <div style="font-weight:700; margin-bottom:10px;">Instrukcja</div>
        <div class="muted">
          <b>Jak działa routing płatności?</b><br/><br/>
          1. Jeśli <code>total = 0</code> → zawsze <b>FOC</b><br/>
          2. Dopasuj regułę:<br/>
          &nbsp;&nbsp;• najpierw po <code>payment_option_name</code><br/>
          &nbsp;&nbsp;• potem po <code>payment_type</code><br/>
          3. Jeśli brak dopasowania → reguła domyślna<br/><br/>
          <b>Typowa konfiguracja:</b><br/>
          • Reguła 1: pattern = <code>Pro-forma</code> → flow = <code>PROFORMA</code><br/>
          • Reguła 2: pattern = <code>online</code> → flow = <code>STRIPE</code><br/>
          • Reguła 3: domyślna → flow = <code>STRIPE</code> (fallback)
        </div>
      </div>
    </div>
    """
    return _page("Reguła płatności", body)


# ---------------------------------------------------------------------------
# ORDERS MANAGEMENT
# ---------------------------------------------------------------------------

ORDER_STATUS_LABELS = {
    "received": ("Otrzymane", "background:#f3f4f6;"),
    "pending_payment": ("Oczekuje na płatność", "background:#fff8e1;"),
    "paid": ("Opłacone", "background:#ecfdf3;"),
    "failed": ("Błąd", "background:#fff5f5;"),
    "cancelled": ("Anulowane", "background:#f3f4f6;"),
}


@admin_bp.route("/orders", methods=["GET"])
def orders_list():
    """Lista zamówień z filtrowaniem."""
    token = _require_admin_token()

    # Filtrowanie
    status_filter = (request.args.get("status") or "").strip()
    event_filter = (request.args.get("event_id") or "").strip()

    orders = list_orders(
        event_id=event_filter or None,
        status=status_filter or None,
        limit=200,
    )

    # Pobierz listę eventów do filtrowania
    events = list_events(limit=100)
    event_options = "".join(
        f'<option value="{e.get("event_id", "")}" {"selected" if e.get("event_id") == event_filter else ""}>{e.get("event_name", "")}</option>'
        for e in events
    )

    status_options = "".join(
        f'<option value="{s}" {"selected" if s == status_filter else ""}>{label}</option>'
        for s, (label, _) in ORDER_STATUS_LABELS.items()
    )

    rows = []
    for o in orders:
        status = o.get("status", "received")
        label, style = ORDER_STATUS_LABELS.get(status, ("?", ""))
        total = o.get("total") or 0
        currency = o.get("currency", "PLN")

        rows.append(f"""
            <tr>
              <td><a href="{url_for('admin_bp.order_detail', order_id=o.get('event_order_id', ''), token=token)}"><code>{o.get('event_order_id', '')[:16]}...</code></a></td>
              <td>{o.get('purchaser_email', '') or '—'}</td>
              <td>{o.get('purchaser_first_name', '')} {o.get('purchaser_last_name', '')}</td>
              <td style="text-align:right;">{total:.2f} {currency}</td>
              <td><span class="pill" style="{style}">{label}</span></td>
              <td class="muted">{str(o.get('created_at', ''))[:16]}</td>
            </tr>
        """)

    body = f"""
    <div style="margin-bottom:12px;">
      <a class="btn" href="{url_for('admin_bp.events_list', token=token)}">← Lista wydarzeń</a>
    </div>

    <div class="card" style="margin-bottom:16px;">
      <form method="get" action="{url_for('admin_bp.orders_list')}" style="display:flex; gap:10px; flex-wrap:wrap; align-items:end;">
        <input type="hidden" name="token" value="{token}" />
        <div>
          <div class="muted">Status</div>
          <select name="status" style="padding:8px; border-radius:6px; border:1px solid #ccc;">
            <option value="">— wszystkie —</option>
            {status_options}
          </select>
        </div>
        <div>
          <div class="muted">Wydarzenie</div>
          <select name="event_id" style="padding:8px; border-radius:6px; border:1px solid #ccc;">
            <option value="">— wszystkie —</option>
            {event_options}
          </select>
        </div>
        <button class="btn" type="submit">Filtruj</button>
        <a class="btn" href="{url_for('admin_bp.orders_list', token=token)}">Wyczyść</a>
      </form>
    </div>

    <div class="card">
      <table style="width:100%; border-collapse:collapse; font-size:14px;">
        <thead>
          <tr style="border-bottom:2px solid #eee;">
            <th style="text-align:left; padding:8px;">ID</th>
            <th style="text-align:left; padding:8px;">Email</th>
            <th style="text-align:left; padding:8px;">Nabywca</th>
            <th style="text-align:right; padding:8px;">Kwota</th>
            <th style="text-align:left; padding:8px;">Status</th>
            <th style="text-align:left; padding:8px;">Data</th>
          </tr>
        </thead>
        <tbody>
          {''.join(rows) if rows else '<tr><td colspan="6" class="muted" style="padding:20px; text-align:center;">Brak zamówień</td></tr>'}
        </tbody>
      </table>
    </div>
    """
    return _page("Zamówienia", body)


@admin_bp.route("/orders/<order_id>", methods=["GET"])
def order_detail(order_id: str):
    """Szczegóły zamówienia."""
    token = _require_admin_token()

    order = get_order(order_id)
    if not order:
        abort(404, description="Nie znaleziono zamówienia")

    status = order.get("status", "received")
    label, style = ORDER_STATUS_LABELS.get(status, ("?", ""))
    total = order.get("total") or 0
    currency = order.get("currency", "PLN")
    event_id = order.get("event_id", "")

    # Pobierz event
    ev = get_event(event_id) if event_id else None
    event_name = ev.get("event_name", "") if ev else ""

    # Pobierz dokumenty wFirma
    wfirma_docs = get_wfirma_documents(order_id)
    docs_html = ""
    if wfirma_docs:
        docs_rows = "".join(
            f"<tr><td>{d.get('document_type', '')}</td><td><code>{d.get('wfirma_number', '')}</code></td><td>{d.get('status', '')}</td></tr>"
            for d in wfirma_docs
        )
        docs_html = f"""
        <div style="margin-top:16px;">
          <div class="muted" style="font-weight:700; margin-bottom:8px;">Dokumenty wFirma</div>
          <table style="width:100%; border-collapse:collapse; font-size:13px;">
            <tr style="border-bottom:1px solid #eee;"><th style="text-align:left;">Typ</th><th style="text-align:left;">Numer</th><th style="text-align:left;">Status</th></tr>
            {docs_rows}
          </table>
        </div>
        """

    # Przycisk "Oznacz jako opłacone" tylko dla pending_payment
    mark_paid_form = ""
    if status == "pending_payment":
        mark_paid_form = f"""
        <div style="margin-top:16px; padding-top:16px; border-top:1px solid #eee;">
          <form method="post" action="{url_for('admin_bp.order_mark_paid', order_id=order_id)}" onsubmit="return confirm('Oznaczyć zamówienie jako opłacone? Zostanie wygenerowana faktura VAT.');">
            <input type="hidden" name="token" value="{token}" />
            <button class="btn btnPrimary" type="submit">Oznacz jako opłacone</button>
            <span class="muted" style="margin-left:10px;">Po kliknięciu: status → paid, wygenerowany mail task do faktury</span>
          </form>
        </div>
        """

    body = f"""
    <div style="margin-bottom:12px;">
      <a class="btn" href="{url_for('admin_bp.orders_list', token=token)}">← Lista zamówień</a>
      {'<a class="btn" href="' + url_for('admin_bp.event_edit', event_id=event_id, token=token) + '">Wydarzenie</a>' if event_id else ''}
    </div>

    <div class="card" style="margin-bottom:16px;">
      <div style="display:flex; justify-content:space-between; align-items:start;">
        <div>
          <div style="font-weight:700;">Zamówienie</div>
          <div class="muted"><code>{order_id}</code></div>
        </div>
        <div>
          <span class="pill" style="{style}">{label}</span>
        </div>
      </div>
    </div>

    <div class="grid">
      <div class="card">
        <div style="font-weight:700; margin-bottom:10px;">Dane nabywcy</div>
        <div class="kv">
          <div class="muted">Email</div><div>{order.get('purchaser_email', '') or '—'}</div>
          <div class="muted">Imię</div><div>{order.get('purchaser_first_name', '') or '—'}</div>
          <div class="muted">Nazwisko</div><div>{order.get('purchaser_last_name', '') or '—'}</div>
          <div class="muted">Telefon</div><div>{order.get('purchaser_phone', '') or '—'}</div>
          <div class="muted">NIP</div><div>{order.get('purchaser_nip', '') or '—'}</div>
        </div>
      </div>

      <div class="card">
        <div style="font-weight:700; margin-bottom:10px;">Płatność</div>
        <div class="kv">
          <div class="muted">Kwota</div><div><b>{total:.2f} {currency}</b></div>
          <div class="muted">Opcja płatności</div><div>{order.get('payment_option_name', '') or '—'}</div>
          <div class="muted">Kod promocyjny</div><div>{order.get('promo_code', '') or '—'}</div>
          <div class="muted">Wydarzenie</div><div>{event_name or '—'} <code class="muted">{event_id}</code></div>
        </div>
        {docs_html}
        {mark_paid_form}
      </div>
    </div>
    """
    return _page("Szczegóły zamówienia", body)


@admin_bp.route("/orders/<order_id>/mark-paid", methods=["POST"])
def order_mark_paid(order_id: str):
    """Oznacza zamówienie jako opłacone (dla proform)."""
    token = _require_admin_token()

    order = get_order(order_id)
    if not order:
        abort(404, description="Nie znaleziono zamówienia")

    # Aktualizuj status
    update_order_status(order_id, "paid")

    # Pobierz dane eventu
    event_id = order.get("event_id", "")
    ev = get_event(event_id) if event_id else None
    event_name = ev.get("event_name", "") if ev else ""
    event_data = ev.get("data", {}) if ev else {}

    # Zapisz mail task do logu (Make może go pobrać)
    from pg_storage import save_mail_log

    purchaser_email = order.get("purchaser_email", "")
    if purchaser_email:
        save_mail_log(
            event_order_id=order_id,
            direction="purchaser",
            template_key="payment_confirmation",
            to_email=purchaser_email,
            subject=f"Potwierdzenie płatności – {event_name}",
            data={
                "event_order_id": order_id,
                "event_name": event_name,
                "purchaser_name": f"{order.get('purchaser_first_name', '')} {order.get('purchaser_last_name', '')}".strip(),
                "purchaser_email": purchaser_email,
                "total": order.get("total", 0),
                "currency": order.get("currency", "PLN"),
                "payment_method": "Przelew (proforma)",
                **event_data,
            },
        )

    # Mail wewnętrzny
    internal_email = event_data.get("md_email_techniczny") or event_data.get("md_email_kontakt")
    if internal_email:
        save_mail_log(
            event_order_id=order_id,
            direction="internal",
            template_key="internal_order_paid",
            to_email=internal_email,
            subject=f"[PAID] Zamówienie opłacone – {event_name}",
            data={
                "event_order_id": order_id,
                "event_name": event_name,
                "purchaser_email": purchaser_email,
                "total": order.get("total", 0),
                "currency": order.get("currency", "PLN"),
                "payment_method": "Przelew (proforma)",
            },
        )

    return redirect(url_for("admin_bp.order_detail", order_id=order_id, token=token))


@admin_bp.errorhandler(401)
@admin_bp.errorhandler(403)
@admin_bp.errorhandler(404)
@admin_bp.errorhandler(500)
def _err(e):
    token = (request.args.get("token") or "").strip()
    back = ""
    if token:
        back = f'<p><a class="btn" href="{url_for("admin_bp.events_list", token=token)}">Lista wydarzeń</a></p>'
    body = f'<div class="error"><b>{getattr(e, "code", 500)}</b> {getattr(e, "description", str(e))}</div>{back}'
    return _page("Błąd", body), getattr(e, "code", 500)

