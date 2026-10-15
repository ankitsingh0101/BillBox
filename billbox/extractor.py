"""Talks to a LOCAL open-weight vision model through Ollama. No cloud, no API key."""
from __future__ import annotations

import base64
import io
import json
import os
import re
from pathlib import Path

import requests

from .validators import clean_gstin, gstin_valid, repair_gstin

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
MODEL = os.getenv("BILLBOX_MODEL", "gemma3:4b")  # any Ollama vision model: gemma3, qwen2.5vl, llama3.2-vision

CATEGORIES = ["Stationery & printing", "Electronics & IT", "Hardware & tools", "Medical & pharmacy",
              "Food & beverages", "Travel & fuel", "Rent & utilities", "Repairs & maintenance",
              "Professional services", "Raw material & stock", "Clothing & textiles", "Other"]

SCHEMA = {
    "type": "object",
    "properties": {
        "vendor_name": {"type": "string"},
        "vendor_gstin": {"type": "string"},
        "buyer_gstin": {"type": "string"},
        "invoice_number": {"type": "string"},
        "invoice_date": {"type": "string"},
        "taxable_value": {"type": "number"},
        "cgst": {"type": "number"},
        "sgst": {"type": "number"},
        "igst": {"type": "number"},
        "cess": {"type": "number"},
        "total": {"type": "number"},
        "summary": {"type": "string"},                        # last on purpose: numbers are read first
        "category": {"type": "string", "enum": CATEGORIES},
    },
    "required": ["vendor_name", "vendor_gstin", "buyer_gstin", "invoice_number", "invoice_date",
                 "taxable_value", "cgst", "sgst", "igst", "cess", "total", "summary", "category"],
}

PROMPT = """You are reading an Indian GST tax invoice or shop bill. Extract the fields exactly as printed.
Rules:
- The bill may show TWO GSTINs. vendor_gstin is the one printed near the top under the shop name (labelled GSTIN or GST No). buyer_gstin is the one labelled Buyer GSTIN or Bill To (empty string if absent). Never leave vendor_gstin empty if a GSTIN appears near the shop name.
- Copy GSTINs character by character. Do not guess missing characters.
- invoice_date: copy as printed (e.g. 14/10/2026).
- Amounts are numbers in rupees with no currency symbol or commas.
- taxable_value is the amount BEFORE tax.
- Fill CGST, SGST or IGST only if that exact label is printed with an amount on the bill. A bill normally has IGST alone, or CGST and SGST together. Never copy one tax into another. Use 0 for any tax label that is not printed.
- total is the final payable amount.
- summary: ONE short sentence (max 15 words) saying what was bought or what service was billed, using only the item descriptions printed on the bill. If no item description is printed, write "Not specified on bill". Never invent items.
- category: the best match from the allowed list; use "Other" if unsure.
Return only JSON matching the schema."""


def _pdf_to_images(path: Path) -> list[bytes]:
    try:
        import fitz  # PyMuPDF
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("PDF support needs PyMuPDF: pip install pymupdf") from e
    out = []
    with fitz.open(path) as doc:
        for page in doc:
            out.append(page.get_pixmap(dpi=170).tobytes("png"))
    return out


def load_images(path: str | Path) -> list[bytes]:
    p = Path(path)
    if p.suffix.lower() == ".pdf":
        return _pdf_to_images(p)
    from PIL import Image, ImageOps

    img = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
    img.thumbnail((1600, 1600))  # keep VRAM/latency sane on a laptop
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return [buf.getvalue()]


def extract(image_bytes: bytes, model: str | None = None, timeout: int = 180) -> dict:
    payload = {
        "model": model or MODEL,
        "stream": False,
        "format": SCHEMA,
        "options": {"temperature": 0},
        "messages": [{
            "role": "user",
            "content": PROMPT,
            "images": [base64.b64encode(image_bytes).decode()],
        }],
    }
    r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=timeout)
    r.raise_for_status()
    return json.loads(r.json()["message"]["content"])


# ---------------------------------------------------------------------------
# Second attempt: ask for ALL GSTINs with their labels, then decide with code.
# ---------------------------------------------------------------------------
LIST_PROMPT = ("List every GSTIN (15-character tax number) printed on this invoice, one per line, "
               "in the format  LABEL: NUMBER  (for example 'GSTIN: ...' or 'Buyer GSTIN: ...'). "
               "Copy each character exactly. Output nothing else.")

_BUYER_WORDS = ("BUYER", "BILL TO", "BILLED TO", "CUSTOMER", "RECIPIENT", "SHIP TO", "CONSIGNEE", "PURCHASER")
_TOKEN = re.compile(r"[0-9]{2}[A-Z0-9]{13}")


def _chat_text(image_bytes: bytes, prompt: str, model: str | None = None, timeout: int = 120) -> str:
    payload = {"model": model or MODEL, "stream": False, "options": {"temperature": 0},
               "messages": [{"role": "user", "content": prompt,
                             "images": [base64.b64encode(image_bytes).decode()]}]}
    r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()["message"]["content"]


def parse_gstin_lines(text: str) -> list[tuple[str, str]]:
    found = []
    for line in text.upper().splitlines():
        label, sep, value = line.partition(":")
        if not sep:
            label, value = "", line
        m = _TOKEN.search(re.sub(r"[^A-Z0-9]", "", value))
        if m:
            found.append((label.strip(), m.group(0)))
    return found


def pick_vendor(cands: list[tuple[str, str]], buyer: str = "") -> tuple[str, str]:
    """Return (repaired_gstin, raw_token_as_read). Vendor = non-buyer label, not the buyer's number, checksum-valid first."""
    buyer = clean_gstin(buyer)
    rep = [(lab, repair_gstin(tok), tok) for lab, tok in cands]
    seller = [(g, t) for lab, g, t in rep if not any(w in lab for w in _BUYER_WORDS) and g != buyer]
    for g, t in seller:
        if gstin_valid(g):
            return g, t
    if seller:
        return seller[0]
    rest = [(g, t) for _, g, t in rep if g != buyer]
    return rest[0] if rest else ("", "")


def pick_vendor_gstin(cands, buyer: str = "") -> str:
    return pick_vendor(cands, buyer)[0]


def find_vendor_gstin(image_bytes: bytes, buyer_gstin: str = "", model: str | None = None) -> tuple[str, str]:
    return pick_vendor(parse_gstin_lines(_chat_text(image_bytes, LIST_PROMPT, model=model)), buyer_gstin)