"""First invoice must match the full NET document and actually settled amount."""
from copy import deepcopy
import pytest
import first_invoice_contract as n
from test_wo601ad_grouped_document_contract import invoice


def body():
    rows=[dict(line_key="conference",name="Conference",unit="szt.",quantity=2,
        unit_net_grosze=39837,vat_rate_code="23")]
    return dict(contract_version=1,calculation_version=n.c.money.CALCULATION_VERSION,
        company="md_test",change_id="synthetic-first-1",intent_sha256="a"*64,
        issue_date="2026-09-14",sale_date="2026-09-14",series_id="72",series_name="FV TEST",
        description="Synthetic event",price_model="netto",currency="PLN",positions=rows,
        after_valuation=n.c.valuation(rows),settled_grosze=97999,
        buyer=dict(id="7001",detail=n.c.party_detail(invoice()["contractor_detail"])),receiver=None)


def prepare(value=None):
    value=body() if value is None else value
    return n.prepare(value,"130706",dict(id="72",name="FV TEST"),buyer=value["buyer"],receiver=value["receiver"])


def readback(prepared):
    """Synthetic provider response. Test assertions use independent literal cents."""
    document=prepared["document"]
    totals=prepared["after_valuation"]["totals"]
    result=invoice()
    m=n.c.money_text
    result.update(fullnumber="FV/TEST/1/2026",series={"id":"72"},id_external=document["id_external"],
        contractor={"id":prepared["buyer"]["id"]},contractor_detail=deepcopy(prepared["buyer"]["detail"]),
        date=document["date"],disposaldate=document["disposaldate"],paymentstate="paid",
        paymentdate=document["paymentdate"],paymentmethod=document["paymentmethod"],description=document["description"],
        alreadypaid=m(totals["gross_grosze"]),remaining="0.00",
        netto=m(totals["net_grosze"]),tax=m(totals["vat_grosze"]),total=m(totals["gross_grosze"]),
        total_composed=m(totals["gross_grosze"]),invoicecontents={},vat_contents={})
    if prepared["receiver"] is not None:
        result.update(contractor_receiver={"id":prepared["receiver"]["id"]},
            contractor_detail_receiver=deepcopy(prepared["receiver"]["detail"]))
    ids={code:key for key,code in n.c.VAT_IDS.items()}
    rates=dict(n.c.money._VAT_RATES)
    for i,p in enumerate(prepared["positions"]):
        net=p["quantity"]*p["unit_net_grosze"]
        result["invoicecontents"][str(i)]={"invoicecontent":dict(id=str(8101+i),parent={"id":"0"},
            name=p["name"],unit=p["unit"],count=str(p["quantity"])+".0000",unit_count=str(p["quantity"])+".0000",
            price=m(p["unit_net_grosze"]),netto=m(net),brutto=m(net+(net*rates[p["vat_rate_code"]]+50)//100),
            discount="0",discount_percent="0",vat_code={"id":ids[p["vat_rate_code"]]})}
    for i,p in enumerate(prepared["after_valuation"]["vat_groups"]):
        result["vat_contents"][str(i)]={"vat_content":dict(vat_code={"id":ids[p["vat_rate_code"]]},
            netto=m(p["net_grosze"]),tax=m(p["vat_grosze"]),brutto=m(p["gross_grosze"]))}
    return result


def test_first_grouped_invoice_marks_exact_97999_not_two_times_49000_as_paid():
    before=body()
    # Act
    prepared=prepare(before)
    assert prepared["document"]["alreadypaid_initial"]=="979.99"
    assert prepared["document"]["type"]=="normal" and "parent_id" not in prepared["document"]
    assert prepared["document"]["invoicecontents"]["0"]["invoicecontent"]==dict(
        name="Conference",unit="szt.",count=2,price="398.37",vat_code={"id":222},discount=0,discount_percent=0)
    proof=n.verify_created(prepared,readback(prepared),"8001","130706")
    assert proof["paid_grosze"]==97999
    assert proof["position_mapping"]==[dict(line_key="conference",position_id="8101")]
    assert before==body()


def test_excess_real_payment_is_not_written_as_invoice_payment_or_discarded():
    value=body()
    value["settled_grosze"]=100000
    # Act
    prepared=prepare(value)
    assert prepared["document"]["alreadypaid_initial"]=="979.99"
    assert value["settled_grosze"]==100000  # no ledger mutation


@pytest.mark.parametrize("rate,net,vat,gross",[("23",159348,36650,195998),
    ("8",159348,24699,184047),("5",159348,22309,181657),("0",159348,18325,177673),
    ("zw",159348,18325,177673),("np",159348,18325,177673)])
def test_mixed_rates_use_document_groups_and_preserve_fiscal_categories(rate,net,vat,gross):
    value=body()
    value["positions"].append(dict(value["positions"][0],line_key="banquet",name="Banquet",vat_rate_code=rate))
    value["after_valuation"]=n.c.valuation(value["positions"])
    value["settled_grosze"]=gross
    # Act
    prepared=prepare(value)
    assert prepared["after_valuation"]["totals"]==dict(net_grosze=net,vat_grosze=vat,gross_grosze=gross)
    proof=n.verify_created(prepared,readback(prepared),"8001","130706")
    assert proof["paid_grosze"]==gross and len(proof["position_mapping"])==2


def test_identical_fiscal_rows_have_explicit_equivalence_not_invented_person_mapping():
    value=body()
    value["positions"]=[dict(value["positions"][0],quantity=1),dict(value["positions"][0],line_key="other",quantity=1)]
    value["after_valuation"]=n.c.valuation(value["positions"])
    # Act
    prepared=prepare(value)
    proof=n.verify_created(prepared,readback(prepared),"8001","130706")
    assert proof["position_mapping"]==[]
    assert proof["equivalent_position_groups"]==[dict(line_keys=["conference","other"],position_ids=["8101","8102"])]
    assert proof["paid_grosze"]==97999


@pytest.mark.parametrize("field,value",[("contract_version",True),("company","other"),("currency","EUR"),
    ("price_model","brutto"),("settled_grosze",97998),("settled_grosze",True),("settled_grosze",97999.0),
    ("intent_sha256","x"),("issue_date","tomorrow"),("sale_date","2026-09-15"),("series_id",72),
    ("description",""),("positions",[])])
def test_malformed_or_unfunded_first_invoice_is_refused(field,value):
    request=body()
    request[field]=value
    # Act
    with pytest.raises(n.c.GroupedDocumentError):prepare(request)


@pytest.mark.parametrize("field,value",[("quantity",True),("quantity",0),("quantity",1.5),
    ("unit_net_grosze",-1),("unit_net_grosze",39837.0),("vat_rate_code","unknown"),("name","line\ninjection")])
def test_untrusted_line_never_reaches_first_invoice_builder(field,value):
    request=body()
    request["positions"][0][field]=value
    # Act
    with pytest.raises(n.c.GroupedDocumentError):prepare(request)


@pytest.mark.parametrize("fault",["buyer","receiver","total","paid","remaining","state","discount",
    "date","sale_date","series","external","parent","company","duplicate_line","missing_number"])
def test_independent_readback_rejects_wrong_identity_cash_and_fiscal_state(fault):
    prepared=prepare()
    value=readback(prepared)
    company="130706"
    if fault=="buyer":value["contractor_detail"]["name"]="Other synthetic"
    elif fault=="receiver":
        value["contractor_receiver"]={"id":"7002"}
        value["contractor_detail_receiver"]=deepcopy(value["contractor_detail"])
    elif fault=="total":value["total"]="980.00"
    elif fault=="paid":value["alreadypaid"]="980.00"
    elif fault=="remaining":value["remaining"]="0.01"
    elif fault=="state":value["paymentstate"]="unpaid"
    elif fault=="discount":value["invoicecontents"]["0"]["invoicecontent"]["discount"]="1"
    elif fault=="date":value["date"]="2026-09-15"
    elif fault=="sale_date":value["disposaldate"]="2026-09-15"
    elif fault=="series":value["series"]={"id":"73"}
    elif fault=="external":value["id_external"]="other"
    elif fault=="parent":value["parent"]={"id":"7000"}
    elif fault=="company":company="130707"
    elif fault=="missing_number":value.pop("fullnumber")
    else:value["invoicecontents"]["1"]=deepcopy(value["invoicecontents"]["0"])
    # Act
    with pytest.raises(n.c.GroupedDocumentError):n.verify_created(prepared,value,"8001",company)


def test_receiver_and_fresh_party_snapshot_are_required_on_both_sides():
    value=body()
    value["receiver"]=dict(id="7002",detail=dict(value["buyer"]["detail"],name="Synthetic recipient",role="2"))
    prepared=prepare(value)
    # Act
    proof=n.verify_created(prepared,readback(prepared),"8001","130706")
    assert proof["parent"]["receiver_id"]=="7002"
    with pytest.raises(n.c.GroupedDocumentError):
        n.prepare(value,"130706",dict(id="72",name="FV TEST"),buyer=value["buyer"],receiver=None)
