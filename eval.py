"""Measure how well a model reads the bills, and how many mistakes the validators catch.
Usage: python eval.py data/synthetic [--model gemma3:4b]
Run it once per model (or before/after fine-tuning) and put the table in your write-up."""
import argparse, json, time
from pathlib import Path

from billbox import extractor, pipeline
from billbox.validators import validate_bill

NUM = ("taxable_value", "cgst", "sgst", "igst", "total")
TXT = ("vendor_gstin", "buyer_gstin", "invoice_number", "invoice_date")


def same(k, got, want):
    if k in NUM:
        return abs(float(got or 0) - float(want or 0)) <= 0.011
    if k == "invoice_date":
        from billbox.validators import parse_date
        return parse_date(got) == parse_date(want)
    return str(got or "").strip().upper().replace(" ", "") == str(want or "").strip().upper().replace(" ", "")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("folder"); ap.add_argument("--model")
    a = ap.parse_args()
    folder = Path(a.folder); truth = json.loads((folder / "truth.json").read_text())
    field_ok = {k: 0 for k in NUM + TXT}; bills_ok = wrong = caught = 0; t0 = time.time()
    for name, want in truth.items():
        raw = extractor.extract(extractor.load_images(folder / name)[0], model=a.model)
        got = pipeline.normalise(raw)
        res = {k: same(k, got.get(k), want.get(k)) for k in field_ok}
        for k, v in res.items():
            field_ok[k] += v
        if all(res.values()):
            bills_ok += 1
        else:
            wrong += 1
            if any(f["level"] == "error" for f in validate_bill(got)):
                caught += 1
    n = len(truth); dt = time.time() - t0
    print(f"\nModel: {a.model or extractor.MODEL}   Bills: {n}   Time/bill: {dt / n:.1f}s")
    print("-" * 44)
    for k, v in field_ok.items():
        print(f"{k:<16}{v / n:>8.1%}")
    print("-" * 44)
    print(f"Fully correct bills      : {bills_ok}/{n} ({bills_ok / n:.1%})")
    if wrong:
        print(f"Wrong bills auto-flagged : {caught}/{wrong} ({caught / wrong:.1%})  <- the safety net")
