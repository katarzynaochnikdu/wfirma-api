"""Synthetic provider-shaped data; literal money assertions, no API/DB."""
import copy
from copy import deepcopy
import json
import pytest

import grouped_document_contract as c


def invoice(*, qty="2.0000", price="398.37", net="796.74", vat="183.25",
            gross="979.99", position_id="8101", document_id="8001"):
    return dict(id=document_id, type="normal", price_type="netto", currency="PLN", corrections="0",
        contractor={"id":"7001"}, contractor_detail={"name":"Synthetic test company","country":"PL"},
        total=gross, total_composed=gross, netto=net, tax=vat,
        invoicecontents={"0":{"invoicecontent":dict(id=position_id, name="Conference", unit="szt.",
            count=qty, unit_count=qty, price=price, netto=net, brutto=gross, discount="1",
            discount_percent="0", vat_code={"id":"222"}, parent={"id":"0"})}},
        vat_contents={"0":{"vat_content":dict(vat_code={"id":"222"}, netto=net, tax=vat, brutto=gross)}})


def body_for(source, *, qty=3, price=39837):
    parent = c.project_chain([source], "130706")
    rows = [dict(kind="existing", line_key="conference", parent_position_id="8101",
                 quantity=qty, unit_net_grosze=price, vat_rate_code="23")]
    after = c.valuation(rows)
    return dict(contract_version=2, calculation_version=c.money.CALCULATION_VERSION,
        company="md_test", change_id="synthetic-1", intent_sha256="a"*64, source_document_ids=["8001"],
        parent=parent, parent_sha256=c.fingerprint(parent), issue_date="2026-09-13",
        series_id="71", series_name="KOR TEST", correction_reason="Zmiana biletow",
        price_model="netto", currency="PLN", positions=rows, after_valuation=after,
        document_delta=c.difference(parent["full_valuation"], after))


def prepare(source, body=None):
    return c.prepare_correction(body or body_for(source), [source], "130706", {"id":"71","name":"KOR TEST"})


def correction(prepared, *, document_id="8002", position_id="8201"):
    row = prepared["positions"][0]
    after, delta = prepared["after_valuation"]["totals"], prepared["document_delta"]
    def m(v):
        return ("-" if v < 0 else "") + f"{abs(v)//100}.{abs(v)%100:02d}"
    result = invoice(qty=str(row["quantity"])+".0000", price=m(row["unit_net_grosze"]),
        net=m(after["net_grosze"]), vat=m(after["vat_grosze"]), gross=m(after["gross_grosze"]),
        document_id=document_id, position_id=position_id)
    result.update(type="correction", parent={"id":prepared["parent"]["document_id"]},
        series={"id":"71"}, id_external=prepared["document"]["id_external"],
        netto=m(delta["net_grosze"]), tax=m(delta["vat_grosze"]), total=m(delta["gross_grosze"]),
        total_composed=m(delta["gross_grosze"]))
    result["invoicecontents"]["0"]["invoicecontent"].update(
        parent={"id":row["parent_position_id"]}, discount="0")
    result["vat_contents"]["0"]["vat_content"].update(
        netto=m(delta["net_grosze"]), tax=m(delta["vat_grosze"]), brutto=m(delta["gross_grosze"]))
    return result


def test_grouped_decimal_and_discount_flag_use_full_document_not_per_ticket():
    data = invoice()
    before = copy.deepcopy(data)
    result = c.project_chain([data], "130706")
    assert result["full_valuation"]["totals"] == {"net_grosze":79674, "vat_grosze":18325, "gross_grosze":97999}
    assert result["positions"][0]["quantity"] == 2
    assert result["positions"][0]["unit_net_grosze"] == 39837
    assert result["positions"][0]["source_discount_flag"] == 1
    assert data == before


def test_two_lines_round_vat_as_one_rate_group():
    data = invoice()
    line = data["invoicecontents"]["0"]["invoicecontent"]
    line.update(count="1.0000", unit_count="1.0000", netto="398.37", brutto="490.00")
    data["invoicecontents"]["1"] = {"invoicecontent":dict(line,id="8102")}
    result = c.project_chain([data], "130706")
    assert sum(r["displayed_gross_grosze"] for r in result["positions"]) == 98000
    assert result["full_valuation"]["totals"]["gross_grosze"] == 97999


