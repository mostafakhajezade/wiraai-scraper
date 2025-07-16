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
from paddleocr import PaddleOCR
import requests
from PIL import Image
from supabase import create_client, Client

# ─── Configuration & Clients ─────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

SUPABASE_URL       = os.getenv("SUPABASE_URL")
SUPABASE_KEY       = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
HUGGINGFACE_TOKEN  = os.getenv("HUGGINGFACE_TOKEN")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Supabase credentials are required")
if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Telegram bot token is required")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
TELEGRAM_API_URL  = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# instantiate our OCR engines
_reader_en   = easyocr.Reader(["en"], gpu=False)
_paddle_ocr  = PaddleOCR(use_angle_cls=True, lang="en")

# HF inference endpoint for vision2text
HF_OCR_URL    = "https://api-inference.huggingface.co/pipeline/vision-to-text/Salesforce/blip2-flan-t5-base"
HF_HEADERS    = {"Authorization": f"Bearer {HUGGINGFACE_TOKEN}"} if HUGGINGFACE_TOKEN else {}

# ─── Helpers ──────────────────────────────────────────────────────────────────

def normalize(text: str) -> str:
    return " ".join(text.split())

def preprocess_img(img: np.ndarray) -> np.ndarray:
    img = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 0, 255,
                              cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if thresh.mean() < 127:
        thresh = cv2.bitwise_not(thresh)
    return thresh

def clean_eng(txt: str) -> str:
    return " ".join(re.findall(r"[A-Za-z0-9\-]{2,}", txt))

def hf_caption(path: str) -> str:
    """Call HuggingFace vision-to-text pipeline to caption the entire box."""
    if not HUGGINGFACE_TOKEN:
        return ""
    with open(path, "rb") as f:
        data = f.read()
    try:
        resp = requests.post(HF_OCR_URL, headers=HF_HEADERS, data=data, timeout=60)
        resp.raise_for_status()
        out = resp.json()
        # HF returns a list of {"generated_text": "..."}
        if isinstance(out, list) and out:
            return out[0].get("generated_text", "")
    except Exception as e:
        logging.warning("HF OCR error: %s", e)
    return ""

def ocr_band(img: np.ndarray, psm: int) -> str:
    """Tesseract → EasyOCR → PaddleOCR cascade on one band."""
    proc = preprocess_img(img)
    pil  = Image.fromarray(proc)
    txt  = pytesseract.image_to_string(pil, lang="eng", config=f"--oem 3 --psm {psm}")
    out  = clean_eng(txt)
    if len(out.split()) < 2:
        res = _reader_en.readtext(img)
        out = clean_eng(" ".join(r[1] for r in res))
    if len(out.split()) < 2:
        paddle_res = _paddle_ocr.ocr(img)
        paddle_txt = " ".join(line[1][0] for block in paddle_res for line in block)
        out = clean_eng(paddle_txt)
    return out

def extract_model_code(text: str) -> str:
    m = re.search(r"\b([A-Za-z]{2,}\d{2,})\b", text)
    return m.group(1) if m else ""

def ocr_image(path: str) -> str:
    """Split into bands, OCR each, then HF fallback if still too sparse."""
    orig = cv2.imread(path)
    h, _ = orig.shape[:2]
    bands = [
        orig[0:int(0.2*h), :],
        orig[int(0.2*h):int(0.8*h), :],
        orig[int(0.8*h):, :]
    ]

    texts = [ocr_band(b, psm=6) for b in bands]
    code  = extract_model_code(" ".join(texts))
    combined = " ".join(filter(None, texts + [code]))
    combined = normalize(combined)

    # If still too short, try full-image BLIP2 via HF
    if len(combined.split()) < 3 and HUGGINGFACE_TOKEN:
        hf = hf_caption(path)
        hf_clean = clean_eng(hf)
        if len(hf_clean.split()) >= 3:
            combined = normalize(hf_clean)

    return combined

# ─── Supabase State Helpers ───────────────────────────────────────────────────

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

# ─── Queue Row ─────────────────────────────────────────────────────────────────

def queue_supplier(image_url: str, raw_text: str, extracted_name: str, supplier: str="Telegram"):
    supabase.table("supplier_queue").insert({
        "id":             str(uuid4()),
        "image_url":      image_url,
        "raw_ocr_text":   raw_text,
        "extracted_name": extracted_name,
        "supplier":       supplier,
        "status":         "pending"
    }).execute()
    logging.info("Queued offer: %s", extracted_name)

# ─── Main Telegram Poller ──────────────────────────────────────────────────────

def handle_telegram():
    last = get_last_offset()
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

        caption = msg.get("caption") or msg.get("text") or ""
        caption = normalize(caption)

        file_id = msg["photo"][-1]["file_id"]
        try:
            fr = requests.get(f"{TELEGRAM_API_URL}/getFile",
                              params={"file_id": file_id}, timeout=30)
            fr.raise_for_status()
            fp = fr.json()["result"]["file_path"]
        except Exception as e:
            logging.error("Error getting file_path: %s", e)
            continue

        url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{fp}"
        try:
            dl = requests.get(url, stream=True, timeout=30)
            dl.raise_for_status()
            with tempfile.NamedTemporaryFile(suffix=".jpg") as tmp:
                for chunk in dl.iter_content(1024):
                    tmp.write(chunk)
                tmp.flush()

                raw  = ocr_image(tmp.name)
                full = normalize(f"{caption} {raw}")
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
