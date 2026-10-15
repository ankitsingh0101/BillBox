from __future__ import annotations

from pathlib import Path

from . import extractor
from .validators import clean_gstin, dedupe_key, parse_date, repair_gstin, validate_bill

FIELDS = ["vendor_name", "vendor_gstin", "buyer_gstin", "invoice_number", "invoice_date",
          "taxable_value", "cgst", "sgst", "igst", "cess", "total", "summary", "category"]


def _info(field: str, msg: str) -> dict:
    return {"level": "info", "field": field, "msg": msg}


def normalise(raw: dict) -> dict:
    b = {k: raw.get(k) for k in FIELDS}
    notes = []
    for k, label in (("vendor_gstin", "Vendor GSTIN"), ("buyer_gstin", "Buyer GSTIN")):
        before = clean_gstin(b[k])
        b[k] = repair_gstin(before)
        if before and b[k] != before:
            notes.append(_info(k, f"{label} auto-corrected from {before} to {b[k]} (checksum confirms the fix)"))
    b["invoice_date"] = parse_date(b["invoice_date"]) or (b["invoice_date"] or "")
    for k in ("taxable_value", "cgst", "sgst", "igst", "cess", "total"):
        b[k] = float(b[k]) if isinstance(b[k], (int, float)) else (b[k] or 0)
    b["summary"] = str(b.get("summary") or "").strip()[:200]
    b["category"] = str(b.get("category") or "").strip()
    b["_info"] = notes
    return b


def process_file(path: str | Path, extract_fn=None) -> list[dict]:
    """One file -> one bill per page. Each bill carries its own validation flags."""
    use_retry = extract_fn is None          # second attempt only with the real model (keeps tests mockable)
    extract_fn = extract_fn or extractor.extract
    bills = []
    for i, img in enumerate(extractor.load_images(path), start=1):
        try:
            bill = normalise(extract_fn(img))
            info = bill.pop("_info", [])
            if use_retry and not bill["vendor_gstin"]:
                try:
                    g, raw = extractor.find_vendor_gstin(img, bill["buyer_gstin"])
                    if g:
                        bill["vendor_gstin"] = g
                        info.append(_info("vendor_gstin", "Vendor GSTIN found on a focused second read"))
                        if raw and raw != g:
                            info.append(_info("vendor_gstin", f"Vendor GSTIN auto-corrected from {raw} to {g} (checksum confirms the fix)"))
                except Exception as e:      # best-effort, but never silent
                    print(f"[BillBox] vendor GSTIN second attempt failed: {e!r}")
            bill["flags"] = validate_bill(bill) + info
        except Exception as e:  # model offline, bad JSON, etc. -> surface it, don't crash the batch
            bill = normalise({})
            bill.pop("_info", None)
            bill["flags"] = [{"level": "error", "field": "file", "msg": f"Extraction failed: {e}"}]
        bill["source"] = f"{Path(path).name}" + (f" (p{i})" if i > 1 else "")
        bill["status"] = status(bill)
        bills.append(bill)
    return bills


def mark_duplicates(bills: list[dict]) -> list[dict]:
    seen: dict[tuple, str] = {}
    for b in bills:
        if not (b.get("total") or b.get("invoice_number")):
            continue
        k = dedupe_key(b)
        if k in seen:
            b["flags"].append({"level": "error", "field": "invoice_number",
                               "msg": f"Possible duplicate of {seen[k]}"})
        else:
            seen[k] = b["source"]
    return bills


def status(b: dict) -> str:
    levels = {f["level"] for f in b.get("flags", [])}
    return "REVIEW" if "error" in levels else ("CHECK" if "warn" in levels else "OK")


def recheck(bills: list[dict]) -> list[dict]:
    """Re-validate a whole list after the user edits or adds bills (also catches cross-file duplicates)."""
    for b in bills:
        b["vendor_gstin"] = clean_gstin(b.get("vendor_gstin"))
        b["buyer_gstin"] = clean_gstin(b.get("buyer_gstin"))
        b["invoice_date"] = parse_date(b.get("invoice_date")) or (b.get("invoice_date") or "")
        info = [f for f in b.get("flags", []) if f.get("level") == "info"]
        b["flags"] = validate_bill(b) + info
    mark_duplicates(bills)
    for b in bills:
        b["status"] = status(b)
    return bills