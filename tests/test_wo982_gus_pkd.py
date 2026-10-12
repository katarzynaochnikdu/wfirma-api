"""WO-982 — the GUS lookup can also return the entity's predominant PKD.

Why: the portal creates a company in Zoho right after a purchase and has to
decide its category from the main (predominant) PKD code. Until now this
service only ran `Zaloguj` + `DaneSzukajPodmioty`, which carry no PKD at all.

The contract:
* `gus_lookup_nip(nip, with_pkd=True)` makes ONE extra call in the same GUS
  session - `DanePobierzPelnyRaport` for the REGON of the first record; the
  report name follows the record type (`P` -> `BIR11OsPrawnaPkd`,
  `F` -> `BIR11OsFizycznaPkd`); any other type or a missing REGON means no call;
* the call is best effort: its own short timeout, no retry, and every failure
  ends as "no PKD" while the lookup still returns the record it found;
* the call is not even started once login + search took more than 15 s - the
  portal waits 30 s for the whole answer and must not lose the address;
* the first record gains `pkdPrzewazajace`, `pkdKod`, `pkdNazwa` and
  `pkdGlowneJednoznaczne` - the service returns data only, it knows no
  business rule;
* without the flag nothing changes: no extra GUS call and no `pkd*` key. The
  contractor / invoice workflow calls the same function without the flag.

Real Flask handlers and the real lookup; the only I/O is a controlled stand-in
for the GUS SOAP endpoint - no network at all. All data is invented for this
file: the tax id has an impossible tax-office prefix, the PKD codes and names
are entries of the public classification.
"""
from __future__ import annotations

import html
import inspect
import os
import re
import sys
from dataclasses import dataclass

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Importing app.py runs its startup hooks; empty values set BEFORE the import
# keep the tests away from a database and from the token/e-mail monitor.
os.environ["DATABASE_URL"] = ""
os.environ["MAKE_WEBHOOK_SEND_EMAIL_REQUEST"] = ""
os.environ["RENDER_EMAIL_KEY_SEND_REQUEST"] = ""

import app as app_module  # noqa: E402

ROUTE = "/api/gus/validate-nip"
NAME_ROUTE = "/api/gus/name-by-nip"
REGON_TOKEN = "wo982-synthetic-regon-token"
GUS_KEY = "wo982-synthetic-gus-key"
HEADERS = {"X-API-Key": REGON_TOKEN}
# The fixture forces the GUS TEST host, so even the address is not production.
GUS_URL = "https://wyszukiwarkaregontest.stat.gov.pl/wsBIR/UslugaBIRzewnPubl.svc"
SID = "wo982syntheticsid"

NIP = "0000098200"      # valid checksum, tax-office prefix 000 does not exist
REGON = "000000982"
COMPANY = "Test Sp. z o.o."
SECRET = "wo982-text-that-must-not-reach-the-log"

REPORT = "DanePobierzPelnyRaport"
LEGAL_REPORT = "BIR11OsPrawnaPkd"
PERSON_REPORT = "BIR11OsFizycznaPkd"

LEGAL_KEYS = ("praw_pkdKod", "praw_pkdNazwa", "praw_pkdPrzewazajace")
PERSON_KEYS_UNDERSCORE = ("fiz_pkd_Kod", "fiz_pkd_Nazwa", "fiz_pkd_Przewazajace")
PERSON_KEYS_PLAIN = ("fiz_pkdKod", "fiz_pkdNazwa", "fiz_pkdPrzewazajace")

MEDICAL = {"kod": "8621Z", "nazwa": "Praktyka lekarska ogólna"}
SOFTWARE = {"kod": "6201Z", "nazwa": "Działalność związana z oprogramowaniem"}
FARMING = {"kod": "0111Z", "nazwa": "Uprawa zbóż"}

PKD_KEYS = {"pkdPrzewazajace", "pkdKod", "pkdNazwa", "pkdGlowneJednoznaczne"}
NO_PKD = {"pkdPrzewazajace": [], "pkdKod": "", "pkdNazwa": "", "pkdGlowneJednoznaczne": False}