@pytest.mark.parametrize("qty,price,net,vat,gross,delta", [
    (3,39837,119511,27488,146999,49000),
    (1,39837,39837,9163,49000,-48999),
    (0,39837,0,0,0,-97999),
    (2,50000,100000,23000,123000,25001),
    (2,0,0,0,0,-97999),
])
def test_quantity_price_and_free_changes_have_literal_signed_document_delta(qty,price,net,vat,gross,delta):
    data = invoice()
    body = body_for(data, qty=qty, price=price)
    before = copy.deepcopy((data,body))
    prepared = prepare(data,body)
    assert prepared["after_valuation"]["totals"] == {"net_grosze":net,"vat_grosze":vat,"gross_grosze":gross}
    assert prepared["document_delta"]["gross_grosze"] == delta
    wire = prepared["document"]["invoicecontents"]["0"]["invoicecontent"]
    assert wire == {"parent_id":8101,"count":qty,"price":f"{price//100}.{price%100:02d}",
                    "vat_code":{"id":222},"discount":0,"discount_percent":0}
    proof = c.verify_created(prepared,correction(prepared),"8002","130706")
    assert proof["parent"]["document_delta"]["gross_grosze"] == delta
    assert proof["parent"]["full_valuation"]["totals"]["gross_grosze"] == gross
    assert proof["position_mapping"] == [{"line_key":"conference","position_id":"8201"}]
    assert (data,body) == before


def test_free_to_paid_has_full_price_without_fabricating_cash():
    data = invoice(qty="2.0000",price="0.00",net="0.00",vat="0.00",gross="0.00")
    prepared = prepare(data,body_for(data,qty=2,price=50000))
    assert prepared["document_delta"] == {"net_grosze":100000,"vat_grosze":23000,"gross_grosze":123000}
    assert "alreadypaid" not in prepared["document"] and "payment" not in prepared["document"]


def test_second_correction_uses_latest_positions_and_full_after_not_negative_header():
    normal = invoice()
    first = prepare(normal,body_for(normal,qty=1))
    changed = correction(first)
    normal["corrections"] = "1"
    normal["total_composed"] = "490.00"  # original source now has a composed amount
    parent = c.project_chain([normal,changed],"130706")
    assert parent["document_delta"]["gross_grosze"] == -48999
    assert parent["full_valuation"]["totals"]["gross_grosze"] == 49000
    body = body_for(invoice(),qty=0)
    body.update(parent=parent,parent_sha256=c.fingerprint(parent),source_document_ids=["8001","8002"])
    body["positions"][0]["parent_position_id"] = "8201"
    body["document_delta"] = {"net_grosze":-39837,"vat_grosze":-9163,"gross_grosze":-49000}
    second = c.prepare_correction(body,[normal,changed],"130706",{"id":"71","name":"KOR TEST"})
    assert second["document"]["parent_id"] == 8002
    assert second["document"]["invoicecontents"]["0"]["invoicecontent"]["parent_id"] == 8201
    proof = c.verify_created(second,correction(second,document_id="8003",position_id="8301"),"8003","130706")
    assert proof["parent"]["source_document_ids"] == ["8001","8002","8003"]
    assert proof["parent"]["full_valuation"]["totals"]["gross_grosze"] == 0


@pytest.mark.parametrize("value", ["2.1","2.0001","2e0","02"," 2",True,2.0,-1,"NaN","Infinity","2.00000",5001])
def test_invalid_provider_quantity_is_not_truncated_or_coerced(value):
    data=invoice()
    data["invoicecontents"]["0"]["invoicecontent"]["count"] = value
    with pytest.raises(c.GroupedDocumentError):
        c.project_chain([data],"130706")


@pytest.mark.parametrize("field,value", [
    ("price","398.370"),("price",398.37),("discount","2"),("discount",True),
    ("discount_percent","30"),("unit_count","1"),("netto","796.73"),("brutto","980.00"),
    ("id","0"),("name","inject\nline"),("unit",""),("vat_code",{"id":"999"}),
])
def test_unproven_source_line_is_refused(field,value):
    data=invoice()
    data["invoicecontents"]["0"]["invoicecontent"][field]=value
    with pytest.raises(c.GroupedDocumentError):
        c.project_chain([data],"130706")


@pytest.mark.parametrize("field,value", [
    ("price_type","brutto"),("price_type",None),("currency","EUR"),("type","proforma"),
    ("total","980.00"),("netto","796.75"),("tax","183.26"),("total_composed","980.00"),
    ("corrections","1"),("contractor_detail",{}),("invoicecontents",{}),("vat_contents",{}),
])
def test_incomplete_or_wrong_document_never_produces_source_proof(field,value):
    data=invoice()
    data[field]=value
    with pytest.raises(c.GroupedDocumentError):
        c.project_chain([data],"130706")


