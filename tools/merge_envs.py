"""
Merge multiple .env-style files into one output file.

Goals:
- Safe-by-default reporting (no secrets printed unless explicitly requested)
- Deterministic merging (default: last file wins)
- Optional rule for wFirma refresh tokens: pick the pair (token + expires) with the newest expires timestamp,
  regardless of file order. Disabled by default (so order decides).

Usage (PowerShell examples):
  python tools/merge_envs.py --out ".env.merged" --report "merge_report.json" ^
    "wfirma-api.env" "UPDATED_VERY.env" "wfirma-api (2).env" "wfirma-api (1).env"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple


LINE_RE = re.compile(r"^\s*(?:export\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.*)\s*$")


@dataclass(frozen=True)
class Source:
    path: str
    line_no: int


def _parse_int(value: str) -> Optional[int]:
    v = value.strip().strip('"').strip("'")
    if not v:
        return None
    try:
        return int(v)
    except ValueError:
        return None


def _redact(value: str) -> str:
    # Avoid leaking secrets in logs/reports by default.
    # Keep only length and tiny prefix/suffix for debugging.
    raw = value.rstrip("\n")
    if raw == "":
        return "<empty>"
    show = 3
    if len(raw) <= show * 2:
        return f"<len:{len(raw)}>"
    return f"{raw[:show]}…{raw[-show:]} (len:{len(raw)})"


def _strip_wrapping_quotes(value: str) -> str:
    v = value.strip()
    if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
        return v[1:-1]
    return value


def parse_env_lines(
    raw_lines: List[str],
    *,
    source_name: str,
    strip_wrapping_quotes: bool = False,
) -> Tuple[Dict[str, str], Dict[str, Source], List[str]]:
    """
    Parse .env-style lines.

    Returns: (data, sources, warnings)
    """
    data: Dict[str, str] = {}
    sources: Dict[str, Source] = {}
    warnings: List[str] = []

    for idx, raw in enumerate(raw_lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = LINE_RE.match(raw)
        if not m:
            # Skip lines we don't understand (e.g. multiline values); report will note it.
            if "=" in raw:
                warnings.append(f"Unparsed line {idx}: {raw}")
            continue
        key = m.group("key")
        value = m.group("value")
        if strip_wrapping_quotes:
            value = _strip_wrapping_quotes(value)
        data[key] = value
        sources[key] = Source(path=source_name, line_no=idx)

    return data, sources, warnings


def read_env_file(path: str, *, strip_wrapping_quotes: bool = False) -> Tuple[Dict[str, str], List[str], Dict[str, Source], List[str]]:
    """
    Returns: (data, raw_lines, sources, warnings)
    """
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        raw_lines = f.read().splitlines()
    data, sources, warnings = parse_env_lines(
        raw_lines,
        source_name=path,
        strip_wrapping_quotes=strip_wrapping_quotes,
    )
    return data, raw_lines, sources, warnings


def merge_envs(
    file_paths: List[str],
    prefer_wfirma_newest_refresh: bool = False,
    strip_wrapping_quotes: bool = False,
) -> Tuple[Dict[str, str], Dict[str, List[Tuple[str, Source]]], Dict[str, List[str]]]:
    """
    Returns:
      - merged key->value (raw value string)
      - history: key -> list of (value, source) in encounter order
      - parse_warnings: path -> list of warnings (e.g. unparsed lines)
    """
    merged: Dict[str, str] = {}
    history: Dict[str, List[Tuple[str, Source]]] = {}
    parse_warnings: Dict[str, List[str]] = {}

    wfirma_best: Optional[Tuple[int, str, str, Source, Source]] = None
    # (expires_int, refresh_token_value, refresh_expires_value, token_src, expires_src)

    for path in file_paths:
        env, raw_lines, sources, warnings = read_env_file(path, strip_wrapping_quotes=strip_wrapping_quotes)

        if warnings:
            parse_warnings[path] = warnings

        # Default merge: last file wins
        for k, v in env.items():
            src = sources.get(k, Source(path=path, line_no=0))
            history.setdefault(k, []).append((v, src))
            merged[k] = v

        # Special wFirma rule: pick newest refresh token pair by *_EXPIRES
        if prefer_wfirma_newest_refresh:
            rt = env.get("WFIRMA_MD_REFRESH_TOKEN")
            rte = env.get("WFIRMA_MD_REFRESH_TOKEN_EXPIRES")
            if rt is not None and rte is not None:
                expires_int = _parse_int(rte)
                if expires_int is not None:
                    rt_src = sources.get("WFIRMA_MD_REFRESH_TOKEN", Source(path=path, line_no=0))
                    rte_src = sources.get("WFIRMA_MD_REFRESH_TOKEN_EXPIRES", Source(path=path, line_no=0))
                    candidate = (expires_int, rt, rte, rt_src, rte_src)
                    if wfirma_best is None or candidate[0] > wfirma_best[0]:
                        wfirma_best = candidate

    if prefer_wfirma_newest_refresh and wfirma_best is not None:
        expires_int, rt, rte, rt_src, rte_src = wfirma_best
        merged["WFIRMA_MD_REFRESH_TOKEN"] = rt
        merged["WFIRMA_MD_REFRESH_TOKEN_EXPIRES"] = rte

    return merged, history, parse_warnings


def _unix_to_iso(ts: Optional[int]) -> Optional[str]:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def write_env_file(path: str, merged: Dict[str, str], sort_keys: bool) -> None:
    keys = sorted(merged.keys()) if sort_keys else list(merged.keys())
    with open(path, "w", encoding="utf-8") as f:
        for k in keys:
            f.write(f"{k}={merged[k]}\n")


def build_report(
    file_paths: List[str],
    merged: Dict[str, str],
    history: Dict[str, List[Tuple[str, Source]]],
    parse_warnings: Dict[str, List[str]],
    show_values: bool,
) -> dict:
    conflicts = {}
    for k, items in history.items():
        unique_vals = []
        for v, _src in items:
            if v not in unique_vals:
                unique_vals.append(v)
        if len(unique_vals) > 1:
            conflicts[k] = {
                "variants": [
                    {
                        "value": v if show_values else _redact(v),
                        "sources": [
                            {"path": src.path, "line": src.line_no}
                            for vv, src in items
                            if vv == v
                        ],
                    }
                    for v in unique_vals
                ],
                "chosen": merged.get(k) if show_values else _redact(merged.get(k, "")),
            }

    wfirma_refresh_token = merged.get("WFIRMA_MD_REFRESH_TOKEN")
    wfirma_expires = _parse_int(merged.get("WFIRMA_MD_REFRESH_TOKEN_EXPIRES", ""))
    wfirma_refresh_token_sources = [
        {"path": src.path, "line": src.line_no}
        for v, src in history.get("WFIRMA_MD_REFRESH_TOKEN", [])
        if wfirma_refresh_token is not None and v == wfirma_refresh_token
    ]
    wfirma_refresh_expires_sources = [
        {"path": src.path, "line": src.line_no}
        for v, src in history.get("WFIRMA_MD_REFRESH_TOKEN_EXPIRES", [])
        if wfirma_expires is not None and _parse_int(v) == wfirma_expires
    ]
    return {
        "inputs": [os.path.abspath(p) for p in file_paths],
        "output_keys": len(merged),
        "conflict_keys": len(conflicts),
        "conflicts": conflicts,
        "parse_warnings": parse_warnings,
        "wfirma": {
            "refresh_token_present": "WFIRMA_MD_REFRESH_TOKEN" in merged,
            "refresh_token_sources": wfirma_refresh_token_sources,
            "refresh_expires": wfirma_expires,
            "refresh_expires_utc": _unix_to_iso(wfirma_expires),
            "refresh_expires_sources": wfirma_refresh_expires_sources,
        },
    }


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Merge .env files into one output file.")
    p.add_argument(
        "files",
        nargs="+",
        help="Input .env files in the desired precedence order (default: last wins).",
    )
    p.add_argument("--out", default=".env.merged", help="Output file path (default: .env.merged).")
    p.add_argument(
        "--report",
        default="merge_report.json",
        help="Write JSON report here (default: merge_report.json).",
    )
    p.add_argument(
        "--sort-keys",
        action="store_true",
        help="Sort keys alphabetically in output (default: keep insertion order).",
    )
    p.add_argument(
        "--wfirma-newest-by-expires",
        action="store_true",
        help="Pick newest WFIRMA refresh token by *_EXPIRES (overrides file order).",
    )
    p.add_argument(
        "--strip-quotes",
        action="store_true",
        help="Strip wrapping single/double quotes from values (e.g. KEY=\"x\" -> KEY=x).",
    )
    p.add_argument(
        "--show-values-in-report",
        action="store_true",
        help="DANGEROUS: include raw values in report JSON. Default: redacted.",
    )
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    missing = [p for p in args.files if not os.path.exists(p)]
    if missing:
        print("ERROR: Missing files:", file=sys.stderr)
        for p in missing:
            print(f"- {p}", file=sys.stderr)
        return 2

    merged, history, parse_warnings = merge_envs(
        file_paths=args.files,
        prefer_wfirma_newest_refresh=args.wfirma_newest_by_expires,
        strip_wrapping_quotes=args.strip_quotes,
    )

    write_env_file(args.out, merged, sort_keys=args.sort_keys)

    report = build_report(
        file_paths=args.files,
        merged=merged,
        history=history,
        parse_warnings=parse_warnings,
        show_values=args.show_values_in_report,
    )
    with open(args.report, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Keep stdout non-secret.
    print(f"OK: wrote {args.out} with {len(merged)} keys")
    print(f"OK: wrote {args.report} (values {'included' if args.show_values_in_report else 'redacted'})")
    if report["conflict_keys"]:
        print(f"NOTE: {report['conflict_keys']} keys had conflicts (see report)")
    if parse_warnings:
        print(f"NOTE: {sum(len(v) for v in parse_warnings.values())} unparsed lines (see report)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