def row(keys, code, name, predominant, **extra) -> dict:
    """One `<dane>` row of a PKD report under the given key spelling."""
    return dict(zip(keys, (code, name, predominant)), **extra)


def person_row(keys, code, name, predominant, silo="CEIDG") -> dict:
    """A natural-person row also carries the register and the removal date."""
    return row(keys, code, name, predominant,
               fiz_Silos_Symbol=silo, fiz_dataSkresleniaDzialalnosciZRegon="")


LEGAL_ROWS = [
    row(LEGAL_KEYS, SOFTWARE["kod"], SOFTWARE["nazwa"], "0"),
    row(LEGAL_KEYS, MEDICAL["kod"], MEDICAL["nazwa"], "1"),
]


def legacy_record(entity_type="P", regon=REGON) -> dict:
    """The first record exactly as the lookup has always mapped it: 15 keys."""
    return {
        "regon": regon, "nip": NIP, "nazwa": COMPANY, "wojewodztwo": "MAZOWIECKIE",
        "powiat": "Testowy", "gmina": "Testowo", "miejscowosc": "Testowo",
        "kodPocztowy": "00-982", "ulica": "ul. Testowa", "nrNieruchomosci": "9",
        "nrLokalu": "82", "typ": entity_type, "silosId": "6",
        "miejscowoscPoczty": "Testowo", "krs": None,
    }


# ---------------------------------------------------------------------------
# A stand-in for the GUS SOAP endpoint
# ---------------------------------------------------------------------------


def inner_xml(rows) -> str:
    cells = ("".join(f"<{key}>{html.escape(str(value))}</{key}>" for key, value in item.items())
             for item in rows)
    return "<root>" + "".join(f"<dane>{cell}</dane>" for cell in cells) + "</root>"


def soap(operation: str, result: str) -> str:
    """GUS returns the inner document entity-encoded inside `<...Result>`."""
    return (
        '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Body>'
        f'<{operation}Response xmlns="http://CIS/BIR/PUBL/2014/07">'
        f"<{operation}Result>{html.escape(result, quote=False)}</{operation}Result>"
        f"</{operation}Response></s:Body></s:Envelope>"
    )


def mtom(envelope: str) -> str:
    """The multipart wrapping the production endpoint answers with."""
    return (
        "--uuid:wo982+id=1\r\n"
        "Content-ID: <http://tempuri.org/0>\r\n"
        "Content-Transfer-Encoding: 8bit\r\n"
        'Content-Type: application/xop+xml;charset=utf-8;type="application/soap+xml"\r\n'
        "\r\n"
        f"{envelope}\r\n"
        "--uuid:wo982+id=1--\r\n"
    )


def search_reply(entity_type="P", regon=REGON) -> str:
    found = {
        "Regon": regon, "Nip": NIP, "StatusNip": "", "Nazwa": COMPANY,
        "Wojewodztwo": "MAZOWIECKIE", "Powiat": "Testowy", "Gmina": "Testowo",
        "Miejscowosc": "Testowo", "KodPocztowy": "00-982", "Ulica": "ul. Testowa",
        "NrNieruchomosci": "9", "NrLokalu": "82", "Typ": entity_type, "SilosID": "6",
        "DataZakonczeniaDzialalnosci": "", "MiejscowoscPoczty": "Testowo",
    }
    return mtom(soap("DaneSzukajPodmioty", inner_xml([found])))


def report_reply(rows) -> str:
    return mtom(soap(REPORT, inner_xml(rows)))


class Reply:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code, self.text = status_code, text


@dataclass
class Call:
    operation: str
    sid: str | None
    timeout: object
    envelope: str


