# supplier_ingest/ingest.py

import os
import logging
import re
import tempfile
from uuid import uuid4

import cv2
import easyocr
import numpy as np
import pytesseract
import requests
from PIL import Image
from supabase import create_client, Client

# ─── Configuration & Clients ─────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

SUPABASE_URL     = os.getenv("SUPABASE_URL")
SUPABASE_KEY     = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not SUPABASE_URL or not SUPABASE_KEY:
    logging.error("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
    raise RuntimeError("Supabase credentials are required")
if not TELEGRAM_BOT_TOKEN:
    logging.error("Missing TELEGRAM_BOT_TOKEN")
    raise RuntimeError("Telegram bot token is required")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# Instantiate EasyOCR reader once
_reader = easyocr.Reader(["en", "fa"], gpu=False)

# ─── OCR / Preprocess / Fallback Helpers ──────────────────────────────────────

def preprocess(path: str) -> Image.Image:
    """Grayscale, upscale, and threshold the image for better OCR."""
    img = cv2.imread(path)
    # upscale for more detail
    img = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # Otsu's threshold
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # invert if dark bg
    if np.mean(thresh) < 127:
        thresh = cv2.bitwise_not(thresh)
    return Image.fromarray(thresh)

def ocr_tesseract(path: str) -> str:
    """Run Tesseract OCR on a preprocessed image."""
    img = preprocess(path)
    config = "--oem 3 --psm 6"
    text = pytesseract.image_to_string(img, lang="eng+fas", config=config)
    return text.strip()

def ocr_with_fallback(path: str) -> str:
    """Try Tesseract first; if result is too short, fall back to EasyOCR."""
    text = ocr_tesseract(path)
    if len(text.split()) < 3:
        results = _reader.readtext(path)
        fallback = " ".join([r[1] for r in results])
        # merge both outputs to maximize coverage
        return (text + " " + fallback).strip()
    return text

def extract_model_code(text: str) -> str:
    """Find patterns like 'LFS017' (letters+digits) in the OCR'd text."""
    m = re.search(r"\b([A-Za-z]{2,}\d{2,})\b", text)
    return m.group(1) if m else ""

def normalize(text: str) -> str:
    """Collapse whitespace to single spaces."""
    return " ".join(text.split())

# ─── Ingest State Helpers ─────────────────────────────────────────────────────

def get_last_offset() -> int:
    resp = (
        supabase
        .table("ingest_state")
        .select("offset_id")
        .eq("id", "telegram_suppliers")
        .single()
        .execute()
    )
    row = resp.data
    return int(row["offset_id"]) if row else 0

def set_last_offset(offset: int):
    supabase.table("ingest_state").upsert({
        "id": "telegram_suppliers",
        "offset_id": offset
    }).execute()

# ─── Queue to supplier_queue ───────────────────────────────────────────────────

def queue_supplier(image_url: str, raw_text: str, extracted_name: str, supplier: str):
    supabase.table("supplier_queue").insert({
        "id":            str(uuid4()),
        "image_url":     image_url,
        "raw_ocr_text":  raw_text,
        "extracted_name": extracted_name,
        "supplier":      supplier,
        "status":        "pending"
    }).execute()
    logging.info(f"Queued offer: {extracted_name} (supplier={supplier})")

# ─── Telegram Handler via HTTP ─────────────────────────────────────────────────

def handle_telegram():
    last_offset = get_last_offset()
    params = {"offset": last_offset + 1, "timeout": 10}

    try:
        r = requests.get(f"{TELEGRAM_API_URL}/getUpdates", params=params, timeout=30)
        r.raise_for_status()
        updates = r.json().get("result", [])
    except Exception as e:
        logging.error("Failed to fetch updates: %s", e)
        return

    max_id = last_offset
    for upd in updates:
        uid = upd.get("update_id")
        if uid is None or uid <= last_offset:
            continue
        max_id = max(max_id, uid)

        msg = upd.get("message") or upd.get("channel_post")
        if not msg or not msg.get("photo"):
            continue

        caption = (msg.get("caption") or msg.get("text") or "").strip()
        file_id = msg["photo"][-1]["file_id"]

        # get file path
        try:
            fr = requests.get(f"{TELEGRAM_API_URL}/getFile", params={"file_id": file_id}, timeout=30)
            fr.raise_for_status()
            file_path = fr.json()["result"]["file_path"]
        except Exception as e:
            logging.error("Error fetching file info for %s: %s", file_id, e)
            continue

        download_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"

        # download + OCR
        try:
            dl = requests.get(download_url, stream=True, timeout=30)
            dl.raise_for_status()
            with tempfile.NamedTemporaryFile(suffix=".jpg") as tmp:
                for chunk in dl.iter_content(1024):
                    tmp.write(chunk)
                tmp.flush()

                raw_text = ocr_with_fallback(tmp.name)
                code     = extract_model_code(raw_text)
                full_name= normalize(f"{caption} {raw_text} {code}")
                queue_supplier(download_url, raw_text, full_name, supplier="Telegram")

        except Exception as e:
            logging.error("Error processing image %s: %s", download_url, e)

    if max_id != last_offset:
        set_last_offset(max_id)
        logging.info(f"Updated last_offset → {max_id}")

# ─── Entrypoint ───────────────────────────────────────────────────────────────

def main():
    handle_telegram()

if __name__ == "__main__":
    main()
