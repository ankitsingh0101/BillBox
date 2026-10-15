import random
from billbox.validators import (gstin_checksum_char, gstin_valid, parse_date, validate_bill,
                                dedupe_key, repair_gstin)
from gen_synthetic import fake_gstin

GOOD = "27AAPFU0939F1ZV"  # widely used public example of a structurally valid GSTIN


def mk(**kw):
    base = dict(vendor_name="X", vendor_gstin=fake_gstin("23"), buyer_gstin=fake_gstin("23"),
                invoice_number="INV/1", invoice_date="14/10/2026", taxable_value=1000.0,
                cgst=90.0, sgst=90.0, igst=0.0, cess=0.0, total=1180.0)
    base.update(kw); return base


def levels(b): return {(f["field"], f["level"]) for f in validate_bill(b)}


def test_known_gstin_valid():
    assert gstin_valid(GOOD)


def test_generated_gstins_always_valid():
    random.seed(1)
    assert all(gstin_valid(fake_gstin()) for _ in range(500))


def test_single_character_misread_is_caught():
    g = fake_gstin("23")
    bad = g[:5] + ("A" if g[5] != "A" else "B") + g[6:]
    assert gstin_valid(g) and not gstin_valid(bad)


def test_lowercase_and_spaces_cleaned():
    assert gstin_valid(" " + GOOD.lower()[:2] + " " + GOOD.lower()[2:])


def test_dates():
    assert parse_date("14/10/2026") == "2026-10-14"
    assert parse_date("14 Oct 2026") == "2026-10-14"
    assert parse_date("garbage") is None


def test_clean_bill_has_no_errors():
    assert not any(l == "error" for _, l in levels(mk()))


def test_total_mismatch_flagged():
    assert ("total", "error") in levels(mk(total=1810.0))  # digits transposed


def test_roundoff_within_one_rupee_ok():
    assert ("total", "error") not in levels(mk(total=1180.4))


def test_cgst_sgst_must_match():
    assert ("sgst", "error") in levels(mk(sgst=19.0, total=1109.0))


def test_igst_and_cgst_together_flagged():
    assert ("igst", "error") in levels(mk(igst=180.0, total=1360.0))


def test_odd_rate_warns():
    assert ("tax", "warn") in levels(mk(cgst=70.0, sgst=70.0, total=1140.0))


def test_interstate_with_cgst_warns():
    b = mk(vendor_gstin=fake_gstin("27"))
    assert ("cgst", "warn") in levels(b)


def test_dedupe_key_ignores_formatting():
    a = mk(invoice_number="INV/1"); b = dict(a, invoice_number="inv 1")
    assert dedupe_key(a) == dedupe_key(b)


def test_repair_fixes_single_lookalike_swap():
    good = "27GOBOY6505B4ZU"
    assert repair_gstin("27G0BOY6505B4ZU") == good   # O misread as 0


def test_repair_never_invents_when_unsure():
    bad = "27G0B0Y6505B4ZU"                           # two wrong characters
    assert repair_gstin(bad) == bad