class FakeGus:
    """Answers the three BIR operations and remembers every call it received.

    It also owns the clock of the lookup: an operation "takes" as long as
    `seconds` says, so a slow register is modelled without any real waiting.
    """

    def __init__(self) -> None:
        self.calls: list[Call] = []
        self.sleeps: list[float] = []
        self.search: object = search_reply()
        self.report: object = report_reply(LEGAL_ROWS)
        self.now = 1000.0
        self.seconds = {"Zaloguj": 0.0, "DaneSzukajPodmioty": 0.0, REPORT: 0.0}

    def clock(self) -> float:
        return self.now

    def post(self, url, data=None, headers=None, timeout=None, **kwargs):
        if url != GUS_URL:
            pytest.fail(f"WO-982 test blocked a call outside the GUS stand-in: {url}")
        envelope = data.decode("utf-8")
        operation = re.search(r"IUslugaBIRzewnPubl/(\w+)</wsa:Action>", envelope).group(1)
        self.calls.append(Call(operation, (headers or {}).get("sid"), timeout, envelope))
        self.now += self.seconds.get(operation, 0.0)
        if operation == "Zaloguj":
            return Reply(200, soap("Zaloguj", SID))
        answer = {"DaneSzukajPodmioty": self.search, REPORT: self.report}.get(operation)
        if answer is None:
            pytest.fail(f"WO-982 test blocked an unexpected GUS operation: {operation}")
        if isinstance(answer, BaseException):
            raise answer
        return answer if isinstance(answer, Reply) else Reply(200, answer)

    @property
    def operations(self) -> list[str]:
        return [call.operation for call in self.calls]

    @property
    def reports(self) -> list[Call]:
        return [call for call in self.calls if call.operation == REPORT]


@pytest.fixture
def gus(monkeypatch):
    """The real lookup and the real routes over a stand-in GUS; nothing leaves the process."""
    fake = FakeGus()
    monkeypatch.setattr(app_module, "GUS_API_KEY", GUS_KEY)
    monkeypatch.setattr(app_module, "GUS_USE_TEST", True)
    monkeypatch.setattr(app_module, "REGON_API_KEY_TOKEN", REGON_TOKEN)
    monkeypatch.setattr(app_module.requests, "post", fake.post)
    monkeypatch.setattr(app_module.requests, "get",
                        lambda url, **kwargs: pytest.fail(f"unexpected read: {url}"))
    monkeypatch.setattr(app_module.time, "sleep", fake.sleeps.append)
    monkeypatch.setattr(app_module, "gus_monotonic", fake.clock)
    app_module.app.config.update(TESTING=True)
    return fake


@pytest.fixture
def client(gus):
    return app_module.app.test_client()


def pkd_log_lines(capsys) -> tuple[str, list[str]]:
    captured = capsys.readouterr()
    text = captured.out + captured.err
    return text, [line for line in text.splitlines() if line.startswith("[GUS-PKD]")]


# ---------------------------------------------------------------------------
# 1) The row parser - a pure function, no network
# ---------------------------------------------------------------------------


def test_wo982_parser_legal_entity_report_returns_the_predominant_row():
    # Arrange - a company report: several codes, one marked as predominant.
    rows = [
        row(LEGAL_KEYS, SOFTWARE["kod"], SOFTWARE["nazwa"], "0"),
        row(LEGAL_KEYS, " 8621Z ", "  Praktyka lekarska ogólna ", "1"),
        row(LEGAL_KEYS, "8690E", "Pozostała działalność w zakresie opieki zdrowotnej", "0"),
    ]

    # Act
    result = app_module.parse_gus_pkd_rows(rows)

    # Assert - the code and the name as GUS gave them, only stripped.
    assert result == [MEDICAL]


@pytest.mark.parametrize("keys", [PERSON_KEYS_UNDERSCORE, PERSON_KEYS_PLAIN],
                         ids=["keys_with_underscore", "keys_without_underscore"])
def test_wo982_parser_natural_person_report_reads_both_key_spellings(keys):
    """The widget reads only the spelling without the underscore and leaves a
    sole trader without PKD. Both spellings are accepted here."""
    # Arrange
    rows = [
        person_row(keys, SOFTWARE["kod"], SOFTWARE["nazwa"], "0"),
        person_row(keys, MEDICAL["kod"], MEDICAL["nazwa"], "1"),
    ]

    # Act
    result = app_module.parse_gus_pkd_rows(rows)

    # Assert
    assert result == [MEDICAL]


