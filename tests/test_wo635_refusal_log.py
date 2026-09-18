"""A refused grouped document names its failing check in the log (WO-635).

The answer to the caller must not change: 502 `first_invoice_unverified` and
409 `reconciliation_unverified` stay exactly as they were. What changes is that
the server stops being silent about which of the checks disagreed.
"""
import pytest
import document_refusal_log as refusal_log
from test_wo599c2b2_structural_workflow import harness, API_KEY
from test_wo601ad_first_invoice_workflow import first, PATH, HEADERS

RECONCILE = PATH + "/reconcile"
HOSTILE_NAME = "Jan Kowalski jan.kowalski@test.example.pl"


def lines(capsys):
    captured = capsys.readouterr()
    text = captured.out + captured.err
    return text, [row for row in text.splitlines() if row.startswith(refusal_log.PREFIX)]


def test_wo635_an_unverified_first_invoice_names_the_failing_check_and_keeps_its_answer(first, capsys):
    client, state, value = first
    state["created"]["alreadypaid"] = "980.00"
    # Act
    result = client.post(PATH, json=value, headers=HEADERS)
    assert result.status_code == 502 and result.get_json()["outcome"] == "created_unverified"
    assert result.get_json()["document_id"] == "9001"
    _, found = lines(capsys)
    assert found == ["[document-bridge] refused stage=first_invoice_create "
                     "reason=created_payment_mismatch exc=grouped_document_error document=9001"]


def test_wo635_an_unverified_reconciliation_names_the_failing_check_and_keeps_its_answer(first, capsys):
    client, state, value = first
    state["created"]["total_composed"] = "0.01"
    # Act
    result = client.post(RECONCILE, json=dict(request=value, document_id="9001"), headers=HEADERS)
    assert result.status_code == 409 and result.get_json()["error"] == "reconciliation_unverified"
    _, found = lines(capsys)
    assert found == ["[document-bridge] refused stage=reconcile "
                     "reason=document_composed_mismatch exc=grouped_document_error document=9001"]


def test_wo635_a_reconciliation_refused_before_the_identifier_is_read_still_logs(first, capsys):
    client, state, value = first
    # Act
    result = client.post(RECONCILE + "?company=md", json=dict(request=value, document_id="9001"),
                         headers=HEADERS)
    assert result.status_code == 409
    _, found = lines(capsys)
    assert found == ["[document-bridge] refused stage=reconcile reason=invalid_grouped_contract "
                     "exc=grouped_document_error"]


def test_wo635_a_settled_document_writes_no_refusal_line(first, capsys):
    client, state, value = first
    # Act
    result = client.post(PATH, json=value, headers=HEADERS)
    assert result.status_code == 200
    _, found = lines(capsys)
    assert found == []


def test_wo635_a_rejected_request_logs_before_the_provider_is_touched(first, capsys):
    """An underfunded body is refused by `decode`, which flattens its own reason.

    The line still proves the refusal happened before the single create POST,
    which is what matters for telling `nothing was issued` apart from
    `something was issued and could not be confirmed`.
    """
    client, state, value = first
    value["settled_grosze"] = 97998
    # Act
    result = client.post(PATH, json=value, headers=HEADERS)
    assert result.status_code == 502 and state["posts"] == []
    _, found = lines(capsys)
    assert found == ["[document-bridge] refused stage=first_invoice_create "
                     "reason=invalid_request exc=grouped_document_error"]


def test_wo635_a_refusal_line_carries_no_customer_data(first, capsys):
    client, state, value = first
    state["created"]["contractor_detail"]["name"] = HOSTILE_NAME
    # Act
    result = client.post(PATH, json=value, headers=HEADERS)
    assert result.status_code == 502
    text, found = lines(capsys)
    assert len(found) == 1 and "created_party_mismatch" in found[0]
    for secret in (HOSTILE_NAME, "jan.kowalski", "test.example.pl", "Kowalski"):
        assert secret not in "\n".join(found)


def test_wo635_a_failing_emitter_never_changes_the_answer(first, monkeypatch):
    client, state, value = first
    state["created"]["alreadypaid"] = "980.00"

    def boom(_exc):
        raise RuntimeError("SYNTHETIC-EMITTER-FAILURE")

    monkeypatch.setattr(refusal_log, "_safe_class", boom)
    # Act
    result = client.post(PATH, json=value, headers=HEADERS)
    assert result.status_code == 502 and result.get_json()["outcome"] == "created_unverified"


@pytest.mark.parametrize("base,expected", [
    (RuntimeError, "runtime_error"),
    (ValueError, "value_error"),
    (Exception, "other"),
])
def test_wo635_an_exception_class_built_at_runtime_cannot_reach_the_log(base, expected, capsys):
    hostile = type("Err_jan_kowalski_test_example_pl", (base,), {})
    # Act
    refusal_log.log_refusal(hostile("created_payment_mismatch"), stage="reconcile")
    text, found = lines(capsys)
    assert found == [f"[document-bridge] refused stage=reconcile "
                     f"reason=created_payment_mismatch exc={expected}"]
    assert "kowalski" not in text.lower()


@pytest.mark.parametrize("reason", [
    "DROP TABLE invoices", "duplicate key value violates unique constraint",
    "Jan Kowalski", "", "   ", "a", None, 17, "created payment mismatch",
])
def test_wo635_a_reason_outside_its_shape_is_not_printed_verbatim(reason, capsys):
    # Act
    refusal_log.log_refusal(ValueError(reason), stage="reconcile")
    text, found = lines(capsys)
    assert found == ["[document-bridge] refused stage=reconcile reason=unnamed exc=value_error"]
    for dangerous in ("DROP", "TABLE", "duplicate", "constraint", "Kowalski", "payment mismatch"):
        assert dangerous not in text


def test_wo635_an_exception_without_arguments_is_named_unnamed(capsys):
    # Act
    refusal_log.log_refusal(ValueError(), stage="first_invoice_create")
    _, found = lines(capsys)
    assert found == ["[document-bridge] refused stage=first_invoice_create "
                     "reason=unnamed exc=value_error"]


@pytest.mark.parametrize("stage", ["settle", "", None, "RECONCILE", "reconcile;rm -rf /"])
def test_wo635_a_stage_outside_the_known_set_is_not_printed_verbatim(stage, capsys):
    # Act
    refusal_log.log_refusal(ValueError("create_unverified"), stage=stage)
    _, found = lines(capsys)
    assert found == ["[document-bridge] refused stage=unnamed reason=create_unverified exc=value_error"]


@pytest.mark.parametrize("document_id", ["../9001", "9001; DROP TABLE", "abc", "", True, -1])
def test_wo635_a_document_identifier_outside_its_shape_is_not_printed_verbatim(document_id, capsys):
    # Act
    refusal_log.log_refusal(ValueError("create_unverified"), stage="reconcile", document_id=document_id)
    _, found = lines(capsys)
    assert found == ["[document-bridge] refused stage=reconcile reason=create_unverified "
                     "exc=value_error document=unnamed"]


def test_wo635_an_absent_document_identifier_leaves_the_field_out(capsys):
    # Act
    refusal_log.log_refusal(ValueError("readback_unavailable"), stage="reconcile", document_id=None)
    _, found = lines(capsys)
    assert found == ["[document-bridge] refused stage=reconcile "
                     "reason=readback_unavailable exc=value_error"]
