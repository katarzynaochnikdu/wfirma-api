"""Private grouped normal invoice; actual Flask, mocked bounded provider I/O."""
from copy import deepcopy
import json
import pytest
import requests
import app as app_module
import first_invoice_contract as n
from test_wo599c2b2_structural_workflow import harness,API_KEY,response
from test_wo601ad_first_invoice_contract import body,prepare,readback

PATH="/api/workflow/grouped-first-invoice"
HEADERS={"X-API-Key":API_KEY}


@pytest.fixture
def first(harness,monkeypatch):
    client,state=harness
    value=body()
    state["buyer"]=dict(value["buyer"]["detail"],id=value["buyer"]["id"])
    state["series"]={"id":"72","name":"FV TEST"}
    state["created"]=readback(prepare(value))
    state["created"]["id"]="9001"
    def read(token,**kwargs):
        state["reads"].append(kwargs)
        if state["read_error"]==kwargs["entity_id"]:return None,"unavailable"
        kind=kwargs["plural"]
        result=state["buyer"] if kind=="contractors" else state["series"] if kind=="series" else state["created"]
        return deepcopy(result),None
    monkeypatch.setattr(app_module,"_strict_wfirma_recovery_get",read)
    monkeypatch.setattr(app_module,"wfirma_add_payment",lambda *_:pytest.fail("no extra payment writer"))
    monkeypatch.setattr(app_module,"wfirma_send_invoice_email",lambda *_:pytest.fail("no unverified automatic email"))
    return client,state,value


def test_normal_invoice_is_created_once_and_independently_verified_before_success(first,capsys):
    client,state,value=first
    state["created"]["unrelated_note"]="DO-NOT-SEND"
    # Act
    result=client.post(PATH,json=value,headers=HEADERS)
    assert result.status_code==200,result.get_json()
    data=result.get_json()
    assert data["invoice_id"]=="9001" and data["proof"]["paid_grosze"]==97999
    assert n.verify_created(prepare(value),data["readback"],"9001","130706")==data["proof"]
    assert len(state["posts"])==1
    wire=state["posts"][0]["json"]["invoices"]["invoice"]
    assert wire["type"]=="normal" and wire["alreadypaid_initial"]=="979.99" and wire["auto_send"]==0
    assert wire["invoicecontents"]["0"]["invoicecontent"]["count"]==2
    assert state["posts"][0]["timeout"]==30 and state["posts"][0]["allow_redirects"] is False
    assert [r["plural"] for r in state["reads"]]==["series","contractors","invoices"]
    assert result.headers["Cache-Control"]=="no-store"
    log=capsys.readouterr()
    assert "Synthetic test company" not in log.out+log.err
    assert "DO-NOT-SEND" not in result.get_data(as_text=True)


def test_authentication_happens_before_any_provider_access(first):
    client,state,value=first
    # Act
    result=client.post(PATH,json=value)
    assert result.status_code==401 and state["reads"]==state["posts"]==state["tokens"]==[]


@pytest.mark.parametrize("fault",["buyer_changed","buyer_missing","series_changed","not_funded",
    "wrong_math","currency","duplicate_key","too_large","query","wrong_content"])
def test_rejected_first_invoice_does_not_issue(first,fault):
    client,state,value=first
    raw=None
    path=PATH
    content_type="application/json"
    if fault=="buyer_changed":state["buyer"]["name"]="Other synthetic company"
    elif fault=="buyer_missing":state["read_error"]="7001"
    elif fault=="series_changed":state["series"]["name"]="Other"
    elif fault=="not_funded":value["settled_grosze"]=97998
    elif fault=="wrong_math":value["after_valuation"]["totals"]["gross_grosze"]=98000
    elif fault=="currency":value["currency"]="EUR"
    elif fault=="duplicate_key":raw='{"contract_version":1,"contract_version":1}'
    elif fault=="too_large":raw=" "* (n.c.MAX_BYTES+1)
    elif fault=="query":path+="?company=md"
    else:content_type="text/plain"
    # Act
    result=client.post(path,data=raw if raw is not None else json.dumps(value),content_type=content_type,headers=HEADERS)
    assert result.status_code>=400 and result.get_json()["outcome"]=="rejected"
    assert state["posts"]==[]


