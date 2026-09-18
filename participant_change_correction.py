"""WO-599C2b2: strict structural corrections, with no I/O or configuration.

Prices are integer cents in the parent's epoch. Provider netto/brutto are
LINE values, never unit prices. A prepared request is not permission to POST:
the portal caller must own a durable committed-start fence.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import math
import re

VERSION = 1
MAX_BODY_BYTES = 1024 * 1024
MAX_POSITIONS = 500
MAX_QUANTITY = 5000
MAX_MONEY = 2**63 - 1
VAT_PERCENT = {"23": 23, "8": 8, "5": 5, "0": 0, "zw": 0, "np": 0}
VAT_IDS = {"222": "23", "223": "8", "224": "5", "225": "0", "226": "zw", "227": "np"}
PARTY_FIELDS = ("role", "name", "tax_id_type", "nip", "street", "zip", "city", "country")
REQUEST_KEYS = frozenset({
    "contract_version", "company", "change_id", "parent", "parent_sha256",
    "issue_date", "series_id", "series_name", "correction_reason", "price_model",
    "currency", "positions", "after_totals",
})
TOTAL_KEYS = frozenset({"net_grosze", "vat_grosze", "gross_grosze"})
SIGNATURE_KEYS = ("name", "unit", "quantity", "unit_price_grosze", "vat_rate_code",
                  "net_grosze", "vat_grosze", "gross_grosze")


class StructuralContractError(ValueError):
    """Stable internal error; never includes provider input or identifiers."""


def _fail(reason="invalid_structural_contract"):
    raise StructuralContractError(reason)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def fingerprint(value):
    return hashlib.sha256(canonical(value)).hexdigest()


# Provider stores id_external truncated to 32 characters (WO-637).
MARKER_LIMIT = 32


def _keys(value, keys):
    return type(value) is dict and all(type(k) is str for k in value) and set(value) == keys


def _text(value, limit=255):
    try:
        return (type(value) is str and bool(value) and value == value.strip()
                and value.isprintable() and len(value.encode("utf-8")) <= limit)
    except UnicodeError:
        return False


def _int(value, limit=MAX_MONEY):
    return type(value) is int and 0 <= value <= limit


def identifier(value):
    """Strict provider numeric identifier; bool and non-canonical strings fail."""
    if type(value) is int and 0 < value < 10**32:
        return str(value)
    if type(value) is str and re.fullmatch(r"[1-9][0-9]{0,31}", value, re.ASCII):
        return value
    _fail()


def _provider_integer(value, limit):
    if type(value) is str and re.fullmatch(r"(?:0|[1-9][0-9]{0,18})", value, re.ASCII):
        value = int(value)
    if not _int(value, limit):
        _fail()
    return value


def _money(value):
    if type(value) not in (int, float, str) or (type(value) is float and not math.isfinite(value)):
        _fail()
    text = str(value)
    if len(text) > 23 or not re.fullmatch(r"(?:0|[1-9][0-9]{0,18})(?:\.[0-9]{1,2})?", text, re.ASCII):
        _fail()
    whole, _, fraction = text.partition(".")
    result = int(whole) * 100 + int((fraction + "00")[:2])
    if result > MAX_MONEY:
        _fail()
    return result


def money_text(cents):
    if not _int(cents):
        _fail()
    return f"{cents // 100}.{cents % 100:02d}"


def line_totals(mode, rate, quantity, price):
    if (type(mode) is not str or mode not in ("netto", "brutto")
            or type(rate) is not str or rate not in VAT_PERCENT
            or not _int(quantity, MAX_QUANTITY) or not _int(price)):
        _fail()
    base = quantity * price
    percent = VAT_PERCENT[rate]
    if mode == "netto":
        net, vat = base, (base * percent + 50) // 100
        gross = net + vat
    else:
        gross = base
        net = (2 * gross * 100 + 100 + percent) // (2 * (100 + percent))
        vat = gross - net
    if gross > MAX_MONEY:
        _fail()
    return {"net_grosze": net, "vat_grosze": vat, "gross_grosze": gross}


def _totals(rows):
    total = {key: sum(row[key] for row in rows) for key in TOTAL_KEYS}
    if any(not _int(value) for value in total.values()):
        _fail()
    return total


def _relation(document, name, *, optional=False):
    values = []
    if name in document:
        node = document[name]
        if type(node) is not dict or "id" not in node:
            _fail()
        values.append(node["id"])
    if name + "_id" in document:
        values.append(document[name + "_id"])
    if not values:
        if optional:
            return None
        _fail()
    normalized = [None if optional and type(v) in (str, int) and v in (0, "0", "")
                  else identifier(v) for v in values]
    if any(value != normalized[0] for value in normalized):
        _fail()
    return normalized[0]


def _party_detail(value):
    if type(value) is not dict or not _text(value.get("name"), 1024):
        _fail("party_snapshot_invalid")
    result = {}
    for key in PARTY_FIELDS:
        item = value.get(key, "")
        if key == "role" and type(item) is int:
            item = str(item)
        if item != "" and not _text(item, 1024):
            _fail("party_snapshot_invalid")
        result[key] = item
    return result


def project_parent(invoice, company_id):
    """Complete bounded projection; any unparsed row invalidates the proof."""
    if type(invoice) is not dict:
        _fail()
    mode = invoice.get("price_type", "netto")  # absent ONLY = documented legacy
    if type(mode) is not str or mode not in ("netto", "brutto") or invoice.get("currency") != "PLN":
        _fail("document_epoch_invalid")
    if invoice.get("type") not in ("normal", "correction"):
        _fail("document_type_invalid")
    if _provider_integer(invoice.get("corrections"), MAX_QUANTITY) != 0:
        _fail("document_is_not_terminal")
    receiver = _relation(invoice, "contractor_receiver", optional=True)
    buyer_detail = _party_detail(invoice.get("contractor_detail"))
    receiver_detail = _party_detail(invoice.get("contractor_detail_receiver")) if receiver else None
    contents = invoice.get("invoicecontents")
    if type(contents) is not dict:
        _fail()
    rows = []
    # Parameters are not positions. No other metadata-shaped omission is allowed.
    for key, entry in contents.items():
        if key == "parameters":
            continue
        if type(key) is not str or not re.fullmatch(r"(?:0|[1-9][0-9]{0,5})", key, re.ASCII):
            _fail()
        if not _keys(entry, {"invoicecontent"}) or type(entry["invoicecontent"]) is not dict:
            _fail()
        content = entry["invoicecontent"]
        if _money(content.get("discount", 0)) != 0 or _money(content.get("discount_percent", 0)) != 0:
            _fail("document_discount_unsupported")
        code = content.get("vat_code")
        if type(code) is not dict:
            _fail()
        rate = VAT_IDS.get(identifier(code.get("id")))
        if rate is None or not _text(content.get("name"), 1024) or not _text(content.get("unit"), 32):
            _fail()
        qty = _provider_integer(content.get("count"), MAX_QUANTITY)
        price = _money(content.get("price"))
        totals = line_totals(mode, rate, qty, price)
        if totals["net_grosze"] != _money(content.get("netto")) or totals["gross_grosze"] != _money(content.get("brutto")):
            _fail("document_line_amount_mismatch")
        rows.append({"position_id": identifier(content.get("id")),
                     "source_parent_id": _relation(content, "parent", optional=True),
                     "name": content["name"], "unit": content["unit"], "quantity": qty,
                     "unit_price_grosze": price, "vat_rate_code": rate, **totals})
        if len(rows) > MAX_POSITIONS:
            _fail()
    if not rows or len({r["position_id"] for r in rows}) != len(rows):
        _fail()
    if "parameters" in contents:
        # Only the provider's exact total-count form is supported here. Unknown
        # pagination metadata must not hide omitted zero-priced positions.
        metadata = contents["parameters"]
        if (not _keys(metadata, {"total"})
                or _provider_integer(metadata["total"], MAX_POSITIONS) != len(rows)):
            _fail("document_positions_incomplete")
    totals = _totals(rows)
    if totals["gross_grosze"] != _money(invoice.get("total_composed")):
        _fail("document_total_mismatch")
    external = invoice.get("id_external", "")
    if external != "" and not _text(external, 160):
        _fail()
    return {
        "contract_version": VERSION, "document_id": identifier(invoice.get("id")),
        "document_type": invoice["type"], "company_id": identifier(company_id),
        "contractor_id": _relation(invoice, "contractor"), "receiver_id": receiver,
        "party_sha256": fingerprint({"buyer": buyer_detail, "receiver": receiver_detail}),
        "price_model": mode, "currency": "PLN", "corrections": 0,
        "source_document_id": _relation(invoice, "parent", optional=True),
        "external_key": external, "positions": sorted(rows, key=lambda r: r["position_id"]),
        "totals": totals,
    }


def validate_request(body):
    if not _keys(body, REQUEST_KEYS) or type(body["contract_version"]) is not int or body["contract_version"] != VERSION:
        _fail()
    if type(body["company"]) is not str or body["company"] not in ("md", "md_test", "test"):
        _fail()
    if not _text(body["change_id"], 160) or not _text(body["series_name"], 128) or not _text(body["correction_reason"], 500):
        _fail()
    if (type(body["parent"]) is not dict or type(body["parent_sha256"]) is not str
            or not re.fullmatch(r"[a-f0-9]{64}", body["parent_sha256"], re.ASCII)):
        _fail()
    if fingerprint(body["parent"]) != body["parent_sha256"] or len(canonical(body)) > MAX_BODY_BYTES:
        _fail()
    if identifier(body["series_id"]) != body["series_id"]:
        _fail()
    if type(body["price_model"]) is not str or body["price_model"] not in ("netto", "brutto") or body["currency"] != "PLN":
        _fail()
    try:
        date = datetime.date.fromisoformat(body["issue_date"])
        if date.isoformat() != body["issue_date"]:
            _fail()
    except (TypeError, ValueError):
        _fail()
    if not _keys(body["after_totals"], TOTAL_KEYS) or any(not _int(x) for x in body["after_totals"].values()):
        _fail()
    positions = body["positions"]
    if type(positions) is not list or not 1 <= len(positions) <= MAX_POSITIONS:
        _fail()
    return body


def prepare_correction(body, live_invoice, company_id, series):
    validate_request(body)
    parent = project_parent(live_invoice, company_id)
    if (canonical(parent) != canonical(body["parent"]) or fingerprint(parent) != body["parent_sha256"]
            or parent["price_model"] != body["price_model"]):
        _fail("parent_snapshot_changed")
    if (type(series) is not dict or identifier(series.get("id")) != body["series_id"]
            or series.get("name") != body["series_name"]):
        _fail("series_mismatch")
    by_id = {p["position_id"]: p for p in parent["positions"]}
    seen_ids, seen_keys = set(), set()
    rows, contents = [], {}
    common = {"kind", "line_key", "quantity", "unit_price_grosze", "vat_rate_code"}
    for index, position in enumerate(body["positions"]):
        if type(position) is not dict or type(position.get("kind")) is not str:
            _fail()
        kind = position["kind"]
        if kind not in ("existing", "new") or not _keys(position, common | ({"parent_position_id"} if kind == "existing" else {"name", "unit"})):
            _fail()
        key = position["line_key"]
        if not _text(key, 160) or key in seen_keys:
            _fail()
        seen_keys.add(key)
        qty, price, rate = position["quantity"], position["unit_price_grosze"], position["vat_rate_code"]
        totals = line_totals(parent["price_model"], rate, qty, price)
        parent_id = None
        if kind == "existing":
            parent_id = identifier(position["parent_position_id"])
            if parent_id != position["parent_position_id"] or parent_id not in by_id or parent_id in seen_ids:
                _fail()
            old = by_id[parent_id]
            if rate != old["vat_rate_code"] or price != old["unit_price_grosze"]:
                _fail("existing_line_price_changed")
            seen_ids.add(parent_id)
            name, unit = old["name"], old["unit"]
        else:
            if qty == 0 or not _text(position["name"], 1024) or not _text(position["unit"], 32):
                _fail()
            name, unit = position["name"], position["unit"]
        row = {"line_key": key, "parent_position_id": parent_id, "name": name, "unit": unit,
               "quantity": qty, "unit_price_grosze": price, "vat_rate_code": rate, **totals}
        rows.append(row)
        content = {"count": qty, "price": money_text(price)}
        if kind == "existing":
            content["parent_id"] = int(parent_id)
        else:
            content.update(name=name, unit=unit, vat=rate)
        contents[str(index)] = {"invoicecontent": content}
    if seen_ids != set(by_id) or _totals(rows) != body["after_totals"]:
        _fail("after_snapshot_mismatch")
    key = ("mt1:" + fingerprint({"change_id": body["change_id"],
                                 "parent": body["parent_sha256"]}))[:MARKER_LIMIT]
    document = {"type": "correction", "parent_id": int(parent["document_id"]),
                "contractor_id": int(parent["contractor_id"]), "date": body["issue_date"],
                "series_id": int(body["series_id"]), "description": body["correction_reason"],
                "price_type": parent["price_model"], "id_external": key,
                "auto_send": 0, "invoicecontents": contents}
    # Only these frozen fields may be copied; never arbitrary provider keys.
    document["contractor_detail"] = {k: v for k, v in _party_detail(live_invoice["contractor_detail"]).items() if v != ""}
    if parent["receiver_id"]:
        document["contractor_receiver_id"] = int(parent["receiver_id"])
        document["contractor_detail_receiver"] = {k: v for k, v in _party_detail(live_invoice["contractor_detail_receiver"]).items() if v != ""}
    return {"document": document, "parent": parent, "positions": rows,
            "totals": _totals(rows), "series_id": body["series_id"]}


def verify_created(prepared, invoice, document_id, company_id):
    observed = project_parent(invoice, company_id)
    parent = prepared["parent"]
    if (observed["document_id"] != identifier(document_id) or observed["document_id"] == parent["document_id"]
            or observed["document_type"] != "correction" or observed["source_document_id"] != parent["document_id"]
            or observed["external_key"] != prepared["document"]["id_external"]
            or observed["totals"] != prepared["totals"]
            or _relation(invoice, "series") != prepared["series_id"]
            or any(observed[k] != parent[k] for k in ("company_id", "contractor_id", "receiver_id", "party_sha256", "price_model", "currency"))):
        _fail("created_document_mismatch")
    if len(observed["positions"]) != len(prepared["positions"]):
        _fail("created_positions_mismatch")
    parent_ids = {row["position_id"] for row in parent["positions"]}
    by_parent = {row["parent_position_id"]: row for row in prepared["positions"]
                 if row["parent_position_id"] is not None}
    remaining = {row["line_key"]: row for row in prepared["positions"]}
    mapping, without_links = [], []
    for row in observed["positions"]:
        if row["position_id"] in parent_ids:
            _fail("created_positions_mismatch")
        if row["source_parent_id"] is None:
            without_links.append(row)
            continue
        wanted = by_parent.pop(row["source_parent_id"], None)
        if wanted is None or any(wanted[k] != row[k] for k in SIGNATURE_KEYS):
            _fail("created_positions_mismatch")
        del remaining[wanted["line_key"]]
        mapping.append({"line_key": wanted["line_key"], "position_id": row["position_id"]})

    expected_groups, actual_groups = {}, {}
    for row in remaining.values():
        expected_groups.setdefault(tuple(row[k] for k in SIGNATURE_KEYS), []).append(row["line_key"])
    for row in without_links:
        actual_groups.setdefault(tuple(row[k] for k in SIGNATURE_KEYS), []).append(row["position_id"])
    if expected_groups.keys() != actual_groups.keys():
        _fail("created_positions_mismatch")
    equivalent = []
    for signature, keys in expected_groups.items():
        ids = actual_groups[signature]
        if len(keys) != len(ids):
            _fail("created_positions_mismatch")
        if len(keys) == 1:
            mapping.append({"line_key": keys[0], "position_id": ids[0]})
        else:
            # Prove a complete multiset, not an invented person-to-row identity.
            # Keep each quantity/rounding row separate; never aggregate money.
            equivalent.append({"line_keys": sorted(keys), "position_ids": sorted(ids)})
    return {"parent": observed, "parent_sha256": fingerprint(observed),
            "position_mapping": sorted(mapping, key=lambda item: item["line_key"]),
            "equivalent_position_groups": sorted(equivalent, key=lambda item: item["line_keys"])}


def decode_request(data):
    """Bounded JSON, rejecting duplicate fields and non-finite numbers."""
    if type(data) is not bytes or len(data) > MAX_BODY_BYTES:
        _fail()
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _fail()
            result[key] = value
        return result
    try:
        body = json.loads(data.decode("utf-8"), object_pairs_hook=pairs,
                          parse_constant=lambda value: _fail())
        return validate_request(body)
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
        _fail()
