from __future__ import annotations

import argparse
import io
import json
import re
import zipfile
from typing import List, Tuple

from flask import Flask, Response, render_template_string, request, send_file

from merge_envs import Source, build_report


HTML = r"""
<!doctype html>
<html lang="pl">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Env Merger</title>
    <style>
      body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 24px; }
      .card { max-width: 900px; margin: 0 auto; border: 1px solid #ddd; border-radius: 10px; padding: 18px; }
      .row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
      .row1 { display: grid; grid-template-columns: 1fr; gap: 12px; }
      label { font-weight: 600; display: block; margin-bottom: 6px; }
      input[type="text"], input[type="number"] { width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 8px; }
      .drop { border: 2px dashed #999; border-radius: 10px; padding: 18px; text-align: center; background: #fafafa; }
      .drop.drag { background: #f0f7ff; border-color: #3b82f6; }
      .small { color: #555; font-size: 13px; line-height: 1.4; }
      .files { margin-top: 10px; font-size: 14px; }
      .files li { margin: 4px 0; }
      .actions { display: flex; gap: 10px; margin-top: 14px; }
      button { padding: 10px 14px; border: 0; border-radius: 9px; cursor: pointer; }
      .primary { background: #111827; color: white; }
      .secondary { background: #e5e7eb; color: #111827; }
      .checks { display: flex; flex-wrap: wrap; gap: 14px; align-items: center; }
      .checks label { font-weight: 500; margin: 0; display: inline-flex; gap: 8px; align-items: center; }
      code { background: #f3f4f6; padding: 2px 6px; border-radius: 6px; }
    </style>
  </head>
  <body>
    <div class="card">
      <h2 style="margin: 0 0 8px;">Env Merger</h2>
      <div class="small">
        - Kolejność plików ma znaczenie: <b>ostatni ma najwyższy priorytet</b> (zakładamy, że dodajesz nowsze pliki jako kolejne).<br/>
        - Opcja wFirma „najnowszy po expires” jest dodatkowa i ignoruje kolejność tylko dla pary refresh token + expires.
      </div>
      <hr style="border:0;border-top:1px solid #eee;margin:14px 0;" />

      <form method="post" action="/merge" enctype="multipart/form-data">
        <div class="row1">
          <div>
            <label>Pliki .env (drag&drop)</label>
            <div id="drop" class="drop">
              Upuść pliki tutaj albo kliknij, żeby wybrać (wiele na raz).
              <div class="small" style="margin-top:8px;">
                Wskazówka: dodawaj pliki w kolejności od starszego do nowszego.
              </div>
              <input id="files" name="files" type="file" multiple style="display:none" />
            </div>
            <ul id="fileList" class="files"></ul>
          </div>
        </div>

        <div class="row" style="margin-top: 12px;">
          <div>
            <label>Nazwa pliku wynikowego</label>
            <input name="out_name" type="text" value=".env.merged" />
            <div class="small">Zostanie spakowane do ZIP razem z <code>merge_report.json</code>.</div>
          </div>
          <div>
            <label>Nazwa ZIP</label>
            <input name="zip_name" type="text" value="env-merged.zip" />
          </div>
        </div>

        <div class="checks" style="margin-top: 12px;">
          <label><input name="strip_quotes" type="checkbox" checked /> Usuń otaczające cudzysłowy z wartości (np. <code>KEY="x"</code> → <code>KEY=x</code>)</label>
          <label><input name="sort_keys" type="checkbox" /> Sortuj klucze alfabetycznie</label>
          <label><input name="wfirma_newest_by_expires" type="checkbox" /> wFirma: wybierz refresh token po największym <code>WFIRMA_MD_REFRESH_TOKEN_EXPIRES</code></label>
        </div>

        <div class="actions">
          <button class="primary" type="submit">Scal i pobierz ZIP</button>
          <button class="secondary" type="button" id="clear">Wyczyść</button>
        </div>
      </form>
    </div>

    <script>
      const drop = document.getElementById('drop');
      const input = document.getElementById('files');
      const list = document.getElementById('fileList');
      const clearBtn = document.getElementById('clear');

      function renderList(files) {
        list.innerHTML = '';
        if (!files || files.length === 0) return;
        [...files].forEach((f, i) => {
          const li = document.createElement('li');
          li.textContent = `${i+1}. ${f.name} (${Math.round(f.size/1024)} KB)`;
          list.appendChild(li);
        });
      }

      function setFiles(fileList) {
        // fileList is a FileList - we need to rebuild it via DataTransfer
        const dt = new DataTransfer();
        [...fileList].forEach(f => dt.items.add(f));
        input.files = dt.files;
        renderList(input.files);
      }

      drop.addEventListener('click', () => input.click());

      input.addEventListener('change', () => renderList(input.files));

      drop.addEventListener('dragover', (e) => {
        e.preventDefault();
        drop.classList.add('drag');
      });
      drop.addEventListener('dragleave', () => drop.classList.remove('drag'));
      drop.addEventListener('drop', (e) => {
        e.preventDefault();
        drop.classList.remove('drag');
        if (e.dataTransfer && e.dataTransfer.files) setFiles(e.dataTransfer.files);
      });

      clearBtn.addEventListener('click', () => {
        input.value = '';
        list.innerHTML = '';
      });
    </script>
  </body>
</html>
"""