@pytest.mark.parametrize("fault",["readback_missing","wrong_paid","wrong_total","wrong_buyer","wrong_date","missing_number"])
def test_first_invoice_known_id_survives_unverified_readback_without_a_second_post(first,fault):
    client,state,value=first
    if fault=="readback_missing":state["read_error"]="9001"
    elif fault=="wrong_paid":state["created"]["alreadypaid"]="980.00"
    elif fault=="wrong_total":state["created"]["total"]="980.00"
    elif fault=="wrong_buyer":state["created"]["contractor_detail"]["name"]="Other synthetic"
    elif fault=="wrong_date":state["created"]["date"]="2026-09-15"
    else:state["created"].pop("fullnumber")
    # Act
    result=client.post(PATH,json=value,headers=HEADERS)
    assert result.status_code==502 and result.get_json()["outcome"]=="created_unverified"
    assert result.get_json()["document_id"]=="9001" and len(state["posts"])==1


@pytest.mark.parametrize("behavior,outcome",[
    (requests.Timeout("SYNTHETIC-PRIVATE"),"unknown"),(response(500,{}),"unknown"),
    (response(302,{}),"unknown"),(response(200,{}),"unknown"),(response(400,{}),"rejected")])
def test_uncertain_first_invoice_is_never_retried_or_leaked(first,behavior,outcome,capsys):
    client,state,value=first
    state["create_response"]=behavior
    # Act
    result=client.post(PATH,json=value,headers=HEADERS)
    assert result.status_code==502 and result.get_json()["outcome"]==outcome
    assert len(state["posts"])==1
    log=capsys.readouterr()
    assert "SYNTHETIC-PRIVATE" not in result.get_data(as_text=True)+log.out+log.err


@pytest.mark.parametrize('fault',['ok','timeout','http','empty','duplicate','oversized','readback'])
def test_explicit_new_buyer_is_created_once_before_invoice_and_unknown_is_not_retried(first,monkeypatch,fault,capsys):
    client,state,value=first
    value['buyer']['id']=None
    original_post=app_module.requests.post
    calls=[]
    class PartyResponse:
        status_code=500 if fault=='http' else 200
        headers={'Content-Type':'application/json'}
        def iter_content(self,chunk_size):
            if fault=='oversized':yield b' '*(app_module.WFIRMA_RECOVERY_RESPONSE_MAX_BYTES+1);return
            data={} if fault=='empty' else {'contractors':{'0':{'contractor':{'id':'7001'}}}}
            if fault=='duplicate':data['contractors']['1']={'contractor':{'id':'7002'}}
            yield json.dumps(data).encode()
        def close(self):calls.append('close')
    def post(url,**kwargs):
        if '/contractors/add' not in url:
            calls.append('invoice')
            return original_post(url,**kwargs)
        calls.append('contractor')
        assert kwargs['timeout']==10 and kwargs['allow_redirects'] is False and kwargs['stream'] is True
        assert kwargs['params']['company_id']=='130706'
        assert kwargs['json']['contractors']['contractor']=={k:v for k,v in value['buyer']['detail'].items() if k!='role' and v!=''}
        if fault=='timeout':raise requests.Timeout('PRIVATE-PARTY')
        return PartyResponse()
    monkeypatch.setattr(app_module.requests,'post',post)
    if fault=='readback':state['buyer']['name']='Wrong new party'
    # Act
    result=client.post(PATH,json=value,headers=HEADERS)
    assert calls.count('contractor')==1
    if fault=='ok':
        assert result.status_code==200,result.get_json()
        assert calls==['contractor','close','invoice']
        assert result.get_json()['proof']['parent']['contractor_id']=='7001'
    else:
        assert result.status_code==502 and result.get_json()['outcome']=='unknown'
        assert 'invoice' not in calls and state['posts']==[]
    log=capsys.readouterr()
    assert 'PRIVATE-PARTY' not in result.get_data(as_text=True)+log.out+log.err