@pytest.mark.parametrize("rows", [
    [row(LEGAL_KEYS, MEDICAL["kod"], MEDICAL["nazwa"], "0")],
    [{"praw_pkdKod": MEDICAL["kod"], "praw_pkdNazwa": MEDICAL["nazwa"]}],
    [person_row(PERSON_KEYS_UNDERSCORE, MEDICAL["kod"], MEDICAL["nazwa"], "")],
    [row(LEGAL_KEYS, "", "Wiersz bez kodu", "1")],
    [row(LEGAL_KEYS, " . ", "Wiersz z samą kropką", "1")],
    [{"ErrorCode": "4", "ErrorMessagePl": "Nie znaleziono podmiotu"}],
    ["not a row", None, 7],
    [],
    None,
], ids=["flag_zero", "flag_absent", "flag_empty", "code_empty", "code_without_characters",
        "gus_error_row", "rows_of_another_type", "no_rows", "no_report"])
def test_wo982_parser_without_a_usable_predominant_row_returns_nothing(rows):
    # Act
    result = app_module.parse_gus_pkd_rows(rows)

    # Assert
    assert result == []


@pytest.mark.parametrize("flag,expected", [
    ("1", True), (1, True), (" 1 ", True), ("1\n", True),
    ("0", False), (0, False), ("", False), (None, False), ("true", False), ("11", False),
], ids=["text_1", "number_1", "padded_1", "newline_1", "text_0", "number_0", "empty", "none",
        "word_true", "eleven"])
def test_wo982_parser_treats_only_the_value_one_as_predominant(flag, expected):
    # Arrange
    rows = [row(LEGAL_KEYS, MEDICAL["kod"], MEDICAL["nazwa"], flag)]

    # Act
    result = app_module.parse_gus_pkd_rows(rows)

    # Assert
    assert result == ([MEDICAL] if expected else [])


def test_wo982_parser_several_predominant_codes_keeps_all_of_them_in_report_order():
    """A natural person with two registers has one predominant code in each.
    The service does not choose - an ambiguous answer has to stay ambiguous."""
    # Arrange
    rows = [
        person_row(PERSON_KEYS_UNDERSCORE, FARMING["kod"], FARMING["nazwa"], "1", silo="ROLNICZA"),
        person_row(PERSON_KEYS_UNDERSCORE, SOFTWARE["kod"], SOFTWARE["nazwa"], "0"),
        person_row(PERSON_KEYS_UNDERSCORE, MEDICAL["kod"], MEDICAL["nazwa"], "1"),
    ]

    # Act
    fields = app_module.gus_pkd_record_fields(app_module.parse_gus_pkd_rows(rows))

    # Assert - both codes, the first one repeated in the flat fields, and not unambiguous.
    assert fields == {
        "pkdPrzewazajace": [FARMING, MEDICAL],
        "pkdKod": FARMING["kod"],
        "pkdNazwa": FARMING["nazwa"],
        "pkdGlowneJednoznaczne": False,
    }


def test_wo982_parser_the_same_predominant_code_repeated_collapses_to_one_element():
    # Arrange - one code in two registers, the second time written with dots.
    rows = [
        person_row(PERSON_KEYS_UNDERSCORE, MEDICAL["kod"], MEDICAL["nazwa"], "1"),
        person_row(PERSON_KEYS_UNDERSCORE, "86.21.z", "Inny zapis tej samej nazwy", "1", silo="INNE"),
        person_row(PERSON_KEYS_UNDERSCORE, MEDICAL["kod"], MEDICAL["nazwa"], "1", silo="ROLNICZA"),
    ]

    # Act
    fields = app_module.gus_pkd_record_fields(app_module.parse_gus_pkd_rows(rows))

    # Assert - the first spelling wins and one element IS an unambiguous answer.
    assert fields == {
        "pkdPrzewazajace": [MEDICAL],
        "pkdKod": MEDICAL["kod"],
        "pkdNazwa": MEDICAL["nazwa"],
        "pkdGlowneJednoznaczne": True,
    }


