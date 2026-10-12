"""A refused `/grouped-document-correction/source` names its reason in the log (WO-996).

BUG-279: two jobs hit this read-only route every five minutes for weeks and got
409 `source_proof_invalid` each time; the bridge wrote nothing, so nobody could
tell which check disagreed. The answer must stay exactly as it was.
"""
import json
import requests
import document_refusal_log as refusal_log
import app as app_module
from test_wo599c2b2_structural_workflow import harness, API_KEY
from test_wo601ad_grouped_document_workflow import grouped, BASE, HEADERS
from test_wo601ad_grouped_document_contract import invoice

SOURCE = BASE + "/source"
HOSTILE = "Jan Kowalski jan.kowalski@test.example.pl"
REQUEST = {"company": "md_test", "document_ids": ["8001"]}


def lines(capsys):
    captured = capsys.readouterr()
    text = captured.out + captured.err
    return text, [row for row in text.splitlines() if row.startswith(refusal_log.PREFIX)]


def test_wo996_source_refused_read_names_stage_reason_and_document_and_keeps_its_answer(grouped, capsys):
    client, state, _ = grouped
    state["read_error"] = "8001"
    # Act
    result = client.post(SOURCE, json=REQUEST, headers=HEADERS)
    assert result.status_code == 409 and result.get_json() == {"success": False, "error": "source_proof_invalid"}
    _, found = lines(capsys)
    assert found == ["[document-bridge] refused stage=correction_source "
                     "reason=source_read_unavailable exc=grouped_document_error document=8001"]


def test_wo996_source_refusal_answer_is_byte_identical_with_and_without_the_emitter(grouped, monkeypatch):
    client, state, _ = grouped
    state["read_error"] = "8001"
    logged = client.post(SOURCE, json=REQUEST, headers=HEADERS)
    monkeypatch.setattr(refusal_log, "log_refusal", lambda *args, **kwargs: None)
    # Act
    silent = client.post(SOURCE, json=REQUEST, headers=HEADERS)
    assert logged.status_code == silent.status_code == 409
    assert logged.get_data() == silent.get_data()


def test_wo996_source_failing_emitter_never_changes_the_answer(grouped, monkeypatch):
    client, state, _ = grouped
    state["read_error"] = "8001"
    baseline = client.post(SOURCE, json=REQUEST, headers=HEADERS)

    def boom(_exc):
        raise RuntimeError("SYNTHETIC-EMITTER-FAILURE")

    monkeypatch.setattr(refusal_log, "_safe_class", boom)
    # Act
    result = client.post(SOURCE, json=REQUEST, headers=HEADERS)
    assert result.status_code == 409 and result.get_data() == baseline.get_data()


def test_wo996_source_request_refused_before_ids_are_known_logs_without_document(grouped, capsys):
    client, state, _ = grouped
    # Act
    result = client.post(SOURCE, json={"company": "md_test", "document_ids": []}, headers=HEADERS)
    assert result.status_code == 409 and state["reads"] == []
    _, found = lines(capsys)
    assert found == ["[document-bridge] refused stage=correction_source "
                     "reason=invalid_grouped_contract exc=grouped_document_error"]


def test_wo996_source_unexpected_failure_logs_as_other_family_and_keeps_502(grouped, monkeypatch, capsys):
    client, state, _ = grouped

    def down(*args, **kwargs):
        raise requests.exceptions.ConnectionError("HTTPSConnectionPool(host='api2.wfirma.pl'): " + HOSTILE)

    monkeypatch.setattr(app_module, "_strict_wfirma_recovery_get", down)
    # Act
    result = client.post(SOURCE, json=REQUEST, headers=HEADERS)
    assert result.status_code == 502 and result.get_json() == {"success": False, "error": "source_read_unavailable"}
    text, found = lines(capsys)
    assert found == ["[document-bridge] refused stage=correction_source reason=unnamed "
                     "exc=connection_error document=8001"]
    for secret in (HOSTILE, "kowalski", "test.example.pl", "wfirma.pl"):
        assert secret not in text.lower()


def test_wo996_source_line_carries_no_customer_data_when_provider_content_is_hostile(grouped, monkeypatch, capsys):
    client, state, _ = grouped
    state["parent"]["contractor_detail"]["name"] = HOSTILE
    state["parent"]["total_composed"] = "999.99"
    state["parent"]["id"] = "7999"
    # Act
    result = client.post(SOURCE, json=REQUEST, headers=HEADERS)
    text, found = lines(capsys)
    assert result.status_code == 409 and len(found) == 1 and "source_read_unavailable" in found[0]
    for secret in (HOSTILE, "kowalski", "test.example.pl", "999.99"):
        assert secret not in text.lower()


def test_wo996_source_settled_read_writes_no_refusal_line(grouped, capsys):
    client, state, _ = grouped
    # Act
    result = client.post(SOURCE, json=REQUEST, headers=HEADERS)
    assert result.status_code == 200
    _, found = lines(capsys)
    assert found == []
