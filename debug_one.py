"""Show exactly what the model says for ONE bill.
Usage:  python debug_one.py data/synthetic/bill_000.jpg"""
import json
import sys

from billbox import extractor

img = extractor.load_images(sys.argv[1])[0]
print("MODEL:", extractor.MODEL, "| OLLAMA:", extractor.OLLAMA_URL)

print("\n--- Pass 1: full form (what the app reads first) ---")
print(json.dumps(extractor.extract(img), indent=2))

print("\n--- Pass 2: GSTIN list, raw reply ---")
raw = extractor._chat_text(img, extractor.LIST_PROMPT)
print(raw)

cands = extractor.parse_gstin_lines(raw)
print("\nParsed candidates:", cands)
print("Vendor chosen    :", extractor.pick_vendor_gstin(cands))