def test_wo982_record_fields_without_any_code_are_complete_and_empty():
    # Act
    fields = app_module.gus_pkd_record_fields([])

    # Assert - all four keys, so the caller never has to probe for a single one.
    assert fields == NO_PKD and set(fields) == PKD_KEYS


# ---------------------------------------------------------------------------
# 2) The lookup: one report in the same session, chosen by the record type
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("entity_type,report_name,rows", [
    ("P", LEGAL_REPORT, LEGAL_ROWS),
    ("F", PERSON_REPORT, [person_row(PERSON_KEYS_UNDERSCORE, MEDICAL["kod"], MEDICAL["nazwa"], "1")]),
], ids=["legal_entity", "natural_person"])
def test_wo982_lookup_with_pkd_reads_one_report_in_the_same_session(gus, entity_type, report_name, rows):
    # Arrange
    gus.search = search_reply(entity_type)
    gus.report = report_reply(rows)

    # Act
    records, error = app_module.gus_lookup_nip(NIP, with_pkd=True)

    # Assert - login, search, ONE report; the report rides the session of the search.
    assert error is None
    assert gus.operations == ["Zaloguj", "DaneSzukajPodmioty", REPORT]
    report = gus.reports[0]
    assert report.sid == SID == gus.calls[1].sid
    assert f"<ns:pRegon>{REGON}</ns:pRegon>" in report.envelope
    assert f"<ns:pNazwaRaportu>{report_name}</ns:pNazwaRaportu>" in report.envelope
    # Its own short budget, never the 20 s of the search.
    assert report.timeout == app_module.GUS_PKD_REPORT_TIMEOUT_SECONDS <= 10
    assert gus.calls[1].timeout == app_module.GUS_SOAP_TIMEOUT
    assert records == [dict(
        legacy_record(entity_type),
        pkdPrzewazajace=[MEDICAL], pkdKod=MEDICAL["kod"], pkdNazwa=MEDICAL["nazwa"],
        pkdGlowneJednoznaczne=True,
    )]


def test_wo982_lookup_reads_a_report_that_is_not_wrapped_in_multipart(gus):
    # Arrange - the same answer as a bare SOAP envelope.
    gus.report = soap(REPORT, inner_xml(LEGAL_ROWS))

    # Act
    records, error = app_module.gus_lookup_nip(NIP, with_pkd=True)

    # Assert
    assert error is None and records[0]["pkdPrzewazajace"] == [MEDICAL]


@pytest.mark.parametrize("entity_type,regon", [
    ("LP", REGON), ("", REGON), ("p", REGON), ("P", ""), ("F", "12345"), ("P", "00000098A"),
], ids=["local_unit", "no_type", "lowercase_type", "no_regon", "short_regon", "regon_with_letter"])
def test_wo982_lookup_with_pkd_skips_the_report_without_a_known_type_or_a_regon(gus, entity_type, regon):
    # Arrange
    gus.search = search_reply(entity_type, regon)

    # Act
    records, error = app_module.gus_lookup_nip(NIP, with_pkd=True)

    # Assert - no call at all, the record is returned with the four fields empty.
    assert error is None and REPORT not in gus.operations
    assert records == [dict(legacy_record(entity_type or None, regon or None), **NO_PKD)]


@pytest.mark.parametrize("report", [
    requests.exceptions.ReadTimeout(SECRET),
    requests.exceptions.ConnectionError(SECRET),
    RuntimeError(SECRET),
    Reply(500, "Service Unavailable"),
    Reply(401, ""),
    Reply(200, ""),
    Reply(200, "<html><body>busy</body></html>"),
    Reply(200, f"<s:Envelope><s:Body><{REPORT}Response><{REPORT}Result/></{REPORT}Response></s:Body></s:Envelope>"),
    soap(REPORT, ""),
    soap(REPORT, "<root><dane>"),
    report_reply([{"ErrorCode": "4", "ErrorMessagePl": "Nie znaleziono podmiotu", "Regon": REGON}]),
    report_reply([]),
    report_reply([row(LEGAL_KEYS, MEDICAL["kod"], MEDICAL["nazwa"], "0")]),
], ids=["timeout", "connection_error", "unexpected_exception", "http_500", "http_401", "empty_body",
        "not_soap", "self_closed_result", "blank_result", "broken_xml", "gus_error_row", "no_rows",
        "no_predominant_row"])
