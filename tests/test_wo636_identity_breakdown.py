"""A failed identity check names the part that disagrees (WO-636).

`created_identity_mismatch` compares four things at once. Both production
settlements of 2026-09-18 died on it and the single name could not tell a
dropped marker apart from a document filed under another series.
"""
import pytest
import document_refusal_log as refusal_log
from test_wo599c2b2_structural_workflow import harness, API_KEY
from test_wo601ad_first_invoice_workflow import first, PATH, HEADERS

RECONCILE = PATH + "/reconcile"
MARKER_LENGTH = 32  # "nf1:" + a digest, cut to what the provider stores (WO-637)
HOSTILE_NAME = "Jan Kowalski jan.kowalski@test.example.pl"


def identity(capsys):
    captured = capsys.readouterr()
    text = captured.out + captured.err
    return text, [row for row in text.splitlines() if row.startswith(refusal_log.PREFIX + " identity")]


@pytest.mark.parametrize("fault,expected", [
    ("marker_dropped", "external_key"),
    ("marker_replaced", "external_key"),
    ("other_series", "series"),
    ("other_document", "document_id"),
    ("number_withheld", "fullnumber"),
])
def test_wo636_a_failed_identity_check_names_the_part_that_disagrees(first, capsys, fault, expected):
    client, state, value = first
    if fault == "marker_dropped":state["created"]["id_external"] = ""
    elif fault == "marker_replaced":state["created"]["id_external"] = "nf1:" + "b" * 32
    elif fault == "other_series":state["created"]["series"] = {"id": "71"}
    elif fault == "other_document":state["created"]["id"] = "9002"
    else:state["created"].pop("fullnumber")
    # Act
    result = client.post(PATH, json=value, headers=HEADERS)
    assert result.status_code == 502 and result.get_json()["outcome"] == "created_unverified"
    _, found = identity(capsys)
    assert len(found) == 1
    assert found[0].startswith(f"[document-bridge] identity stage=first_invoice_create disagrees={expected}")
    assert found[0].endswith("document=9001")


def test_wo636_a_dropped_marker_is_told_apart_from_a_truncated_one(first, capsys):
    client, state, value = first
    state["created"]["id_external"] = ""
    # Act
    result = client.post(PATH, json=value, headers=HEADERS)
    assert result.status_code == 502
    _, found = identity(capsys)
    assert found == ["[document-bridge] identity stage=first_invoice_create disagrees=external_key "
                     f"marker_seen=0 marker_sent={MARKER_LENGTH} document=9001"]


def test_wo636_a_truncated_marker_reports_both_lengths(first, capsys):
    client, state, value = first
    state["created"]["id_external"] = state["created"]["id_external"][:20]
    # Act
    result = client.post(PATH, json=value, headers=HEADERS)
    assert result.status_code == 502
    _, found = identity(capsys)
    assert found == ["[document-bridge] identity stage=first_invoice_create disagrees=external_key "
                     f"marker_seen=20 marker_sent={MARKER_LENGTH} document=9001"]


def test_wo636_reconciliation_names_the_part_that_disagrees_too(first, capsys):
    client, state, value = first
    state["created"]["id_external"] = ""
    # Act
    result = client.post(RECONCILE, json=dict(request=value, document_id="9001"), headers=HEADERS)
    assert result.status_code == 409 and result.get_json()["error"] == "reconciliation_unverified"
    _, found = identity(capsys)
    assert found == ["[document-bridge] identity stage=reconcile disagrees=external_key "
                     f"marker_seen=0 marker_sent={MARKER_LENGTH} document=9001"]


def test_wo636_a_refusal_after_the_identity_check_writes_no_breakdown(first, capsys):
    client, state, value = first
    state["created"]["alreadypaid"] = "980.00"
    # Act
    result = client.post(PATH, json=value, headers=HEADERS)
    assert result.status_code == 502
    text, found = identity(capsys)
    assert found == []
    assert "reason=created_payment_mismatch" in text


def test_wo636_a_settled_document_writes_no_breakdown(first, capsys):
    client, state, value = first
    # Act
    result = client.post(PATH, json=value, headers=HEADERS)
    assert result.status_code == 200
    _, found = identity(capsys)
    assert found == []


def test_wo636_a_refusal_before_the_provider_answers_writes_no_breakdown(first, capsys):
    client, state, value = first
    value["settled_grosze"] = 97998
    # Act
    result = client.post(PATH, json=value, headers=HEADERS)
    assert result.status_code == 502 and state["posts"] == []
    _, found = identity(capsys)
    assert found == []


def test_wo636_a_breakdown_carries_no_customer_data(first, capsys):
    client, state, value = first
    state["created"]["id_external"] = ""
    state["created"]["contractor_detail"]["name"] = HOSTILE_NAME
    # Act
    result = client.post(PATH, json=value, headers=HEADERS)
    assert result.status_code == 502
    text, found = identity(capsys)
    assert len(found) == 1
    for secret in (HOSTILE_NAME, "Kowalski", "test.example.pl", "nf1:"):
        assert secret not in "\n".join(found)


def test_wo636_a_failing_breakdown_never_changes_the_answer(first, monkeypatch):
    client, state, value = first
    state["created"]["id_external"] = ""

    def boom(_call):
        raise RuntimeError("SYNTHETIC-BREAKDOWN-FAILURE")

    monkeypatch.setattr(refusal_log, "_attempt", boom)
    # Act
    result = client.post(PATH, json=value, headers=HEADERS)
    assert result.status_code == 502 and result.get_json()["outcome"] == "created_unverified"


@pytest.mark.parametrize("probe", [None, (), ("a", "b"), "text", 17, (1, 2, 3, 4)])
def test_wo636_an_unusable_probe_is_silent_rather_than_raising(probe, capsys):
    import grouped_document_contract as contract
    # Act
    refusal_log.log_identity(contract, probe, stage="reconcile", document_id="9001")
    _, found = identity(capsys)
    assert found == [] or found[0].startswith("[document-bridge] identity stage=reconcile disagrees=")
