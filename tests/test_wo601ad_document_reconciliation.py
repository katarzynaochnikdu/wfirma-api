"""Reconciliation reads the existing fiscal document, never creates one."""
from copy import deepcopy
import json
import pytest
from test_wo599c2b2_structural_workflow import harness
from test_wo601ad_first_invoice_workflow import first,PATH,HEADERS
from test_wo601ad_grouped_document_workflow import grouped,BASE


@pytest.fixture(params=['first','grouped'])
def case(request):
    client,state,body=request.getfixturevalue(request.param)
    value=dict(request=body,document_id='9001')
    path=PATH if request.param=='first' else BASE
    if request.param=='grouped':value['source_documents']=[deepcopy(state['parent'])]
    return client,state,value,path+'/reconcile'


def test_existing_document_is_read_and_confirmed_without_any_create_or_party_request(case):
    client,state,body,path=case
    state['created']['private_note']='PRIVATE-CANARY'
    # Act
    result=client.post(path,json=body,headers=HEADERS)
    assert result.status_code==200,result.get_json()
    assert result.get_json()['invoice_id']=='9001'
    assert result.headers['Cache-Control']=='no-store'
    assert [(x['plural'],x['entity_id']) for x in state['reads']]==[('invoices','9001')]
    assert state['posts']==[]
    assert 'PRIVATE-CANARY' not in result.get_data(as_text=True)


@pytest.mark.parametrize('fault',['wrong_key','wrong_amount','wrong_buyer','missing','other_id'])
def test_unmatched_or_missing_existing_document_is_not_confirmation_and_never_issued(case,fault):
    client,state,body,path=case
    if fault=='wrong_key':state['created']['id_external']='different-attempt'
    elif fault=='wrong_amount':state['created']['total_composed']='0.01'
    elif fault=='wrong_buyer':state['created']['contractor_detail']['name']='Other buyer'
    elif fault=='missing':state['read_error']='9001'
    else:state['created']['id']='9002'
    # Act
    result=client.post(path,json=body,headers=HEADERS)
    assert result.status_code==409,result.get_json()
    assert state['posts']==[] and result.get_json()['error']=='reconciliation_unverified'


@pytest.mark.parametrize('fault',['no_auth','query','duplicate','oversized','extra','invalid_id'])
def test_readonly_reconciliation_refuses_untrusted_input_before_provider(case,fault):
    client,state,body,path=case
    headers=HEADERS if fault!='no_auth' else {}
    raw=None
    if fault=='query':path+='?x=1'
    elif fault=='duplicate':raw='{"document_id":"9001","document_id":"9001"}'
    elif fault=='oversized':raw=' '*(24*1024*1024+1)
    elif fault=='extra':body['url']='https://example.invalid/'
    elif fault=='invalid_id':body['document_id']='../9001'
    # Act
    result=client.post(path,data=raw if raw is not None else json.dumps(body),headers=headers,content_type='application/json')
    assert result.status_code>=400
    assert state['posts']==state['reads']==[]