def test_wo982_failed_report_leaves_the_found_record_without_pkd(gus, capsys, report):
    # Arrange
    gus.report = report

    # Act
    records, error = app_module.gus_lookup_nip(NIP, with_pkd=True)

    # Assert - the search succeeded, so the lookup succeeds: the record with empty fields.
    assert error is None
    assert records == [dict(legacy_record(), **NO_PKD)]
    # Best effort means ONE attempt: no retry and no waiting.
    assert len(gus.reports) == 1 and gus.sleeps == []
    text, lines = pkd_log_lines(capsys)
    assert len(lines) == 1 and SECRET not in text


def test_wo982_lookup_without_the_flag_makes_no_extra_call_and_adds_no_key(gus):
    """This is the call of the contractor / invoice workflow: one positional argument."""
    # Act
    records, error = app_module.gus_lookup_nip(NIP)

    # Assert
    assert error is None and gus.operations == ["Zaloguj", "DaneSzukajPodmioty"]
    assert records == [legacy_record()]
    assert inspect.signature(app_module.gus_lookup_nip).parameters["with_pkd"].default is False


def test_wo982_lookup_with_pkd_asks_for_no_report_when_the_tax_id_is_unknown(gus):
    # Arrange - the register answers that there is no such entity.
    gus.search = mtom('<s:Envelope><s:Body><DaneSzukajPodmiotyResponse><DaneSzukajResult/>'
                      '</DaneSzukajPodmiotyResponse></s:Body></s:Envelope>')

    # Act
    records, error = app_module.gus_lookup_nip(NIP, with_pkd=True)

    # Assert
    assert (records, error) == ([], None) and REPORT not in gus.operations


def test_wo982_pkd_log_lines_carry_names_and_counts_but_no_record_value(gus, capsys):
    """A sole trader's record is personal data. The older `[GUS-LOOKUP]` lines are
    out of this change; what WO-982 adds must not print a single value."""
    # Arrange
    gus.search = search_reply("F")
    gus.report = report_reply([person_row(PERSON_KEYS_UNDERSCORE, MEDICAL["kod"], MEDICAL["nazwa"], "1")])

    # Act
    app_module.gus_lookup_nip(NIP, with_pkd=True)

    # Assert
    text, lines = pkd_log_lines(capsys)
    assert len(lines) == 1
    assert PERSON_REPORT in lines[0] and "status=200" in lines[0]
    assert "wiersze=1" in lines[0] and "przewazajace=1" in lines[0] and "fiz_pkd_Kod" in lines[0]
    for value in (REGON, NIP, COMPANY, "CEIDG", SID):
        assert value not in lines[0]
    # The PKD itself is new data: no line of any stage prints it.
    assert MEDICAL["kod"] not in text and MEDICAL["nazwa"] not in text


# ---------------------------------------------------------------------------
# 3) The time budget: a slow register never costs the caller the record
# ---------------------------------------------------------------------------

# The portal waits this long for the WHOLE route answer (`call_wfirma_service`).
PORTAL_WAIT_SECONDS = 30
SKIPPED_LINE = "[GUS-PKD] pominieto: budzet czasu"

LEGACY_RESPONSE = {
    "nip_status": "poprawny",
    "nip": NIP,
    "gus_data": {
        "name": COMPANY, "regon": REGON, "street": "ul. Testowa 9/82", "zip": "00-982",
        "city": "Testowo", "voivodeship": "mazowieckie", "krs": None,
    },
    "data": legacy_record(),
}


@pytest.mark.parametrize("login_seconds,search_seconds", [(0, 15.5), (8, 7.5), (19, 0), (19, 20)],
                         ids=["slow_search", "both_slow", "slow_login", "everything_at_its_limit"])
