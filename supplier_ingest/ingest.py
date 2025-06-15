# supplier_ingest/ingest.py

import os
import logging
import re
import tempfile
from uuid import uuid4

import cv2
import numpy as np
import easyocr
import pytesseract
import requests
from PIL import Image
from supabase import create_client, Client

# ─── Configuration & Clients ─────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

SUPABASE_URL       = os.getenv("SUPABASE_URL")
SUPABASE_KEY       = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Supabase credentials are required")
if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Telegram bot token is required")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
TELEGRAM_API_URL  = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# instantiate an English‐only EasyOCR reader
_reader_en = easyocr.Reader(["en"], gpu=False)

# ─── Text Normalization ───────────────────────────────────────────────────────

def normalize(text: str) -> str:
    return " ".join(text.split())

# ─── OCR / Preprocessing Helpers ───────────────────────────────────────────────

def preprocess_img(img: np.ndarray) -> np.ndarray:
    img = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 0, 255,
                              cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if thresh.mean() < 127:
        thresh = cv2.bitwise_not(thresh)
    return thresh

def clean_eng(txt: str) -> str:
    # keep only A–Z a–z 0–9 – and spaces
    return " ".join(re.findall(r"[A-Za-z0-9\-]{2,}", txt))

def ocr_band(img: np.ndarray, psm: int) -> str:
    """
    English‐only OCR on one band: Tesseract → EasyOCR-EN fallback.
    """
    proc = preprocess_img(img)
    pil  = Image.fromarray(proc)
    # first pass: Tesseract EN
    txt  = pytesseract.image_to_string(pil, lang="eng", config=f"--oem 3 --psm {psm}")
    out  = clean_eng(txt)
    # if too few words, fallback to EasyOCR-EN
    if len(out.split()) < 2:
        res = _reader_en.readtext(img)
        out = clean_eng(" ".join([r[1] for r in res]))
    return out

def extract_model_code(text: str) -> str:
    m = re.search(r"\b([A-Za-z]{2,}\d{2,})\b", text)
    return m.group(1) if m else ""

def ocr_image(path: str) -> str:
    """
    Split into top/middle/bottom, OCR each EN-only, then merge.
    """
    orig = cv2.imread(path)
    h, _ = orig.shape[:2]

    top    = orig[0:int(0.2*h), :]
    middle = orig[int(0.2*h):int(0.8*h), :]
    bottom = orig[int(0.8*h):, :]

    t1 = ocr_band(top,    psm=6)
    t2 = ocr_band(middle, psm=6)
    t3 = ocr_band(bottom, psm=6)

    code = extract_model_code(" ".join([t1, t2, t3]))
    combined = " ".join(filter(None, [t1, t2, t3, code]))
    return normalize(combined)

# ─── Ingest State Helpers ─────────────────────────────────────────────────────

def get_last_offset() -> int:
    resp = (supabase.table("ingest_state")
                   .select("offset_id")
                   .eq("id", "telegram_suppliers")
                   .single()
                   .execute())
    row = resp.data
    return int(row["offset_id"]) if row else 0

def set_last_offset(offset: int):
    supabase.table("ingest_state").upsert({
        "id":         "telegram_suppliers",
        "offset_id":  offset
    }).execute()

# ─── Queue to supplier_queue ───────────────────────────────────────────────────

def queue_supplier(image_url: str, raw_text: str, extracted_name: str, supplier: str="Telegram"):
    supabase.table("supplier_queue").insert({
        "id":             str(uuid4()),
        "image_url":      image_url,
        "raw_ocr_text":   raw_text,
        "extracted_name": extracted_name,
        "supplier":       supplier,
        "status":         "pending"
    }).execute()
    logging.info(f"Queued offer: {extracted_name}")

# ─── Telegram Handler via HTTP ─────────────────────────────────────────────────

def handle_telegram():
    last = get_last_offset()
    updates = []
    try:
        r = requests.get(f"{TELEGRAM_API_URL}/getUpdates",
                         params={"offset": last+1, "timeout": 10}, timeout=30)
        r.raise_for_status()
        updates = r.json().get("result", [])
    except Exception as e:
        logging.error("Fetch updates failed: %s", e)
        return

    max_id = last
    for u in updates:
        uid = u.get("update_id", 0)
        if uid <= last:
            continue
        max_id = max(max_id, uid)

        msg = u.get("message") or u.get("channel_post")
        if not msg or not msg.get("photo"):
            continue

        # Persian caption stays as-is
        caption = msg.get("caption") or msg.get("text") or ""
        caption = normalize(caption)

        # download highest-res photo
        file_id = msg["photo"][-1]["file_id"]
        try:
            fr = requests.get(f"{TELEGRAM_API_URL}/getFile",
                              params={"file_id": file_id}, timeout=30)
            fr.raise_for_status()
            path = fr.json()["result"]["file_path"]
        except Exception as e:
            logging.error("Error getting file_path: %s", e)
            continue

        url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{path}"
        try:
            dl = requests.get(url, stream=True, timeout=30)
            dl.raise_for_status()
            with tempfile.NamedTemporaryFile(suffix=".jpg") as tmp:
                for ch in dl.iter_content(1024):
                    tmp.write(ch)
                tmp.flush()

                raw = ocr_image(tmp.name)                     # English‐only OCR
                full = normalize(f"{caption} {raw}")          # caption + box‐text
                queue_supplier(url, raw, full)

        except Exception as e:
            logging.error("Error processing %s: %s", url, e)

    if max_id != last:
        set_last_offset(max_id)
        logging.info("Updated last_offset → %d", max_id)

def main():
    handle_telegram()

if __name__ == "__main__":
    main()
