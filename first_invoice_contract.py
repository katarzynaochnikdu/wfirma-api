"""Grouped first normal invoice, not a correction and never a cash writer.

Pure internal contract. Caller authenticates the order, proves no prior document
and cash basis, resolves parties, and owns a committed outbound fence.
Canonical identical copy is required in the bridge before activation.
"""
from collections import Counter
from datetime import date
import json
import re

if __package__:
    from . import wfirma_grouped_document_contract as c
else:
    import grouped_document_contract as c

VERSION = 1
KEYS = {"contract_version","calculation_version","company","change_id","intent_sha256",
    "issue_date","sale_date","series_id","series_name","description","price_model",
    "currency","positions","after_valuation","settled_grosze","buyer","receiver"}
LINE_KEYS = {"line_key","name","unit","quantity","unit_net_grosze","vat_rate_code"}
SIGNATURE = ("name","unit","quantity","unit_net_grosze","vat_rate_code")


def decode(raw):
    c.require(type(raw) is bytes and len(raw)<=c.MAX_BYTES)
    def pairs(items):
        result={}
        for key,value in items:
            c.require(key not in result)
            result[key]=value
        return result
    def bad_number(_):raise c.GroupedDocumentError("invalid_number")
    try:return validate(json.loads(raw.decode("utf-8"),object_pairs_hook=pairs,parse_constant=bad_number))
    except (UnicodeError,ValueError,TypeError,RecursionError):
        raise c.GroupedDocumentError("invalid_request") from None


def party(value,*,resolved=False):
    c.require(c.keys(value,{"id","detail"}))
    c.require((value["id"] is None and not resolved) or c.identifier(value["id"])==value["id"])
    c.require(c.keys(value["detail"],c.PARTY_FIELDS))
    detail=c.party_detail(value["detail"])
    c.require(c.canonical(detail)==c.canonical(value["detail"]))
    return value


def resolved_party(expected,actual):
    party(expected)
    party(actual,resolved=True)
    c.require((expected["id"] is None or actual["id"]==expected["id"])
        and c.canonical(actual["detail"])==c.canonical(expected["detail"]),"party_changed")
    return actual


def validate(body):
    c.require(c.keys(body,KEYS))
    c.canonical(body)
    c.require(type(body["contract_version"]) is int and body["contract_version"]==VERSION
        and body["calculation_version"]==c.money.CALCULATION_VERSION
        and type(body["company"]) is str and body["company"] in {"md","md_test"}
        and body["price_model"]=="netto" and body["currency"]=="PLN")
    c.require(c.text(body["change_id"]) and c.text(body["description"],4096)
        and c.text(body["series_name"],128) and c.identifier(body["series_id"])==body["series_id"]
        and type(body["intent_sha256"]) is str
        and re.fullmatch(r"[0-9a-f]{64}",body["intent_sha256"],re.ASCII))
    for key in ("issue_date","sale_date"):
        try:c.require(type(body[key]) is str and date.fromisoformat(body[key]).isoformat()==body[key])
        except (ValueError,TypeError):raise c.GroupedDocumentError("date_invalid") from None
    c.require(body["sale_date"]<=body["issue_date"],"sale_date_after_issue")
    party(body["buyer"])
    if body["receiver"] is not None:party(body["receiver"])
    rows=body["positions"]
    c.require(type(rows) is list and 1<=len(rows)<=c.money.MAX_POSITIONS)
    seen=set()
    for row in rows:
        c.require(c.keys(row,LINE_KEYS) and c.text(row["line_key"])
            and row["line_key"] not in seen and c.text(row["name"],1024) and c.text(row["unit"],32)
            and type(row["quantity"]) is int and 1<=row["quantity"]<=c.MAX_QUANTITY
            and type(row["unit_net_grosze"]) is int and 0<=row["unit_net_grosze"]<=c.money.MAX_GROSZE
            and type(row["vat_rate_code"]) is str and row["vat_rate_code"] in c.money._VAT_CODES)
        seen.add(row["line_key"])
    value=c.valuation(rows)
    c.require(c.canonical(value)==c.canonical(body["after_valuation"]),"after_valuation_mismatch")
    gross=value["totals"]["gross_grosze"]
    c.require(gross>0 and type(body["settled_grosze"]) is int
        and gross<=body["settled_grosze"]<=c.money.MAX_GROSZE,"cash_not_confirmed")
    return body


