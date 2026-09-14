"""Real Flask routes with the existing bounded transport; synthetic data only."""
from copy import deepcopy
import json
import pytest
import requests
import app as app_module
import grouped_document_contract as c
from test_wo599c2b2_structural_workflow import harness, API_KEY, response
from test_wo601ad_grouped_document_contract import invoice, body_for, prepare, correction

BASE="/api/workflow/grouped-document-correction"
HEADERS={"X-API-Key":API_KEY}


@pytest.fixture
def grouped(harness):
    client,state=harness
    state["parent"]=invoice()
    state["series"]={"id":"71","name":"KOR TEST"}
    body=body_for(state["parent"])
    state["created"]=correction(prepare(state["parent"],body),document_id="9001",position_id="9101")
    state["created"]["fullnumber"]="KOR/TEST/1/2026"
    return client,state,body


def test_source_reads_and_independently_reprojects_minimal_data(grouped):
    client,state,body=grouped
    state["parent"]["irrelevant_private_note"]="SHOULD-NOT-TRANSFER"
    state["parent"]["invoicecontents"]["0"]["invoicecontent"]["contact_log"]="SHOULD-NOT-TRANSFER"
    result=client.post(BASE+"/source",json={"company":"md_test","document_ids":["8001"]},headers=HEADERS)
    assert result.status_code==200
    data=result.get_json()
    assert c.project_chain(data["source_documents"],"130706")==data["parent"]
    assert c.fingerprint(data["parent"])==data["parent_sha256"]
    assert "SHOULD-NOT-TRANSFER" not in result.get_data(as_text=True)
    assert result.headers["Cache-Control"]=="no-store"
    assert len(state["reads"])==1 and state["posts"]==[]


def test_create_once_returns_minimal_readback_provable_without_trusting_success(grouped,capsys):
    client,state,body=grouped
    state["created"]["irrelevant_private_note"]="SHOULD-NOT-TRANSFER"
    result=client.post(BASE,json=body,headers=HEADERS)
    assert result.status_code==200
    data=result.get_json()
    assert data["contract_version"]==2 and data["invoice_id"]=="9001"
    assert c.verify_created(prepare(state["parent"],body),data["readback"],"9001","130706")==data["proof"]
    assert len(state["posts"])==1
    assert state["posts"][0]["timeout"]==30 and state["posts"][0]["allow_redirects"] is False
    wire=state["posts"][0]["json"]["invoices"]["invoice"]
    assert wire["price_type"]=="netto" and wire["auto_send"]==0
    assert wire["invoicecontents"]["0"]["invoicecontent"]["count"]==3
    assert wire["invoicecontents"]["0"]["invoicecontent"]["discount"]==0
    assert "SHOULD-NOT-TRANSFER" not in result.get_data(as_text=True)
    log=capsys.readouterr()
    assert "Synthetic test company" not in log.out+log.err


@pytest.mark.parametrize("endpoint",["","/source"])
def test_api_key_is_required_before_reading_and_creating(grouped,endpoint):
    client,state,body=grouped
    result=client.post(BASE+endpoint,json=body)
    assert result.status_code==401
    assert state["reads"]==state["posts"]==state["tokens"]==[]


@pytest.mark.parametrize("kind",["missing","duplicate","wrong_type","unknown_company","duplicate_key","extra","huge"])
def test_source_input_is_bounded_and_closed_before_provider(grouped,kind):
    client,state,_=grouped
    body={"company":"md_test","document_ids":["8001"]}
    raw=None
    if kind=="missing": body.pop("document_ids")
    elif kind=="duplicate": body["document_ids"]*=2
    elif kind=="wrong_type": body["document_ids"]=[8001]
    elif kind=="unknown_company": body["company"]="whatever"
    elif kind=="extra": body["url"]="https://example.invalid"
    elif kind=="huge": raw=b" "*8193
    else: raw=b'{"company":"md","company":"test","document_ids":["8001"]}'
    result=client.post(BASE+"/source",data=raw if raw is not None else json.dumps(body),
                       content_type="application/json",headers=HEADERS)
    assert result.status_code==409
    assert state["reads"]==state["posts"]==[]