def test_provider_pagination_and_duplicate_summary_cannot_hide_rows():
    data=invoice()
    data["invoicecontents"]["parameters"]={"total":"2"}
    with pytest.raises(c.GroupedDocumentError,match="positions_incomplete"):
        c.project_chain([data],"130706")
    data=invoice()
    data["vat_contents"]["1"]=copy.deepcopy(data["vat_contents"]["0"])
    with pytest.raises(c.GroupedDocumentError,match="vat_summary_invalid"):
        c.project_chain([data],"130706")


@pytest.mark.parametrize("change", ["identity","header","series","external","quantity","price","discount","position_parent","company"])
def test_bad_readback_never_confirms_created_correction(change):
    data=invoice()
    prepared=prepare(data)
    out=correction(prepared)
    company="130706"
    if change=="identity": out["id"]="8001"
    elif change=="header": out["total"]="490.01"
    elif change=="series": out["series"]["id"]="72"
    elif change=="external": out["id_external"]="different"
    elif change=="quantity": out["invoicecontents"]["0"]["invoicecontent"]["count"]="4"
    elif change=="price": out["invoicecontents"]["0"]["invoicecontent"]["price"]="1.00"
    elif change=="discount": out["invoicecontents"]["0"]["invoicecontent"]["discount"]="1"
    elif change=="position_parent": out["invoicecontents"]["0"]["invoicecontent"]["parent"]={"id":"8102"}
    else: company="130707"
    with pytest.raises(c.GroupedDocumentError):
        c.verify_created(prepared,out,"8002",company)


@pytest.mark.parametrize("change", ["version","math","intent","ids","sha","parent","missing_line","amount","extra"])
def test_invalid_request_refuses_before_wire_document(change):
    data=invoice()
    body=body_for(data)
    if change=="version": body["contract_version"]=1
    elif change=="math": body["calculation_version"]="legacy"
    elif change=="intent": body["intent_sha256"]="x"*64
    elif change=="ids": body["source_document_ids"]=["8002"]
    elif change=="sha": body["parent_sha256"]="0"*64
    elif change=="parent": body["parent"]["full_valuation"]["totals"]["gross_grosze"]+=1; body["parent_sha256"]=c.fingerprint(body["parent"])
    elif change=="missing_line": body["positions"]=[]
    elif change=="amount": body["after_valuation"]["totals"]["gross_grosze"]+=1
    else: body["payment"]=123
    with pytest.raises(c.GroupedDocumentError):
        prepare(data,body)


def test_duplicate_json_and_v1_are_rejected():
    body=body_for(invoice())
    raw=c.canonical(body)
    assert c.decode_request(raw)==body
    with pytest.raises(c.GroupedDocumentError):
        c.decode_request(raw[:-1]+b',"contract_version":2}')
    with pytest.raises(c.GroupedDocumentError):
        c.decode_request(b'{"contract_version":NaN}')


def test_source_changed_since_preview_is_refused():
    data=invoice()
    body=body_for(data)
    data["contractor_detail"]["name"]="Changed synthetic buyer"
    with pytest.raises(c.GroupedDocumentError,match="parent_snapshot_changed"):
        prepare(data,body)


def add_banquet_case(number=1):
    data=invoice()
    body=body_for(data,qty=2)
    for index in range(number):
        body["positions"].append(dict(kind="new",line_key=f"banquet{index}",name="Banquet",unit="szt.",
            quantity=1,unit_net_grosze=10000,vat_rate_code="23"))
    body["after_valuation"]=c.valuation(body["positions"])
    body["document_delta"]=c.difference(body["parent"]["full_valuation"],body["after_valuation"])
    prepared=prepare(data,body)
    out=invoice(document_id="8002",position_id="8201")
    delta = 12300*number
    out.update(type="correction",parent={"id":"8001"},series={"id":"71"},
        id_external=prepared["document"]["id_external"],netto=f"{100*number}.00",
        tax=f"{23*number}.00",total=f"{123*number}.00",total_composed=f"{123*number}.00")
    out["invoicecontents"]["0"]["invoicecontent"].update(parent={"id":"8101"},discount="0")
    for index in range(number):
        out["invoicecontents"][str(index+1)]={"invoicecontent":dict(
            id=str(8202+index),parent={"id":"0"},name="Banquet",unit="szt.",count="1.0000",
            unit_count="1.0000",price="100.00",netto="100.00",brutto="123.00",
            discount="0",discount_percent="0",vat_code={"id":"222"})}
    out["vat_contents"]["0"]["vat_content"].update(netto=f"{100*number}.00",
        tax=f"{23*number}.00",brutto=f"{123*number}.00")
    return prepared,out


