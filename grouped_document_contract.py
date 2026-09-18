"""WO-601AD-F: grouped NETTO documents, full state and signed correction.

Pure v2 contract. A verified source is not authority to issue a document.
The caller must authenticate tenant/order, read the whole chain, own a durable
start fence, and classify unknown create outcomes. Never retry a POST here.
Copied byte-for-byte to the bridge with the pinned document calculator.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import re
from collections import Counter

if __package__:
    from . import wfirma_document_money as money
else:
    import wfirma_document_money as money

VERSION = 2
MAX_BYTES = 4 * 1024 * 1024
MAX_CHAIN = 32
MAX_QUANTITY = 5000
VAT_IDS = {"222": "23", "223": "8", "224": "5", "225": "0", "226": "zw", "227": "np"}
PARTY_FIELDS = ("role", "name", "tax_id_type", "nip", "street", "zip", "city", "country")
TOTAL_KEYS = ("net_grosze", "vat_grosze", "gross_grosze")
REQUEST_KEYS = frozenset({
    "contract_version", "calculation_version", "company", "change_id", "intent_sha256",
    "source_document_ids", "parent", "parent_sha256", "issue_date", "series_id",
    "series_name", "correction_reason", "price_model", "currency", "positions",
    "after_valuation", "document_delta",
})


class GroupedDocumentError(ValueError):
    """Closed reason; never attach raw provider values, party names or IDs."""


def require(condition, reason="invalid_grouped_contract"):
    if not condition:
        raise GroupedDocumentError(reason)


def canonical(value):
    try:
        data = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                          separators=(",", ":")).encode("utf-8")
        require(len(data) <= MAX_BYTES, "contract_size_limit")
        return data
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        raise GroupedDocumentError("contract_encoding_invalid") from None


def fingerprint(value):
    return hashlib.sha256(canonical(value)).hexdigest()


MARKER_LIMIT = 32


def marker(prefix, value):
    """Request marker short enough for the provider to store it whole.

    wFirma keeps `id_external` truncated to 32 characters. Measured on
    production 2026-09-18: 68 characters sent, 32 read back. A longer marker
    can therefore never read back equal to what was written, so the identity
    check fails for every document and none is ever recognised as our own.
    Cutting the very string we used to send keeps documents created before
    this fix recognisable.
    """
    require(type(prefix) is str and len(prefix) == 4)
    return (prefix + fingerprint(value))[:MARKER_LIMIT]


def keys(value, expected):
    return type(value) is dict and set(value) == set(expected) and all(type(k) is str for k in value)


def text(value, limit=160):
    try:
        return (type(value) is str and bool(value) and value == value.strip()
                and value.isprintable() and len(value.encode("utf-8")) <= limit)
    except UnicodeError:
        return False


def identifier(value):
    if type(value) is int and 0 < value < 10**32:
        return str(value)
    require(type(value) is str and re.fullmatch(r"[1-9][0-9]{0,31}", value, re.ASCII))
    return value


def integer(value, limit=MAX_QUANTITY):
    """Provider decimal notation is accepted only for an EXACT integer."""
    if type(value) is str and re.fullmatch(r"(?:0|[1-9][0-9]{0,18})(?:\.0{1,4})?", value, re.ASCII):
        value = int(value.split(".")[0])
    require(type(value) is int and 0 <= value <= limit)
    return value


def amount(value, *, signed=False):
    require(type(value) in (str, int))  # no binary float or ambient Decimal context
    raw = str(value)
    require(len(raw) <= 24 and re.fullmatch(
        (r"-?" if signed else "") + r"(?:0|[1-9][0-9]{0,18})(?:\.[0-9]{1,2})?", raw, re.ASCII))
    negative = raw.startswith("-")
    whole, _, fraction = raw.lstrip("-").partition(".")
    result = int(whole)*100 + int((fraction+"00")[:2])
    require(result <= money.MAX_GROSZE)
    return -result if negative else result


def vat_relation(code):
    """Provider invoices/add expects the VAT relation, not a numeric VAT label."""
    require(type(code) is str and code in VAT_IDS.values())
    return {"id":int(next(identifier for identifier,rate in VAT_IDS.items() if rate==code))}


def money_text(value):
    require(type(value) is int and 0 <= value <= money.MAX_GROSZE)
    return f"{value//100}.{value%100:02d}"


def relation(node, name, *, optional=False):
    values = []
    if name in node:
        require(type(node[name]) is dict and "id" in node[name])
        values.append(node[name]["id"])
    if name+"_id" in node:
        values.append(node[name+"_id"])
    if not values:
        require(optional)
        return None
    normalized = [None if optional and type(v) in (str, int) and v in (0, "0", "")
                  else identifier(v) for v in values]
    require(all(v == normalized[0] for v in normalized))
    return normalized[0]


def party_detail(value):
    require(type(value) is dict and text(value.get("name"), 1024), "party_invalid")
    result = {}
    for key in PARTY_FIELDS:
        field = value.get(key, "")
        if key == "role" and type(field) is int:
            field = str(field)
        if key == "role" and field == "0":
            # The provider spells "no role" two ways: an absent field reads
            # back as "" and an explicit zero as "0". Measured on production
            # 2026-09-18: a proforma carried "" while its own contractor card
            # carried "0", and the settlement refused to recognise the buyer
            # as unchanged. One spelling, so identical parties compare equal.
            field = ""
        require(field == "" or text(field, 1024), "party_invalid")
        result[key] = field
    return result


def collection(value, wrapper):
    require(type(value) is dict, "positions_incomplete")
    indices = [k for k in value if k != "parameters"]
    require(1 <= len(indices) <= money.MAX_POSITIONS
            and set(indices) == {str(i) for i in range(len(indices))}, "positions_incomplete")
    if "parameters" in value:
        meta = value["parameters"]
        require(keys(meta, {"total"}) and integer(meta["total"], money.MAX_POSITIONS) == len(indices),
                "positions_incomplete")
    result = []
    for index in range(len(indices)):
        item = value[str(index)]
        require(keys(item, {wrapper}) and type(item[wrapper]) is dict, "positions_incomplete")
        result.append(item[wrapper])
    return result


def valuation(rows):
    try:
        return money.calculate_document_money(
            calculation_version=money.CALCULATION_VERSION, price_model="netto",
            positions=[{k: r[k] for k in ("quantity", "unit_net_grosze", "vat_rate_code")}
                       for r in rows if r["quantity"] != 0])
    except (KeyError, TypeError, money.DocumentMoneyError):
        raise GroupedDocumentError("valuation_invalid") from None


def difference(before, after):
    return {k: after["totals"][k]-before["totals"][k] for k in TOTAL_KEYS}


def group_difference(before, after):
    b = {r["vat_rate_code"]: r for r in before["vat_groups"]}
    a = {r["vat_rate_code"]: r for r in after["vat_groups"]}
    return {code: {k: a.get(code, {}).get(k, 0)-b.get(code, {}).get(k, 0) for k in TOTAL_KEYS}
            for code in set(a) | set(b)}


def same_valuation(left, right):
    """Rows may be reordered, never merged or rounded per participant."""
    try:
        fixed = ("calculation_version", "price_model", "currency", "vat_groups", "totals")
        return (all(canonical(left[k]) == canonical(right[k]) for k in fixed)
                and Counter(canonical(r) for r in left["positions"])
                    == Counter(canonical(r) for r in right["positions"])
                and set(left) == set(right))
    except (TypeError, KeyError):
        return False


def _project(invoice, company_id, *, previous, root_id, terminal):
    require(type(invoice) is dict)
    canonical(invoice)
    require(invoice.get("price_type") == "netto" and invoice.get("currency") == "PLN",
            "document_epoch_invalid")
    kind = invoice.get("type")
    require(kind == ("normal" if previous is None else "correction"), "document_chain_invalid")
    count = integer(invoice.get("corrections"))
    require((count == 0) if terminal else (count > 0), "document_terminal_mismatch")
    document_id = identifier(invoice.get("id"))
    parent_id = relation(invoice, "parent", optional=True)
    if previous is None:
        require(parent_id is None, "document_chain_invalid")
    else:
        require(parent_id in {previous["document_id"], root_id} and document_id != parent_id,
                "document_chain_invalid")
    receiver = relation(invoice, "contractor_receiver", optional=True)
    buyer = party_detail(invoice.get("contractor_detail"))
    recipient = party_detail(invoice.get("contractor_detail_receiver")) if receiver else None
    identity = dict(company_id=identifier(company_id), contractor_id=relation(invoice, "contractor"),
        receiver_id=receiver, party_sha256=fingerprint({"buyer": buyer, "receiver": recipient}),
        price_model="netto", currency="PLN")
    if previous:
        require(all(identity[k] == previous[k] for k in identity), "chain_party_changed")
    rows = []
    for item in collection(invoice.get("invoicecontents"), "invoicecontent"):
        quantity = integer(item.get("count"))
        if "unit_count" in item:
            require(integer(item["unit_count"]) == quantity, "quantity_unit_mismatch")
        price = amount(item.get("price"))
        flag = integer(item.get("discount", "0"), 1)
        percent = amount(item.get("discount_percent", "0"))
        require(percent == 0, "discount_representation_unsupported")
        code_node = item.get("vat_code")
        require(type(code_node) is dict)
        code = VAT_IDS.get(identifier(code_node.get("id")))
        require(code is not None and text(item.get("name"), 1024) and text(item.get("unit"), 32))
        net = quantity*price
        percent_value = dict(money._VAT_RATES)[code]
        displayed_gross = net + (net*percent_value+50)//100
        require(net <= money.MAX_GROSZE and net == amount(item.get("netto"))
                and displayed_gross == amount(item.get("brutto")), "document_line_amount_mismatch")
        rows.append(dict(position_id=identifier(item.get("id")),
            source_parent_id=relation(item, "parent", optional=True),
            name=item["name"], unit=item["unit"], quantity=quantity, unit_net_grosze=price,
            vat_rate_code=code, net_grosze=net, displayed_gross_grosze=displayed_gross,
            source_discount_flag=flag, source_discount_percent=percent))
    require(len({r["position_id"] for r in rows}) == len(rows), "duplicate_position")
    if previous:
        prior_ids = {r["position_id"] for r in previous["positions"]}
        linked = [r["source_parent_id"] for r in rows if r["source_parent_id"] is not None]
        require(set(linked) == prior_ids and len(linked) == len(prior_ids)
                and not prior_ids.intersection(r["position_id"] for r in rows), "chain_positions_incomplete")
    else:
        require(all(r["source_parent_id"] is None for r in rows), "unexpected_position_parent")
    after = valuation(rows)
    before = previous["full_valuation"] if previous else valuation([])
    expected_header = difference(before, after)
    header = dict(net_grosze=amount(invoice.get("netto"), signed=True),
                  vat_grosze=amount(invoice.get("tax"), signed=True),
                  gross_grosze=amount(invoice.get("total"), signed=True))
    require(header == expected_header, "document_header_mismatch")
    if terminal:
        require(amount(invoice.get("total_composed"), signed=True) == header["gross_grosze"],
                "document_composed_mismatch")
    groups = {}
    for item in collection(invoice.get("vat_contents"), "vat_content"):
        code = VAT_IDS.get(relation(item, "vat_code"))
        require(code is not None and code not in groups, "vat_summary_invalid")
        groups[code] = dict(net_grosze=amount(item.get("netto"), signed=True),
                           vat_grosze=amount(item.get("tax"), signed=True),
                           gross_grosze=amount(item.get("brutto"), signed=True))
    # Provider may include zero summary rows for a deleted or zero-price rate.
    expected_groups = group_difference(before, after)
    require(all(v == expected_groups.get(k, dict.fromkeys(TOTAL_KEYS, 0)) for k,v in groups.items())
            and all(v == groups.get(k, dict.fromkeys(TOTAL_KEYS, 0)) for k,v in expected_groups.items()),
            "vat_summary_mismatch")
    external = invoice.get("id_external", "")
    require(external == "" or text(external, 160))
    return dict(contract_version=VERSION, calculation_version=money.CALCULATION_VERSION,
        document_id=document_id, document_type=kind, source_document_id=parent_id,
        root_document_id=root_id or document_id, corrections=count, **identity,
        external_key=external, positions=sorted(rows, key=lambda r:r["position_id"]),
        full_valuation=after, document_delta=header)


def project_chain(invoices, company_id):
    require(type(invoices) is list and 1 <= len(invoices) <= MAX_CHAIN, "document_chain_invalid")
    canonical(invoices)  # one bound for the WHOLE chain, not 32 independent limits
    previous, seen, ids = None, set(), []
    for index, invoice in enumerate(invoices):
        item = _project(invoice, company_id, previous=previous,
            root_id=ids[0] if ids else None, terminal=index == len(invoices)-1)
        require(item["document_id"] not in seen, "document_chain_invalid")
        seen.add(item["document_id"])
        ids.append(item["document_id"])
        previous = item
    previous["source_document_ids"] = ids
    return previous


def validate_request(body):
    require(keys(body, REQUEST_KEYS))
    require(type(body["contract_version"]) is int and body["contract_version"] == VERSION
            and body["calculation_version"] == money.CALCULATION_VERSION, "version_unsupported")
    require(type(body["company"]) is str and body["company"] in {"md", "md_test", "test"})
    require(text(body["change_id"]) and text(body["series_name"], 128)
            and text(body["correction_reason"], 500))
    require(type(body["parent"]) is dict and fingerprint(body["parent"]) == body["parent_sha256"])
    require(type(body["intent_sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", body["intent_sha256"], re.ASCII))
    ids = body["source_document_ids"]
    require(type(ids) is list and 1 <= len(ids) <= MAX_CHAIN
            and all(identifier(v) == v for v in ids) and len(set(ids)) == len(ids))
    require(body["price_model"] == "netto" and body["currency"] == "PLN")
    require(identifier(body["series_id"]) == body["series_id"])
    try:
        require(datetime.date.fromisoformat(body["issue_date"]).isoformat() == body["issue_date"])
    except (TypeError, ValueError):
        raise GroupedDocumentError("date_invalid") from None
    require(type(body["positions"]) is list and 1 <= len(body["positions"]) <= money.MAX_POSITIONS)
    canonical(body)
    return body


def prepare_correction(body, live_invoices, company_id, series):
    validate_request(body)
    parent = project_chain(live_invoices, company_id)
    require(len(parent["source_document_ids"]) < MAX_CHAIN, "document_chain_limit")
    require(canonical(parent) == canonical(body["parent"])
            and parent["source_document_ids"] == body["source_document_ids"], "parent_snapshot_changed")
    require(type(series) is dict and identifier(series.get("id")) == body["series_id"]
            and series.get("name") == body["series_name"], "series_mismatch")
    by_id = {r["position_id"]: r for r in parent["positions"]}
    seen_ids, seen_keys, rows, contents = set(), set(), [], {}
    common = {"kind", "line_key", "quantity", "unit_net_grosze", "vat_rate_code"}
    for index, position in enumerate(body["positions"]):
        require(type(position) is dict)
        kind = position.get("kind")
        require(type(kind) is str and kind in {"existing", "new"})
        require(keys(position, common | ({"parent_position_id"} if kind == "existing" else {"name", "unit"})))
        key = position["line_key"]
        require(text(key) and key not in seen_keys)
        seen_keys.add(key)
        qty, price, rate = position["quantity"], position["unit_net_grosze"], position["vat_rate_code"]
        require(type(qty) is int and 0 <= qty <= MAX_QUANTITY
                and type(price) is int and 0 <= price <= money.MAX_GROSZE
                and type(rate) is str and rate in money._VAT_CODES)
        parent_position_id = None
        if kind == "existing":
            parent_position_id = identifier(position["parent_position_id"])
            require(parent_position_id == position["parent_position_id"]
                    and parent_position_id in by_id and parent_position_id not in seen_ids)
            seen_ids.add(parent_position_id)
            name, unit = by_id[parent_position_id]["name"], by_id[parent_position_id]["unit"]
        else:
            require(qty > 0 and text(position["name"], 1024) and text(position["unit"], 32))
            name, unit = position["name"], position["unit"]
        rows.append(dict(line_key=key, parent_position_id=parent_position_id, name=name, unit=unit,
                         quantity=qty, unit_net_grosze=price, vat_rate_code=rate))
        # price is final NETTO. Explicitly turn the provider discount OFF;
        # parent discount flag must not be inherited and applied a second time.
        content = dict(count=qty, price=money_text(price), vat_code=vat_relation(rate), discount=0, discount_percent=0)
        if parent_position_id:
            content["parent_id"] = int(parent_position_id)
        else:
            content.update(name=name, unit=unit)
        contents[str(index)] = {"invoicecontent": content}
    require(seen_ids == set(by_id), "after_positions_incomplete")
    after = valuation(rows)
    delta = difference(parent["full_valuation"], after)
    require(canonical(after) == canonical(body["after_valuation"])
            and canonical(delta) == canonical(body["document_delta"]), "after_valuation_mismatch")
    require(any(v != 0 for v in delta.values()) or
            Counter((r["quantity"], r["unit_net_grosze"], r["vat_rate_code"], r["name"], r["unit"]) for r in rows)
            != Counter((r["quantity"], r["unit_net_grosze"], r["vat_rate_code"], r["name"], r["unit"]) for r in parent["positions"]),
            "document_no_change")
    key = marker("nd2:", {"change_id":body["change_id"], "intent_sha256":body["intent_sha256"],
                          "parent_sha256":body["parent_sha256"]})
    invoice = live_invoices[-1]
    document = dict(type="correction", parent_id=int(parent["document_id"]),
        contractor_id=int(parent["contractor_id"]), date=body["issue_date"], series={"id":int(body["series_id"])},
        description=body["correction_reason"], price_type="netto", id_external=key, auto_send=0,
        invoicecontents=contents, contractor_detail={k:v for k,v in party_detail(invoice["contractor_detail"]).items() if v != ""})
    if parent["receiver_id"]:
        document.update(contractor_receiver_id=int(parent["receiver_id"]),
            contractor_detail_receiver={k:v for k,v in party_detail(invoice["contractor_detail_receiver"]).items() if v != ""})
    return dict(document=document, parent=parent, positions=rows, after_valuation=after,
                document_delta=delta, series_id=body["series_id"])


def verify_created(prepared, invoice, document_id, company_id):
    parent = prepared["parent"]
    observed = _project(invoice, company_id, previous=parent,
        root_id=parent["root_document_id"], terminal=True)
    require(observed["document_id"] == identifier(document_id)
            and observed["document_id"] not in parent["source_document_ids"]
            and observed["source_document_id"] == parent["document_id"]
            and observed["external_key"] == prepared["document"]["id_external"]
            and relation(invoice, "series") == prepared["series_id"], "created_identity_mismatch")
    require(same_valuation(observed["full_valuation"], prepared["after_valuation"])
            and canonical(observed["document_delta"]) == canonical(prepared["document_delta"]),
            "created_valuation_mismatch")
    remaining = {r["line_key"]:r for r in prepared["positions"]}
    existing = {r["parent_position_id"]:r for r in remaining.values() if r["parent_position_id"] is not None}
    mapping, fresh = [], []
    signature = ("name", "unit", "quantity", "unit_net_grosze", "vat_rate_code")
    for row in observed["positions"]:
        require(row["source_discount_flag"] == 0 and row["source_discount_percent"] == 0, "created_discount_mismatch")
        if row["source_parent_id"] is None:
            fresh.append(row)
            continue
        wanted = existing.pop(row["source_parent_id"], None)
        require(wanted is not None and all(row[k] == wanted[k] for k in signature), "created_positions_mismatch")
        remaining.pop(wanted["line_key"])
        mapping.append(dict(line_key=wanted["line_key"], position_id=row["position_id"]))
    require(not existing and len(fresh) == len(remaining), "created_positions_mismatch")
    equivalent = []
    for sig in {tuple(r[k] for k in signature) for r in remaining.values()}:
        wanted = sorted(k for k,r in remaining.items() if tuple(r[f] for f in signature) == sig)
        actual = sorted(r["position_id"] for r in fresh if tuple(r[f] for f in signature) == sig)
        require(len(wanted) == len(actual), "created_positions_mismatch")
        if len(wanted) == 1:
            mapping.append(dict(line_key=wanted[0], position_id=actual[0]))
        else:
            equivalent.append(dict(line_keys=wanted, position_ids=actual))
    observed["source_document_ids"] = parent["source_document_ids"] + [observed["document_id"]]
    return dict(parent=observed, parent_sha256=fingerprint(observed),
                position_mapping=sorted(mapping, key=lambda r:r["line_key"]),
                equivalent_position_groups=sorted(equivalent, key=lambda r:r["line_keys"]))


def decode_request(data):
    require(type(data) is bytes and len(data) <= MAX_BYTES, "contract_size_limit")
    def pairs(items):
        result = {}
        for key,value in items:
            require(key not in result, "duplicate_field")
            result[key] = value
        return result
    def invalid(_):
        raise GroupedDocumentError("invalid_number")
    try:
        return validate_request(json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid))
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
        raise GroupedDocumentError("invalid_grouped_contract") from None
