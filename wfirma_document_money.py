"""Versioned, pure NETTO document arithmetic; not an invoice/payment writer.

Prices are whole PLN grosze AFTER the caller's approved discount. VAT is
rounded once per rate group, not per ticket or displayed gross line. The
observed sales documents in WO-601AC support this NETTO calculation; this is
not a replacement for the frozen line/saga contracts in migration 0063.

There are intentionally no runtime callers yet. Empty positions describe a
zero valuation (e.g. before an addition), not permission to issue an invoice.
This module neither decides discounts nor derives actual payments/refunds.
"""

from __future__ import annotations

CALCULATION_VERSION = "wfirma-net-document/v1"
MAX_POSITIONS = 500
MAX_QUANTITY = 1_000_000
MAX_GROSZE = 999_999_999_999
_POSITION_KEYS = frozenset({"quantity", "unit_net_grosze", "vat_rate_code"})
# Fiscal categories with a zero rate must not be merged into one category.
_VAT_RATES = (("23", 23), ("8", 8), ("5", 5), ("0", 0), ("zw", 0), ("np", 0))
_VAT_CODES = frozenset(code for code, _ in _VAT_RATES)


class DocumentMoneyError(ValueError):
    """Calculation refusal with a constant diagnostic code, never input data."""


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise DocumentMoneyError(reason)


def calculate_document_money(
    *, calculation_version: str, price_model: str, positions: object
) -> dict:
    """Return a fresh PLN document valuation or raise DocumentMoneyError.

    Each input position has EXACTLY quantity, unit_net_grosze and
    vat_rate_code. Currency is deliberately fixed to PLN. Unsupported epochs
    (including BRUTTO) and fractions are rejected, never silently converted.
    Output positions carry net bases only: gross is authoritative at the
    document/rate-group level, so no arbitrary cent is assigned to a person.
    """
    _require(
        type(calculation_version) is str
        and calculation_version == CALCULATION_VERSION,
        "calculation_version_unsupported",
    )
    _require(type(price_model) is str and price_model == "netto", "price_model_unsupported")
    _require(type(positions) in (list, tuple), "positions_malformed")
    _require(len(positions) <= MAX_POSITIONS, "positions_limit")
    net_by_code: dict[str, int] = {}
    lines = []
    net_total = 0
    for position in positions:
        _require(type(position) is dict, "position_malformed")
        _require(
            all(type(key) is str for key in position) and set(position) == _POSITION_KEYS,
            "position_fields_malformed",
        )
        quantity = position["quantity"]
        unit = position["unit_net_grosze"]
        code = position["vat_rate_code"]
        _require(type(quantity) is int and 1 <= quantity <= MAX_QUANTITY, "quantity_malformed")
        _require(type(unit) is int and 0 <= unit <= MAX_GROSZE, "unit_net_malformed")
        _require(type(code) is str and code in _VAT_CODES, "vat_rate_unsupported")
        net = quantity * unit
        _require(net <= MAX_GROSZE, "amount_limit")
        net_total += net
        _require(net_total <= MAX_GROSZE, "amount_limit")
        net_by_code[code] = net_by_code.get(code, 0) + net
        lines.append({
            "quantity": quantity,
            "unit_net_grosze": unit,
            "vat_rate_code": code,
            "net_grosze": net,
        })

    groups = []
    vat_total = 0
    for code, rate in _VAT_RATES:
        if code not in net_by_code:
            continue
        net = net_by_code[code]
        # HALF_UP of a non-negative integer base; no float/Decimal context.
        vat = (net * rate + 50) // 100
        gross = net + vat
        _require(gross <= MAX_GROSZE, "amount_limit")
        vat_total += vat
        groups.append({
            "vat_rate_code": code,
            "net_grosze": net,
            "vat_grosze": vat,
            "gross_grosze": gross,
        })
    gross_total = net_total + vat_total
    _require(gross_total <= MAX_GROSZE, "amount_limit")
    return {
        "calculation_version": CALCULATION_VERSION,
        "price_model": "netto",
        "currency": "PLN",
        "positions": lines,
        "vat_groups": groups,
        "totals": {
            "net_grosze": net_total,
            "vat_grosze": vat_total,
            "gross_grosze": gross_total,
        },
    }


def calculate_document_change(
    *, calculation_version: str, price_model: str,
    before_positions: object, after_positions: object
) -> dict:
    """Value both complete states, then subtract; delta is NOT a cash movement.

    Recalculate inputs rather than trust caller-supplied totals. In particular,
    VAT(after net - before net) is not VAT(after net) - VAT(before net).
    Negative results are valid decreases; both source valuations are unsigned.
    """
    before = calculate_document_money(
        calculation_version=calculation_version, price_model=price_model,
        positions=before_positions,
    )
    after = calculate_document_money(
        calculation_version=calculation_version, price_model=price_model,
        positions=after_positions,
    )
    return {
        "calculation_version": CALCULATION_VERSION,
        "price_model": "netto",
        "currency": "PLN",
        "before": before,
        "after": after,
        "delta": {
            key: after["totals"][key] - before["totals"][key]
            for key in ("net_grosze", "vat_grosze", "gross_grosze")
        },
    }
