"""Deterministic checks that run AFTER the model extracts a bill.

The model reads the bill; plain code decides whether to trust it. Anything that
fails a check is flagged for human review instead of being silently accepted.
"""
from __future__ import annotations

import re
from datetime import datetime

_CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_GSTIN_RE = re.compile(r"^(0[1-9]|[1-2][0-9]|3[0-9])[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")

# Rates seen on Indian bills. 12% and 28% were retired for new supplies in the
# Sept-2025 GST rate rationalisation but still appear on older bills.
KNOWN_RATES = {0.0, 0.25, 3.0, 5.0, 12.0, 18.0, 28.0, 40.0}

# Characters a vision model commonly confuses. Used for checksum-guided repair.
_CONFUSABLE = {"0": "O", "O": "0", "1": "I", "I": "1", "8": "B", "B": "8",
               "5": "S", "S": "5", "2": "Z", "Z": "2", "6": "G", "G": "6"}


def gstin_checksum_char(first14: str) -> str:
    """Compute the 15th (check) character of a GSTIN from its first 14."""
    total = 0
    for i, ch in enumerate(first14):
        val = _CHARSET.index(ch) * (1 if i % 2 == 0 else 2)
        total += val // 36 + val % 36
    return _CHARSET[(36 - total % 36) % 36]


def clean_gstin(raw: str | None) -> str:
    return re.sub(r"[^0-9A-Z]", "", (raw or "").upper())


def gstin_valid(raw: str | None) -> bool:
    g = clean_gstin(raw)
    return bool(_GSTIN_RE.match(g)) and gstin_checksum_char(g[:14]) == g[14]


def repair_gstin(raw: str | None) -> str:
    """Swap ONE look-alike character (0/O, 1/I, 8/B...) if, and only if, exactly one
    swap makes the checksum pass. Otherwise return the GSTIN unchanged.
    The checksum is the judge, so a GSTIN is never invented, only provably repaired."""
    g = clean_gstin(raw)
    if len(g) != 15 or gstin_valid(g):
        return g
    fixes = set()
    for i, ch in enumerate(g):
        if ch in _CONFUSABLE:
            cand = g[:i] + _CONFUSABLE[ch] + g[i + 1:]
            if gstin_valid(cand):
                fixes.add(cand)
    return fixes.pop() if len(fixes) == 1 else g


def parse_date(raw: str | None) -> str | None:
    """Return ISO date (YYYY-MM-DD) or None. Indian bills are day-first."""
    if not raw:
        return None
    s = raw.strip()
    fmts = ["%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y",
            "%Y-%m-%d", "%d %b %Y", "%d-%b-%Y", "%d %B %Y", "%d-%b-%y"]
    for f in fmts:
        try:
            return datetime.strptime(s, f).date().isoformat()
        except ValueError:
            continue
    return None


def _num(v) -> float:
    if v in (None, ""):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d.\-]", "", str(v).replace(",", ""))
    try:
        return float(s)
    except ValueError:
        return 0.0


def validate_bill(b: dict) -> list[dict]:
    """Return a list of flags: {"level": "error"|"warn", "field": str, "msg": str}."""
    flags: list[dict] = []

    def add(level, field, msg):
        flags.append({"level": level, "field": field, "msg": msg})

    vg = clean_gstin(b.get("vendor_gstin"))
    if not vg:
        add("warn", "vendor_gstin",
            "Vendor GSTIN not read - check the bill (if none is printed, input tax credit is not claimable)")
    elif not gstin_valid(vg):
        add("error", "vendor_gstin", f"Vendor GSTIN '{vg}' fails format/checksum - likely misread")

    bg = clean_gstin(b.get("buyer_gstin"))
    if bg and not gstin_valid(bg):
        add("error", "buyer_gstin", f"Buyer GSTIN '{bg}' fails format/checksum - likely misread")

    if not parse_date(b.get("invoice_date")):
        add("error", "invoice_date", "Date missing or unreadable")
    if not (b.get("invoice_number") or "").strip():
        add("warn", "invoice_number", "Invoice number missing")

    taxable, cgst, sgst, igst, cess, total = (
        _num(b.get(k)) for k in ("taxable_value", "cgst", "sgst", "igst", "cess", "total")
    )
    if total <= 0:
        add("error", "total", "Total missing or zero")

    if igst and (cgst or sgst):
        add("error", "igst", "Both IGST and CGST/SGST present - a bill has one or the other")
    if cgst or sgst:
        if abs(cgst - sgst) > 0.02:
            add("error", "sgst", f"CGST ({cgst:.2f}) and SGST ({sgst:.2f}) should be equal")

    if total > 0:
        expected = taxable + cgst + sgst + igst + cess
        diff = abs(expected - total)
        if diff > 1.01:  # allow up to Rs 1 round-off
            add("error", "total",
                f"Taxable + taxes = {expected:.2f} but total reads {total:.2f} (diff {diff:.2f})")

    tax = cgst + sgst + igst
    if taxable > 0 and tax > 0:
        rate = round(tax / taxable * 100, 2)
        # tolerance for rounding on small amounts
        if not any(abs(rate - r) <= 0.35 for r in KNOWN_RATES):
            add("warn", "tax", f"Effective GST rate {rate}% is not a standard slab - check amounts")

    vs, bs = vg[:2], bg[:2]
    if vs and bs and gstin_valid(vg) and gstin_valid(bg):
        if vs == bs and igst > 0:
            add("warn", "igst", "Same-state parties but IGST charged (expected CGST+SGST)")
        if vs != bs and (cgst or sgst):
            add("warn", "cgst", "Different-state parties but CGST/SGST charged (expected IGST)")

    return flags


def dedupe_key(b: dict) -> tuple:
    g = clean_gstin(b.get("vendor_gstin"))
    inv = re.sub(r"[^A-Z0-9]", "", (b.get("invoice_number") or "").upper())
    if g and inv:
        return ("inv", g, inv)
    return ("amt", g, parse_date(b.get("invoice_date")), round(_num(b.get("total")), 2))