def test_wo982_slow_lookup_skips_the_report_and_returns_the_record_without_pkd(
        gus, capsys, login_seconds, search_seconds):
    """Before WO-982 a lookup that took 16 s still delivered the address in time.
    A report added on top could push the answer past the portal's wait and lose
    the address as well, so past the threshold the report is not started."""
    # Arrange - the register answers, but login + search took more than the threshold.
    gus.seconds.update(Zaloguj=login_seconds, DaneSzukajPodmioty=search_seconds)

    # Act
    records, error = app_module.gus_lookup_nip(NIP, with_pkd=True)

    # Assert - no report at all; the found record comes back with the four fields empty.
    assert error is None and gus.operations == ["Zaloguj", "DaneSzukajPodmioty"]
    assert records == [dict(legacy_record(), **NO_PKD)]
    # One line, the literal text: no tax id, no REGON, no name.
    assert pkd_log_lines(capsys)[1] == [SKIPPED_LINE]


@pytest.mark.parametrize("login_seconds,search_seconds", [(0, 0), (0.4, 0.6), (8, 7)],
                         ids=["instant", "usual", "exactly_at_the_threshold"])
def test_wo982_lookup_within_the_budget_still_reads_the_report(gus, capsys, login_seconds, search_seconds):
    # Arrange
    gus.seconds.update(Zaloguj=login_seconds, DaneSzukajPodmioty=search_seconds)

    # Act
    records, error = app_module.gus_lookup_nip(NIP, with_pkd=True)

    # Assert - "more than" the threshold skips; the threshold itself does not.
    assert error is None and gus.operations == ["Zaloguj", "DaneSzukajPodmioty", REPORT]
    assert records[0]["pkdPrzewazajace"] == [MEDICAL] and records[0]["pkdGlowneJednoznaczne"] is True
    assert SKIPPED_LINE not in pkd_log_lines(capsys)[0]


def test_wo982_lookup_without_the_flag_never_reads_the_clock(gus, monkeypatch):
    """The contractor / invoice workflow gains not a single step: a slow lookup
    returns exactly what it always returned and the clock is not even consulted."""
    # Arrange - a slow register, and a clock that fails the test if anybody reads it.
    gus.seconds.update(Zaloguj=19, DaneSzukajPodmioty=20)
    monkeypatch.setattr(app_module, "gus_monotonic",
                        lambda: pytest.fail("the lookup read the clock without with_pkd"))

    # Act
    records, error = app_module.gus_lookup_nip(NIP)

    # Assert
    assert error is None and records == [legacy_record()]
    assert gus.operations == ["Zaloguj", "DaneSzukajPodmioty"]


@pytest.mark.parametrize("body_flag,expected_data", [
    ({}, legacy_record()),
    ({"with_pkd": True}, dict(legacy_record(), **NO_PKD)),
], ids=["without_flag", "with_flag"])
def test_wo982_route_over_a_slow_register_still_confirms_the_tax_id(gus, client, body_flag, expected_data):
    # Arrange
    gus.seconds.update(Zaloguj=8, DaneSzukajPodmioty=12)

    # Act
    response = client.post(ROUTE, json=dict({"nip": NIP}, **body_flag), headers=HEADERS)

    # Assert - the address the portal needs is there either way, and no report was started.
    assert response.status_code == 200
    assert response.get_json() == dict(LEGACY_RESPONSE, data=expected_data)
    assert REPORT not in gus.operations


def test_wo982_report_budget_fits_into_the_wait_of_the_portal():
    """Pins the arithmetic the comments in app.py rely on. The per-call limit of
    `requests` covers the connection and every single read separately, so the
    report nominally costs twice its limit; the threshold is what protects the
    caller. Raising either constant has to be a conscious decision."""
    # Act
    nominal_worst_case = (app_module.GUS_PKD_SKIP_AFTER_SECONDS
                          + 2 * app_module.GUS_PKD_REPORT_TIMEOUT_SECONDS)

    # Assert
    assert app_module.GUS_PKD_SKIP_AFTER_SECONDS == 15
    assert nominal_worst_case < PORTAL_WAIT_SECONDS


