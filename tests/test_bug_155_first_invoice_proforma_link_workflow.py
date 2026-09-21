"""BUG-155: the grouped first invoice sends and proves the proforma link (v2 only).

Actual Flask, mocked bounded provider I/O, synthetic data only.
"""
import pytest
import first_invoice_contract as n
from test_wo599c2b2_structural_workflow import harness
from test_wo601ad_first_invoice_workflow import first, PATH, HEADERS
from test_wo601ad_first_invoice_contract import prepare, readback


def linked(value, state, proforma_id="7777"):
    value.update(contract_version=n.LINKED_VERSION, proforma_id=proforma_id)
    state["created"] = readback(prepare(value))
    state["created"]["id"] = "9001"
    return value


def test_bug_155_v2_invoice_is_posted_with_the_order_link_and_echoes_v2(first):
    client, state, value = first
    value = linked(value, state)
    # Act
    result = client.post(PATH, json=value, headers=HEADERS)
    assert result.status_code == 200, result.get_json()
    data = result.get_json()
    assert state["posts"][0]["json"]["invoices"]["invoice"]["order"] == {"id": 7777}
    assert data["contract_version"] == 2 and data["readback"]["order"] == {"id": "7777"}
    assert n.verify_created(prepare(value), data["readback"], "9001", "130706") == data["proof"]


def test_bug_155_v1_invoice_is_posted_and_answered_exactly_as_before(first):
    client, state, value = first
    state["created"]["order"] = {"id": "7777"}
    # Act
    result = client.post(PATH, json=value, headers=HEADERS)
    assert result.status_code == 200, result.get_json()
    data = result.get_json()
    assert "order" not in state["posts"][0]["json"]["invoices"]["invoice"]
    assert data["contract_version"] == 1 and "order" not in data["readback"]


@pytest.mark.parametrize("returned", [None, {"id": "0"}, {"id": "7778"}])
def test_bug_155_v2_invoice_without_the_link_on_readback_is_created_unverified(first, returned):
    client, state, value = first
    value = linked(value, state)
    if returned is None:
        del state["created"]["order"]
    else:
        state["created"]["order"] = returned
    # Act
    result = client.post(PATH, json=value, headers=HEADERS)
    assert result.status_code == 502 and result.get_json()["outcome"] == "created_unverified"
    assert result.get_json()["document_id"] == "9001" and len(state["posts"]) == 1


def test_bug_155_v2_reconcile_proves_the_link_without_any_create(first):
    client, state, value = first
    value = linked(value, state)
    # Act
    result = client.post(PATH + "/reconcile", json=dict(request=value, document_id="9001"), headers=HEADERS)
    assert result.status_code == 200, result.get_json()
    data = result.get_json()
    assert data["contract_version"] == 2 and data["readback"]["order"] == {"id": "7777"}
    assert state["posts"] == []


def test_bug_155_v2_reconcile_of_an_unlinked_invoice_is_not_confirmation(first):
    client, state, value = first
    value = linked(value, state)
    del state["created"]["order"]
    # Act
    result = client.post(PATH + "/reconcile", json=dict(request=value, document_id="9001"), headers=HEADERS)
    assert result.status_code == 409 and state["posts"] == []
