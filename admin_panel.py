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
    if bilety_records:
        by_event: Dict[str, List[Dict[str, Any]]] = {}
        for r in bilety_records:
            eid = (r.get("eventId") or "").strip()
            if not eid:
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

    body = f"""
    <div class="ok"><b>Import zakończony.</b></div>
    <div style="height:10px;"></div>
    <div class="card">
      <div class="kv">
        <div class="muted">Zaimportowane eventy</div><div><b>{imported_events}</b></div>
        <div class="muted">Zaimportowane klasy biletów</div><div><b>{imported_ticket_classes}</b></div>
      </div>
    </div>
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
    if event_id:
        preview_link = f'<a class="btn" href="{url_for("admin_bp.event_preview", event_id=event_id, token=token)}">Podgląd</a>'

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