# ---------------------------------------------------------------------------
# 4) POST /api/gus/validate-nip
# ---------------------------------------------------------------------------


def test_wo982_route_without_the_flag_answers_exactly_as_before(gus, client):
    # Act
    response = client.post(ROUTE, json={"nip": NIP}, headers=HEADERS)

    # Assert - the same keys and values as before WO-982, and no report was read.
    assert response.status_code == 200
    assert response.get_json() == LEGACY_RESPONSE
    assert "pkd" not in response.get_data(as_text=True).lower()
    assert gus.operations == ["Zaloguj", "DaneSzukajPodmioty"]


@pytest.mark.parametrize("flag", ["true", "True", 1, "1", False, None, 0, [True], {"on": True}],
                         ids=["text_true", "text_True", "number_1", "text_1", "false", "null", "zero",
                              "list", "object"])
def test_wo982_route_starts_the_report_only_for_a_literal_true(gus, client, flag):
    # Act
    response = client.post(ROUTE, json={"nip": NIP, "with_pkd": flag}, headers=HEADERS)

    # Assert
    assert response.status_code == 200 and response.get_json() == LEGACY_RESPONSE
    assert REPORT not in gus.operations


def test_wo982_route_with_the_flag_adds_the_pkd_fields_to_the_data_record(gus, client):
    # Act
    response = client.post(ROUTE, json={"nip": NIP, "with_pkd": True}, headers=HEADERS)

    # Assert - four new keys in `data`; everything else is what the route always returned.
    body = response.get_json()
    assert response.status_code == 200
    assert set(body["data"]) - set(LEGACY_RESPONSE["data"]) == PKD_KEYS
    assert body == dict(LEGACY_RESPONSE, data=dict(
        legacy_record(),
        pkdPrzewazajace=[MEDICAL], pkdKod=MEDICAL["kod"], pkdNazwa=MEDICAL["nazwa"],
        pkdGlowneJednoznaczne=True,
    ))
    assert len(gus.reports) == 1


def test_wo982_route_with_the_flag_still_confirms_the_tax_id_when_the_report_fails(gus, client):
    # Arrange
    gus.report = requests.exceptions.ReadTimeout(SECRET)

    # Act
    response = client.post(ROUTE, json={"nip": NIP, "with_pkd": True}, headers=HEADERS)

    # Assert - a found company is never turned into "the register does not answer".
    body = response.get_json()
    assert response.status_code == 200 and body["nip_status"] == "poprawny"
    assert body == dict(LEGACY_RESPONSE, data=dict(legacy_record(), **NO_PKD))
    assert SECRET not in response.get_data(as_text=True)


def test_wo982_route_with_the_flag_keeps_the_outage_answer_when_the_search_fails(gus, client):
    # Arrange - the search itself fails; there is no record to describe.
    gus.search = requests.exceptions.ReadTimeout("read timeout")

    # Act
    response = client.post(ROUTE, json={"nip": NIP, "with_pkd": True}, headers=HEADERS)

    # Assert
    body = response.get_json()
    assert response.status_code == 503 and body["nip_status"] == "niedostepny"
    assert body["gus_data"] is None and REPORT not in gus.operations


def test_wo982_route_with_the_flag_requires_the_gus_token(gus, client):
    # Act
    response = client.post(ROUTE, json={"nip": NIP, "with_pkd": True})

    # Assert
    assert response.status_code == 401 and gus.calls == []


def test_wo982_name_by_nip_route_ignores_the_flag(gus, client):
    """`name-by-nip` has its own copy of the lookup and is out of this change."""
    # Act
    response = client.post(NAME_ROUTE, json={"nip": NIP, "with_pkd": True}, headers=HEADERS)

    # Assert
    assert response.status_code == 200
    assert response.get_json() == {"data": [legacy_record()]}
    assert gus.operations == ["Zaloguj", "DaneSzukajPodmioty"]