@pytest.mark.parametrize("number,gross",[(1,110299),(2,122599)])
def test_new_banquet_lines_are_checked_as_complete_positions(number,gross):
    prepared,out=add_banquet_case(number)
    proof=c.verify_created(prepared,out,"8002","130706")
    assert proof["parent"]["full_valuation"]["totals"]["gross_grosze"]==gross
    assert proof["parent"]["document_delta"]["gross_grosze"]==12300*number
    if number==1:
        assert {"line_key":"banquet0","position_id":"8202"} in proof["position_mapping"]
        assert proof["equivalent_position_groups"]==[]
    else:
        assert proof["equivalent_position_groups"]==[
            {"line_keys":["banquet0","banquet1"],"position_ids":["8202","8203"]}]


def test_extra_zero_position_in_readback_is_not_hidden_by_matching_totals():
    prepared,out=add_banquet_case()
    extra=deepcopy(out["invoicecontents"]["1"])
    extra["invoicecontent"].update(id="8999",count="0",unit_count="0",netto="0.00",brutto="0.00")
    out["invoicecontents"]["2"]=extra
    with pytest.raises(c.GroupedDocumentError,match="created_positions_mismatch"):
        c.verify_created(prepared,out,"8002","130706")


@pytest.mark.parametrize("change",["missing","duplicate","wrong_parent","wrong_buyer","not_terminal","cycle"])
def test_incomplete_or_foreign_chain_is_rejected(change):
    normal=invoice()
    prepared=prepare(normal,body_for(normal,qty=1))
    first=correction(prepared)
    normal["corrections"]="1"
    documents=[normal,first]
    if change=="missing": documents=[first]
    elif change=="duplicate": documents=[normal,normal,first]
    elif change=="wrong_parent": first["parent"]={"id":"8999"}
    elif change=="wrong_buyer": first["contractor"]={"id":"7999"}
    elif change=="not_terminal": first["corrections"]="1"
    else: first["id"]="8001"
    with pytest.raises(c.GroupedDocumentError):
        c.project_chain(documents,"130706")


def test_multiple_vat_rate_groups_are_separate_even_with_zero_categories():
    data=invoice(qty="1",price="0.10",net="0.10",vat="0.02",gross="0.12")
    data["invoicecontents"]["0"]["invoicecontent"]["vat_code"]={"id":"222"}
    second=deepcopy(data["invoicecontents"]["0"])
    second["invoicecontent"].update(id="8102",netto="0.10",brutto="0.11",vat_code={"id":"224"})
    data["invoicecontents"]["1"]=second
    data.update(netto="0.20",tax="0.03",total="0.23",total_composed="0.23")
    data["vat_contents"]["1"]={"vat_content":dict(vat_code={"id":"224"},netto="0.10",tax="0.01",brutto="0.11")}
    result=c.project_chain([data],"130706")
    assert result["full_valuation"]["totals"]=={"net_grosze":20,"vat_grosze":3,"gross_grosze":23}
    assert [g["vat_rate_code"] for g in result["full_valuation"]["vat_groups"]]==["23","5"]


def test_unchanged_quantity_and_price_do_not_issue_a_correction():
    with pytest.raises(c.GroupedDocumentError,match="document_no_change"):
        prepare(invoice(),body_for(invoice(),qty=2))


def test_entire_chain_has_one_size_limit(monkeypatch):
    data=invoice()
    monkeypatch.setattr(c,"MAX_BYTES",len(c.canonical(data)))
    with pytest.raises(c.GroupedDocumentError):
        c.project_chain([data],"130706")


def test_new_correction_is_refused_before_creation_when_chain_limit_is_reached(monkeypatch):
    data=invoice()
    body=body_for(data)
    monkeypatch.setattr(c,"MAX_CHAIN",1)
    with pytest.raises(c.GroupedDocumentError,match="document_chain_limit"):
        prepare(data,body)


def test_consistent_but_wrong_header_does_not_replace_calculated_document_total():
    data=invoice()
    data.update(total="980.00",total_composed="980.00")
    with pytest.raises(c.GroupedDocumentError,match="document_header_mismatch"):
        c.project_chain([data],"130706")
