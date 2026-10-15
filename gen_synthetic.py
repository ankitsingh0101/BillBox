"""Make labelled FAKE GST bills (image + ground-truth JSON) for testing and fine-tuning.
Usage: python gen_synthetic.py --n 30 --out data/synthetic
GSTINs are structurally valid (real checksum) but invented. No real business data is used."""
import argparse, json, random, string
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from billbox.validators import gstin_checksum_char

STATES = ["23", "27", "07", "29", "24", "09", "33", "08"]  # MP, MH, DL, KA, GJ, UP, TN, RJ
SHOPS = ["Sharma General Store", "Agrawal Electronics", "Jain Stationers", "Patel Hardware",
         "Gupta Medical Agency", "Mehta Mobile Point", "Verma Printing Press", "Khan Auto Parts",
         "Malviya Sweets & Namkeen", "Choudhary Traders", "Soni Jewellers", "Tiwari Cold Storage"]
SLABS = [5, 12, 18, 28]


def fake_gstin(state=None):
    state = state or random.choice(STATES)
    pan = "".join(random.choices(string.ascii_uppercase, k=5)) + "".join(random.choices(string.digits, k=4)) + random.choice(string.ascii_uppercase)
    first14 = f"{state}{pan}{random.randint(1, 9)}Z"
    return first14 + gstin_checksum_char(first14)


def make_truth(buyer_gstin):
    vstate = random.choice(STATES)
    vg = fake_gstin(vstate)
    taxable = round(random.uniform(200, 48000), 2)
    rate = random.choice(SLABS)
    tax = round(taxable * rate / 100, 2)
    d = date(2026, 4, 1) + timedelta(days=random.randint(0, 180))
    t = dict(vendor_name=random.choice(SHOPS), vendor_gstin=vg, buyer_gstin=buyer_gstin,
             invoice_number=f"{random.choice(['INV','GST','BL'])}/{random.randint(1,999):03d}/{random.randint(26,27)}",
             invoice_date=d.strftime("%d/%m/%Y"), taxable_value=taxable, cgst=0.0, sgst=0.0, igst=0.0, cess=0.0)
    if vstate == buyer_gstin[:2]:
        t["cgst"] = t["sgst"] = round(tax / 2, 2)
    else:
        t["igst"] = tax
    t["total"] = round(taxable + t["cgst"] + t["sgst"] + t["igst"], 2)
    return t


def font(size, bold=False):
    names = (["arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold else []) + ["arial.ttf", "DejaVuSans.ttf", "Arial.ttf"]
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def render(t, path):
    W, H = 900, 1100
    img = Image.new("RGB", (W, H), (252, 250, 244))
    d = ImageDraw.Draw(img)
    d.text((W // 2, 50), t["vendor_name"].upper(), font=font(34, True), fill=(20, 20, 20), anchor="mm")
    d.text((W // 2, 92), "TAX INVOICE", font=font(22, True), fill=(60, 60, 60), anchor="mm")
    d.text((50, 140), f"GSTIN: {t['vendor_gstin']}", font=font(22), fill=(20, 20, 20))
    d.text((50, 180), f"Invoice No: {t['invoice_number']}", font=font(22), fill=(20, 20, 20))
    d.text((W - 50, 180), f"Date: {t['invoice_date']}", font=font(22), fill=(20, 20, 20), anchor="ra")
    d.text((50, 220), f"Buyer GSTIN: {t['buyer_gstin']}", font=font(22), fill=(20, 20, 20))
    d.line((50, 270, W - 50, 270), fill=(80, 80, 80), width=2)
    d.text((50, 285), "Description", font=font(20, True), fill=(20, 20, 20))
    d.text((W - 50, 285), "Amount (Rs)", font=font(20, True), fill=(20, 20, 20), anchor="ra")
    d.text((50, 330), "Goods / services as per challan", font=font(20), fill=(20, 20, 20))
    d.text((W - 50, 330), f"{t['taxable_value']:,.2f}", font=font(20), fill=(20, 20, 20), anchor="ra")
    y = 520
    d.line((50, y - 20, W - 50, y - 20), fill=(80, 80, 80), width=1)
    rows = [("Taxable value", t["taxable_value"])]
    if t["cgst"]:
        rows += [("CGST", t["cgst"]), ("SGST", t["sgst"])]
    if t["igst"]:
        rows += [("IGST", t["igst"])]
    for label, val in rows:
        d.text((W - 300, y), label, font=font(21), fill=(20, 20, 20), anchor="la")
        d.text((W - 50, y), f"{val:,.2f}", font=font(21), fill=(20, 20, 20), anchor="ra")
        y += 40
    d.text((W - 300, y + 10), "TOTAL", font=font(26, True), fill=(20, 20, 20))
    d.text((W - 50, y + 10), f"{t['total']:,.2f}", font=font(26, True), fill=(20, 20, 20), anchor="ra")
    img = img.rotate(random.uniform(-2.5, 2.5), expand=True, fillcolor=(235, 235, 230))
    img = img.filter(ImageFilter.GaussianBlur(random.uniform(0, 0.9)))
    img.convert("RGB").save(path, "JPEG", quality=random.randint(55, 90))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--out", default="data/synthetic")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    random.seed(a.seed)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    buyer = fake_gstin("23")  # the "customer" is based in MP (Indore)
    truth = {}
    for i in range(a.n):
        t = make_truth(buyer)
        name = f"bill_{i:03d}.jpg"
        render(t, out / name)
        truth[name] = t
    (out / "truth.json").write_text(json.dumps(truth, indent=2))
    print(f"wrote {a.n} bills to {out}")
