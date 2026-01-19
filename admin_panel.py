import json
import os
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


@admin_bp.route("/events/<event_id>/preview", methods=["GET"])
def event_preview(event_id: str):
    token = _require_admin_token()
    ev = get_event(event_id)
    if not ev:
        abort(404, description="Nie znaleziono eventu")

    data = ev.get("data") or {}
    if not isinstance(data, dict):
        data = {}

    def _url(k: str) -> str:
        v = (data.get(k) or "").strip()
        return v

    banner = _url("event_mail_link_top_banner") or _url("event_mail_link_bottom_banner")
    logo = _url("event_logo_link") or _url("event_logo_link_white") or _url("event_logo_link_color")
    color1 = (data.get("color_gradient_1") or "").strip()
    color2 = (data.get("color_gradient_2") or "").strip()

    important = [
        ("eventName", data.get("eventName")),
        ("eventId", data.get("eventId") or ev.get("event_id")),
        ("url_event", _url("url_event")),
        ("url_success", _url("url_success")),
        ("url_cancel", _url("url_cancel")),
        ("event_orders_link", _url("event_orders_link")),
        ("event_attendees_link", _url("event_attendees_link")),
        ("event_config_link", _url("event_config_link")),
        ("md_email_kontakt", data.get("md_email_kontakt")),
        ("md_email_techniczny", data.get("md_email_techniczny")),
        ("event_location_place", data.get("event_location_place")),
        ("event_location_address", data.get("event_location_address")),
        ("event_location_zip", data.get("event_location_zip")),
        ("event_location_city", data.get("event_location_city")),
        ("event_day_text_1", data.get("event_day_text_1")),
        ("event_time_text", data.get("event_time_text")),
    ]

    kv_html = "".join(
        f"<div class='muted'>{k}</div><div>{(v or '—')}</div>"
        for (k, v) in important
    )

    warn = ""
    if banner and not banner.startswith("http"):
        warn += "<div class='warn'>Top banner wygląda podejrzanie (brak http/https).</div>"
    if logo and not logo.startswith("http"):
        warn += "<div class='warn'>Logo wygląda podejrzanie (brak http/https).</div>"

    body = f"""
    <div style="margin-bottom:12px;">
      <a class="btn" href="{url_for('admin_bp.event_edit', event_id=event_id, token=token)}">← Wróć do edycji</a>
      <a class="btn" href="{url_for('admin_bp.events_list', token=token)}">Lista wydarzeń</a>
    </div>
    {warn}
    <div class="card">
      <div style="font-weight:700; font-size:18px;">{ev.get('event_name','')}</div>
      <div class="muted"><code>{ev.get('event_id','')}</code></div>
    </div>
    <div class="grid" style="margin-top:16px;">
      <div class="card">
        <div style="font-weight:700; margin-bottom:10px;">Podgląd (baner/logo/kolory)</div>
        <div class="banner">
          {'<img src="'+banner+'" alt="banner" />' if banner else '<div class="muted" style="padding:12px;">Brak event_mail_link_top_banner</div>'}
        </div>
        <div style="margin-top:10px; display:flex; gap:12px; align-items:center;">
          <div style="width:72px; height:72px; border:1px solid #eee; border-radius:12px; overflow:hidden;">
            {'<img src="'+logo+'" alt="logo" />' if logo else '<div class="muted" style="padding:10px;">Brak logo</div>'}
          </div>
          <div>
            <div class="muted">color_gradient_1 / color_gradient_2</div>
            <div style="display:flex; gap:8px; margin-top:4px;">
              <div style="width:42px;height:26px;border-radius:6px;border:1px solid #eee;background:{color1 or '#fff'}"></div>
              <div style="width:42px;height:26px;border-radius:6px;border:1px solid #eee;background:{color2 or '#fff'}"></div>
            </div>
          </div>
        </div>
      </div>

      <div class="card">
        <div style="font-weight:700; margin-bottom:10px;">Najważniejsze pola (sanity-check)</div>
        <div class="kv">{kv_html}</div>
      </div>
    </div>
    """
    return _page("Podgląd wydarzenia", body)


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

          <div class="muted">data_json (pełny JSON – jeśli wolisz)</div>
          <textarea name="data_json">{data_json}</textarea>

          <div style="height:10px;"></div>
          <div class="muted">Szybkie wklejenie (key TAB value / key: value). Nadpisuje/uzupełnia data_json.</div>
          <textarea name="kv_paste" placeholder="event_location_place<TAB>Regent Warsaw Hotel"></textarea>

          <div style="height:10px;"></div>
          <div class="muted">ticket_classes_json (lista) – opcjonalnie, jeśli chcesz od razu dodać klasy biletów</div>
          <textarea name="ticket_classes_json">{ticket_classes_json}</textarea>

          <div style="height:14px;"></div>
          <button class="btn btnPrimary" type="submit">Zapisz</button>
        </form>
      </div>

      <div class="card">
        <div style="font-weight:700; margin-bottom:10px;">Podpowiedź pól (pod maile)</div>
        <div class="muted">Najczęściej używane w HTML-ach z Make (Twoje pliki w <code>HTML/</code>):</div>
        <ul>
          <li><code>event_mail_link_top_banner</code>, <code>event_logo_link</code></li>
          <li><code>url_event</code>, <code>url_success</code>, <code>url_cancel</code></li>
          <li><code>event_orders_link</code>, <code>event_attendees_link</code>, <code>event_config_link</code></li>
          <li><code>color_gradient_1</code>, <code>color_gradient_2</code>, <code>color_gradient_angle</code></li>
          <li><code>md_email_kontakt</code>, <code>md_email_techniczny</code>, telefony</li>
          <li>lokalizacja i daty: <code>event_location_*</code>, <code>event_day_text_1</code>, <code>event_time_text</code></li>
        </ul>
        <div class="muted">Po zapisie wejdź w „Podgląd”, żeby upewnić się, że linki i obrazy wyglądają OK.</div>
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