def _safe_filename(name: str, default: str) -> str:
    n = (name or "").strip()
    if not n:
        return default
    # forbid path separators and weird control chars
    n = re.sub(r"[\\/\x00-\x1f\x7f]+", "_", n)
    return n


def _merge_uploaded_files(
    uploads: List[Tuple[str, bytes]],
    *,
    wfirma_newest_by_expires: bool,
    strip_quotes: bool,
) -> Tuple[str, dict]:
    """
    Merge by order of uploads (last wins). We implement this by writing to temp files? No:
    We reuse the existing merge logic by parsing each file in memory and applying the same merging rules.
    """
    # Minimal re-implementation using merge_envs.py primitives would duplicate code;
    # easiest/cleanest: write temp files is avoided, but merge_envs() currently expects paths.
    # We'll create temporary files *in memory* by using NamedTemporaryFile? Windows + Flask makes delete tricky.
    # So we do the merge ourselves here with the same rules as merge_envs().

    from merge_envs import _parse_int, parse_env_lines  # local import to keep API small

    merged = {}
    history = {}
    parse_warnings = {}

    wfirma_best = None  # (expires_int, rt, rte, rt_src, rte_src)

    for name, content in uploads:
        text = content.decode("utf-8", errors="replace")
        raw_lines = text.splitlines()
        env, sources, warnings = parse_env_lines(raw_lines, source_name=name, strip_wrapping_quotes=strip_quotes)
        if warnings:
            parse_warnings[name] = warnings

        for k, v in env.items():
            src = sources.get(k, Source(path=name, line_no=0))
            history.setdefault(k, []).append((v, src))
            merged[k] = v

        if wfirma_newest_by_expires:
            rt = env.get("WFIRMA_MD_REFRESH_TOKEN")
            rte = env.get("WFIRMA_MD_REFRESH_TOKEN_EXPIRES")
            if rt is not None and rte is not None:
                expires_int = _parse_int(rte)
                if expires_int is not None:
                    rt_src = sources.get("WFIRMA_MD_REFRESH_TOKEN", Source(path=name, line_no=0))
                    rte_src = sources.get("WFIRMA_MD_REFRESH_TOKEN_EXPIRES", Source(path=name, line_no=0))
                    cand = (expires_int, rt, rte, rt_src, rte_src)
                    if wfirma_best is None or cand[0] > wfirma_best[0]:
                        wfirma_best = cand

    if wfirma_newest_by_expires and wfirma_best is not None:
        _expires_int, rt, rte, _rt_src, _rte_src = wfirma_best
        merged["WFIRMA_MD_REFRESH_TOKEN"] = rt
        merged["WFIRMA_MD_REFRESH_TOKEN_EXPIRES"] = rte

    merged_text = "".join(f"{k}={v}\n" for k, v in merged.items())

    # Build report using existing helper (redacted by default)
    report = build_report(
        file_paths=[name for name, _ in uploads],
        merged=merged,
        history=history,
        parse_warnings=parse_warnings,
        show_values=False,
    )
    report["ui"] = {
        "assumption": "last file wins (newer files appended later)",
        "strip_quotes": strip_quotes,
        "wfirma_newest_by_expires": wfirma_newest_by_expires,
        "last_input_file": (uploads[-1][0] if uploads else None),
    }

    return merged_text, report


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index() -> str:
        return render_template_string(HTML)

    @app.post("/merge")
    def merge_route() -> Response:
        files = request.files.getlist("files")
        if not files:
            return Response("Brak plików. Wróć i dodaj pliki.", status=400, mimetype="text/plain")

        uploads: List[Tuple[str, bytes]] = []
        for f in files:
            # filename is user-supplied; keep it for display only.
            name = f.filename or "unknown.env"
            uploads.append((name, f.read()))

        out_name = _safe_filename(request.form.get("out_name", ""), ".env.merged")
        zip_name = _safe_filename(request.form.get("zip_name", ""), "env-merged.zip")
        strip_quotes = bool(request.form.get("strip_quotes"))
        sort_keys = bool(request.form.get("sort_keys"))
        wfirma_newest_by_expires = bool(request.form.get("wfirma_newest_by_expires"))

        merged_text, report = _merge_uploaded_files(
            uploads,
            wfirma_newest_by_expires=wfirma_newest_by_expires,
            strip_quotes=strip_quotes,
        )

        if sort_keys:
            # Sort keys in merged output (reparse, sort, rebuild)
            lines = [ln for ln in merged_text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
            kv = []
            for ln in lines:
                if "=" not in ln:
                    continue
                k, v = ln.split("=", 1)
                kv.append((k, v))
            kv.sort(key=lambda x: x[0])
            merged_text = "".join(f"{k}={v}\n" for k, v in kv)

        # Build ZIP in-memory
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr(out_name, merged_text)
            z.writestr("merge_report.json", json.dumps(report, ensure_ascii=False, indent=2))
            z.writestr("merge_order.txt", "\n".join([name for name, _ in uploads]) + "\n")
        buf.seek(0)

        return send_file(
            buf,
            mimetype="application/zip",
            as_attachment=True,
            download_name=zip_name,
            max_age=0,
        )

    return app


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Small UI (Flask) to merge .env files.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5055)
    p.add_argument("--debug", action="store_true")
    args = p.parse_args(argv)

    app = create_app()
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