def prepare(body,company_id,series,*,buyer,receiver):
    """Resolved IDs and exact party details must be checked fresh by the bridge."""
    validate(body)
    company_id=c.identifier(company_id)
    c.require(type(series) is dict and c.identifier(series.get("id"))==body["series_id"]
        and series.get("name")==body["series_name"],"series_mismatch")
    resolved_party(body["buyer"],buyer)
    c.require((receiver is None)==(body["receiver"] is None),"receiver_changed")
    if receiver is not None:resolved_party(body["receiver"],receiver)
    gross=body["after_valuation"]["totals"]["gross_grosze"]
    external="nf1:"+c.fingerprint({"change_id":body["change_id"],"intent_sha256":body["intent_sha256"]})
    document=dict(type="normal",price_type="netto",currency="PLN",contractor_id=int(buyer["id"]),
        contractor_detail={k:v for k,v in buyer["detail"].items() if v!=""},
        date=body["issue_date"],disposaldate=body["sale_date"],paymentdate=body["issue_date"],paymentmethod="transfer",
        series={"id":int(body["series_id"])},id_external=external,auto_send=0,description=body["description"],
        alreadypaid_initial=c.money_text(gross),invoicecontents={
            str(i):{"invoicecontent":dict(name=p["name"],unit=p["unit"],count=p["quantity"],
                price=c.money_text(p["unit_net_grosze"]),vat_code=c.vat_relation(p["vat_rate_code"]),discount=0,discount_percent=0)}
            for i,p in enumerate(body["positions"])})
    if receiver is not None:
        document.update(contractor_receiver_id=int(receiver["id"]),
            contractor_detail_receiver={k:v for k,v in receiver["detail"].items() if v!=""})
    return dict(document=document,company_id=company_id,positions=body["positions"],
        after_valuation=body["after_valuation"],buyer=buyer,receiver=receiver,series_id=body["series_id"])


def verify_created(prepared,invoice,document_id,company_id):
    """Independent full GET required. A 200/create body never proves payment/lines."""
    c.require(c.identifier(company_id)==prepared["company_id"])
    observed=c.project_chain([invoice],company_id)
    c.require(observed["document_id"]==c.identifier(document_id)
        and observed["external_key"]==prepared["document"]["id_external"]
        and c.relation(invoice,"series")==prepared["series_id"] and c.text(invoice.get("fullnumber"),256),
        "created_identity_mismatch")
    expected_parties={"buyer":prepared["buyer"]["detail"],
        "receiver":prepared["receiver"]["detail"] if prepared["receiver"] else None}
    c.require(observed["contractor_id"]==prepared["buyer"]["id"]
        and observed["receiver_id"]==(prepared["receiver"]["id"] if prepared["receiver"] else None)
        and observed["party_sha256"]==c.fingerprint(expected_parties),"created_party_mismatch")
    c.require(c.same_valuation(observed["full_valuation"],prepared["after_valuation"]),"created_valuation_mismatch")
    c.require(invoice.get("date")==prepared["document"]["date"]
        and invoice.get("disposaldate")==prepared["document"]["disposaldate"],"created_date_mismatch")
    c.require(all(invoice.get(key)==prepared["document"][key]
        for key in ("paymentdate","paymentmethod","description")),"created_payment_metadata_mismatch")
    gross=prepared["after_valuation"]["totals"]["gross_grosze"]
    c.require(invoice.get("paymentstate")=="paid" and c.amount(invoice.get("alreadypaid"))==gross
        and c.amount(invoice.get("remaining"))==0,"created_payment_mismatch")
    actual=observed["positions"]
    c.require(all(p["source_discount_flag"]==0 and p["source_discount_percent"]==0 for p in actual),
        "created_discount_mismatch")
    expected=prepared["positions"]
    c.require(Counter(tuple(p[k] for k in SIGNATURE) for p in actual)
        ==Counter(tuple(p[k] for k in SIGNATURE) for p in expected),"created_positions_mismatch")
    mapping,groups=[],[]
    for signature in {tuple(p[k] for k in SIGNATURE) for p in expected}:
        keys=sorted(p["line_key"] for p in expected if tuple(p[k] for k in SIGNATURE)==signature)
        ids=sorted(p["position_id"] for p in actual if tuple(p[k] for k in SIGNATURE)==signature)
        if len(keys)==1:mapping.append(dict(line_key=keys[0],position_id=ids[0]))
        else:groups.append(dict(line_keys=keys,position_ids=ids))
    return dict(parent=observed,parent_sha256=c.fingerprint(observed),
        position_mapping=sorted(mapping,key=lambda p:p["line_key"]),
        equivalent_position_groups=sorted(groups,key=lambda p:p["line_keys"]),
        paid_grosze=gross)