@pytest.mark.parametrize("fault",["parent_drift","series_drift","wrong_version","wrong_math","wrong_id","missing_line"])
def test_pre_create_refusal_never_posts(grouped,fault):
    client,state,body=grouped
    if fault=="parent_drift": state["parent"]["contractor_detail"]["name"]="Changed synthetic"
    elif fault=="series_drift": state["series"]["name"]="Changed"
    elif fault=="wrong_version": body["contract_version"]=1
    elif fault=="wrong_math": body["document_delta"]["gross_grosze"]+=1
    elif fault=="wrong_id": body["source_document_ids"]=["7999"]
    else: body["positions"]=[]
    result=client.post(BASE,json=body,headers=HEADERS)
    assert result.status_code>=400
    assert result.get_json()["outcome"]=="rejected" and state["posts"]==[]


@pytest.mark.parametrize("behavior,outcome",[
    (requests.Timeout("SENSITIVE-FAKE-PAYLOAD"),"unknown"),
    (response(500,{"error":"SENSITIVE-FAKE-PAYLOAD"}),"unknown"),
    (response(302,{}),"unknown"),(response(200,{}),"unknown"),
    (response(400,{"error":"SENSITIVE-FAKE-PAYLOAD"}),"rejected"),
])
def test_uncertain_create_is_once_and_does_not_leak(grouped,behavior,outcome,capsys):
    client,state,body=grouped
    state["create_response"]=behavior
    result=client.post(BASE,json=body,headers=HEADERS)
    assert result.status_code==502
    assert result.get_json()["outcome"]==outcome
    assert len(state["posts"])==1
    log=capsys.readouterr()
    assert "SENSITIVE-FAKE-PAYLOAD" not in result.get_data(as_text=True)+log.out+log.err


@pytest.mark.parametrize("fault",["read_unavailable","wrong_price","wrong_total","wrong_buyer","missing_number","wrong_parent"])
def test_known_document_id_survives_all_readback_failures(grouped,fault):
    client,state,body=grouped
    if fault=="read_unavailable": state["read_error"]="9001"
    elif fault=="wrong_price": state["created"]["invoicecontents"]["0"]["invoicecontent"]["price"]="1.00"
    elif fault=="wrong_total": state["created"]["total"]="490.01"
    elif fault=="wrong_buyer": state["created"]["contractor_detail"]["name"]="Wrong synthetic"
    elif fault=="missing_number": state["created"].pop("fullnumber")
    else: state["created"]["parent"]={"id":"8999"}
    result=client.post(BASE,json=body,headers=HEADERS)
    assert result.status_code==502
    assert result.get_json()["outcome"]=="created_unverified"
    assert result.get_json()["document_id"]=="9001"
    assert len(state["posts"])==1

def test_oauth_refusal_does_not_fall_back_to_another_tenant(grouped,monkeypatch):
    client,state,body=grouped
    monkeypatch.setattr(app_module,"_pinned_recovery_company_id",lambda company:None)
    result=client.post(BASE,json=body,headers=HEADERS)
    assert result.status_code==503
    assert result.get_json()["outcome"]=="rejected"
    assert state["reads"]==state["posts"]==[]


def test_ambiguous_create_envelope_keeps_known_id_without_claiming_success(grouped):
    client,state,body=grouped
    state["create_response"]=response(200,{"invoices":{
        "0":{"invoice":{"id":"9001"}},"1":{"invoice":{"id":"9002"}}}})
    result=client.post(BASE,json=body,headers=HEADERS)
    assert result.status_code==502
    assert result.get_json()["outcome"]=="created_unverified"
    assert result.get_json()["document_id"]=="9001"
    assert len(state["posts"])==1
