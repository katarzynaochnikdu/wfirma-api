"""Real Flask/requests boundary; official field expectations are independent literals."""
import pytest
from test_wo599c2b2_structural_workflow import harness
from test_wo601ad_first_invoice_workflow import first,PATH,HEADERS
from test_wo601ad_grouped_document_workflow import grouped,BASE


def test_first_flask_post_transmits_exact_documented_metadata_and_retains_verified_readback(first):
    client,state,body=first
    body["sale_date"]="2026-09-10"
    state["created"].update(disposaldate="2026-09-10",paymentdate="2026-09-14",
        paymentmethod="transfer",description="Synthetic event")
    # Act
    result=client.post(PATH,json=body,headers=HEADERS)
    assert result.status_code==200,result.get_json()
    assert len(state["posts"])==1
    wire=state["posts"][0]["json"]["invoices"]["invoice"]
    assert wire["disposaldate"]=="2026-09-10" and wire["date"]=="2026-09-14"
    assert wire["paymentdate"]=="2026-09-14" and wire["paymentmethod"]=="transfer"
    assert wire["series"]=={"id":72}
    assert wire["invoicecontents"]["0"]["invoicecontent"]["vat_code"]=={"id":222}
    assert not {"sale_date","payment_date","paymenttype","series_id"} & set(wire)
    observed=result.get_json()["readback"]
    assert {k:observed[k] for k in ("paymentdate","paymentmethod","description")}=={
        "paymentdate":"2026-09-14","paymentmethod":"transfer","description":"Synthetic event"}


@pytest.mark.parametrize("field",["paymentdate","paymentmethod","description"])
@pytest.mark.parametrize("fault",["missing","wrong"])
def test_provider_lost_metadata_preserves_known_document_and_never_reposts(first,field,fault):
    client,state,body=first
    if fault=="missing":state["created"].pop(field)
    else:state["created"][field]="wrong"
    # Act
    result=client.post(PATH,json=body,headers=HEADERS)
    assert result.status_code==502 and result.get_json()["outcome"]=="created_unverified"
    assert result.get_json()["document_id"]=="9001" and len(state["posts"])==1


def test_grouped_correction_transmits_series_and_vat_relation_without_a_payment(grouped):
    client,state,body=grouped
    # Act
    result=client.post(BASE,json=body,headers=HEADERS)
    assert result.status_code==200,result.get_json()
    assert len(state["posts"])==1
    wire=state["posts"][0]["json"]["invoices"]["invoice"]
    assert wire["series"]=={"id":71} and "series_id" not in wire
    line=wire["invoicecontents"]["0"]["invoicecontent"]
    assert line["vat_code"]=={"id":222} and "vat" not in line
    assert not {"alreadypaid","alreadypaid_initial","payment"} & set(wire)
