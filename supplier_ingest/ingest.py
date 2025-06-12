# supplier_ingest/ingest.py

import os
import logging
from uuid import uuid4
from supabase import create_client, Client
from PIL import Image
import pytesseract
import tempfile
import requests

# ─── Configuration & Clients ─────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

# Load environment variables
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Validate configuration
if not SUPABASE_URL or not SUPABASE_KEY:
    logging.error("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
    raise RuntimeError("Supabase credentials are required")
if not TELEGRAM_BOT_TOKEN:
    logging.error("Missing TELEGRAM_BOT_TOKEN")
    raise RuntimeError("Telegram bot token is required")

# Initialize Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Telegram Bot API base URL
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# ─── OCR & Text Helpers ──────────────────────────────────────────────────────

def ocr_image(path: str) -> str:
    img = Image.open(path)
    text = pytesseract.image_to_string(img, lang="eng+fas")
    return text.strip()


def normalize(text: str) -> str:
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
        "id": str(uuid4()),
        "image_url": image_url,
        "raw_ocr_text": raw_text,
        "extracted_name": extracted_name,
        "supplier": supplier,
        "status": "pending"
    }).execute()
    logging.info(f"Queued offer: {extracted_name} (supplier={supplier})")

# ─── Telegram Handler via HTTP ─────────────────────────────────────────────────

def handle_telegram():
    last_offset = get_last_offset()
    params = {"offset": last_offset + 1, "timeout": 10}

    try:
        response = requests.get(
            f"{TELEGRAM_API_URL}/getUpdates", params=params, timeout=20
        )
        response.raise_for_status()
        data = response.json()
        updates = data.get("result", [])
    except Exception as e:
        logging.error("Failed to fetch updates from Telegram: %s", e)
        return

    max_id = last_offset
    for update in updates:
        uid = update.get("update_id")
        if uid is None:
            continue
        if uid > max_id:
            max_id = uid

        # extract message object
        msg = update.get("message") or update.get("channel_post")
        if not msg or not msg.get("photo"):
            continue

        # caption or text
        caption = (msg.get("caption") or msg.get("text") or "").strip()

        # highest-resolution photo
        photo_list = msg.get("photo")
        file_id = photo_list[-1]["file_id"]

        # get file path
        file_resp = requests.get(
            f"{TELEGRAM_API_URL}/getFile", params={"file_id": file_id}
        )
        file_resp.raise_for_status()
        file_path = file_resp.json().get("result", {}).get("file_path")
        if not file_path:
            continue

        download_url = (
            f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
        )

        # download and process image
        try:
            dl = requests.get(download_url, stream=True, timeout=20)
            dl.raise_for_status()
            with tempfile.NamedTemporaryFile(suffix=".jpg") as tmp:
                for chunk in dl.iter_content(1024):
                    tmp.write(chunk)
                tmp.flush()
                raw_text = ocr_image(tmp.name)
                name = normalize(f"{caption} {raw_text}")
                queue_supplier(download_url, raw_text, name, supplier="Telegram")
        except Exception as e:
            logging.error("Error processing image %s: %s", download_url, e)

    if max_id != last_offset:
        set_last_offset(max_id)
        logging.info(f"Updated last_offset → {max_id}")

# ─── Main Entrypoint ───────────────────────────────────────────────────────────

def main():
    handle_telegram()


if __name__ == "__main__":
    main()