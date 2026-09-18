"""One place that names a masked refusal of a grouped document call (WO-635).

The two strict workflows answer the portal from a closed vocabulary. Creating a
first invoice ends as ``first_invoice_unverified`` (502) and reconciling an
existing one ends as ``reconciliation_unverified`` (409), and both handlers
build that answer inside a bare ``except Exception``. That is deliberate: the
provider's body must never reach the caller. The side effect is that the reason
our own code chose — ``created_payment_mismatch``, ``create_unverified``,
``readback_unavailable`` and a dozen siblings, each one a literal in this
repository — is destroyed at the moment it is needed most.

2026-09-18 that cost a production settlement: wFirma created an invoice, the
bridge refused to confirm it, and nothing anywhere recorded which of the nine
checks disagreed. The portal side of the same blind spot was removed the day
before (WO-631); this is the same remedy one layer down.

This module changes no behaviour, no status code and no response body. It
writes one line per refusal from a closed vocabulary only: our own reason name,
a mapped exception family, and the provider's document identifier. Party names,
amounts, provider payloads and stack traces are excluded by construction — the
guards accept a *shape*, never arbitrary content.
"""
import re

PREFIX = "[document-bridge]"
UNNAMED = "unnamed"

# Our refusal reasons are snake_case literals in this repository. A provider
# message, an SQL fragment, a contractor name or an e-mail cannot match: no
# spaces, no newlines, no punctuation beyond `_`, no capitals, max 64 chars.
_REASON_SHAPE = re.compile(r"[a-z][a-z0-9_]{2,63}")
# wFirma entity identifiers are decimal strings; nothing else is printable here.
_DOCUMENT_SHAPE = re.compile(r"[0-9]{1,32}")
_STAGES = frozenset({"first_invoice_create", "reconcile"})
_OTHER = "other"


def _exception_codes():
    """Closed map of exception type -> one word. Anything else becomes `other`.

    A shape guard would not be enough, and that is not a hypothesis: a class
    name is a valid Python identifier, so a type built at runtime from customer
    data passes any identifier pattern untouched. WO-631 reached this same
    conclusion for the portal. The cost is accepted — an unmapped layer reads as
    `other`, while our own reason still arrives in `reason=`.
    """
    codes = {
        ValueError: "value_error", TypeError: "type_error", KeyError: "key_error",
        AttributeError: "attribute_error", RuntimeError: "runtime_error",
        AssertionError: "assertion_error", OSError: "os_error",
        ArithmeticError: "arithmetic_error", LookupError: "lookup_error",
    }
    for module, names in (
        ("grouped_document_contract", ("GroupedDocumentError",)),
        ("participant_change_correction", ("StructuralContractError",)),
        ("wfirma_document_money", ("DocumentMoneyError",)),
        ("requests.exceptions", ("RequestException", "Timeout", "ConnectionError")),
        ("werkzeug.exceptions", ("HTTPException",)),
    ):
        try:
            imported = __import__(module, fromlist=list(names))
        except Exception:
            continue
        for name in names:
            found = getattr(imported, name, None)
            if isinstance(found, type):
                # Snake_case of the class name; these names are literals in our
                # own source, so they cannot carry data.
                codes.setdefault(found, re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower())
    return codes


_CODES = None


def _safe_class(exc):
    """Name the failing layer through the closed map, never from the class itself.

    Built on first use rather than at import: the contract modules named above
    are imported lazily inside the handlers, and building this eagerly would tie
    this module's import order to theirs. Walking the ancestry means a narrower
    subclass still reports its family, and the word always comes from our map.
    """
    global _CODES
    if _CODES is None:
        try:
            _CODES = _exception_codes()
        except Exception:
            _CODES = {}
    try:
        for ancestor in type(exc).__mro__:
            code = _CODES.get(ancestor)
            if code is not None:
                return code
    except Exception:
        return _OTHER
    return _OTHER


def _safe_reason(value):
    if type(value) is str and _REASON_SHAPE.fullmatch(value):
        return value
    return UNNAMED


def _internal(exc):
    return _safe_reason(exc.args[0] if getattr(exc, "args", None) else None)


def log_refusal(exc, *, stage, document_id=None):
    """Call once, from the handler that turns an exception into a fixed answer."""
    # This runs inside an `except` block on the refusal path. A raising emitter
    # would escape the handler, reach `document_outcome_envelope` and turn a
    # deliberate 502/409 into a 500 — the one thing this change promises not to
    # do.
    try:
        fields = [
            f"{PREFIX} refused",
            f"stage={stage if stage in _STAGES else UNNAMED}",
            f"reason={_internal(exc)}",
            f"exc={_safe_class(exc)}",
        ]
        if document_id is not None:
            fields.append(f"document={_safe_document(document_id)}")
        print(" ".join(fields))
    except Exception:
        pass


def _safe_document(value):
    if type(value) is str and _DOCUMENT_SHAPE.fullmatch(value):
        return value
    if type(value) is int and type(value) is not bool and 0 < value < 10**32:
        return str(value)
    return UNNAMED


def _attempt(call):
    try:
        return call()
    except Exception:
        return None


def _length(value):
    return len(value) if type(value) is str else -1


def log_identity(contract, probe, *, stage, document_id=None):
    """Say which part of a failed identity check disagrees (WO-636).

    `created_identity_mismatch` compares four things at once, so on its own it
    does not say whether the provider returned a different document, filed it
    under another series, dropped our marker, or withheld the number. Both
    production settlements of 2026-09-18 died here and the single name could
    not tell them apart.

    The breakdown is recomputed here rather than reported by the contract on
    purpose: `first_invoice_contract.py` and `grouped_document_contract.py` are
    byte-identical twins of the portal's own copies, and splitting the check at
    the source would put the two halves of one contract out of step.

    Only field *names* and string *lengths* are printed. No provider value, no
    party data, no marker content.
    """
    try:
        prepared, invoice, created_id, company_id = probe
        observed = _attempt(lambda: contract.project_chain([invoice], company_id))
        if observed is None:
            # The document could not be projected at all, so the identity check
            # never ran. Reporting all four parts as disagreeing would be a
            # confident lie; `log_refusal` already named the real failure.
            return
        wanted = _attempt(lambda: prepared["document"]["id_external"])
        seen = _attempt(lambda: observed["external_key"])
        checks = (
            ("document_id", lambda: observed["document_id"] == contract.identifier(created_id)),
            ("external_key", lambda: seen == wanted),
            ("series", lambda: contract.relation(invoice, "series") == prepared["series_id"]),
            ("fullnumber", lambda: bool(contract.text(invoice.get("fullnumber"), 256))),
        )
        bad = [name for name, check in checks if _attempt(check) is not True]
        if not bad:
            # The refusal came from a later check; `log_refusal` already named
            # it and a second line saying `nothing disagrees` would be noise.
            return
        fields = [
            f"{PREFIX} identity",
            f"stage={stage if stage in _STAGES else UNNAMED}",
            f"disagrees={','.join(bad)}",
        ]
        if "external_key" in bad:
            # Zero tells a dropped marker apart from a truncated one, and both
            # apart from a marker the provider replaced with something else.
            fields.append(f"marker_seen={_length(seen)}")
            fields.append(f"marker_sent={_length(wanted)}")
        if document_id is not None:
            fields.append(f"document={_safe_document(document_id)}")
        print(" ".join(fields))
    except Exception:
        pass
