# supplier_ingest/ingest.py

import os
import logging
import asyncio
from uuid import uuid4
from supabase import create_client, Client
from telegram import Bot
from telegram.error import TelegramError
from PIL import Image
import pytesseract
import tempfile

# ─── Configuration & Clients ─────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not SUPABASE_URL or not SUPABASE_KEY:
    logging.error("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
    raise RuntimeError("Supabase credentials are required")
if not TELEGRAM_BOT_TOKEN:
    logging.error("Missing TELEGRAM_BOT_TOKEN")
    raise RuntimeError("Telegram bot token is required")

# Initialize Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Initialize Telegram Bot
bot = Bot(token=TELEGRAM_BOT_TOKEN)

# ─── OCR & Text Helpers ──────────────────────────────────────────────────────

def ocr_image(path: str) -> str:
    img = Image.open(path)
    text = pytesseract.image_to_string(img, lang="eng+fas")
    return text.strip()


def normalize(text: str) -> str:
    return " ".join(text.split())

# ─── Ingest State Helpers ─────────────────────────────────────────────────────

def get_last_offset() -> int:
    resp = supabase.table("ingest_state") \
                   .select("offset_id") \
                   .eq("id", "telegram_suppliers") \
                   .single() \
                   .execute()
    row = resp.data
    return int(row["offset_id"]) if row else 0


def set_last_offset(offset: int):
    supabase.table("ingest_state").upsert({
        "id": "telegram_suppliers",
        "offset_id": offset
    }).execute()

# ─── Queue to supplier_queue ───────────────────────────────────────────────────

def queue_supplier(image_path: str, raw_text: str, extracted_name: str, supplier: str):
    supabase.table("supplier_queue").insert({
        "id": str(uuid4()),
        "image_url": image_path,
        "raw_ocr_text": raw_text,
        "extracted_name": extracted_name,
        "supplier": supplier,
        "status": "pending"
    }).execute()
    logging.info(f"Queued offer: {extracted_name} (supplier={supplier})")

# ─── Telegram Handler ─────────────────────────────────────────────────────────

def handle_telegram():
    last_offset = get_last_offset()
    try:
        # Use asyncio event loop to call async method
        loop = asyncio.new_event_loop()
        updates = loop.run_until_complete(
            bot.get_updates(offset=last_offset + 1, timeout=10)
        )
    except TelegramError as e:
        logging.error("Failed to fetch updates from Telegram: %s", e)
        return
    finally:
        loop.close()

    max_id = last_offset
    for update in updates or []:
        uid = update.update_id
        if uid > max_id:
            max_id = uid
        msg = update.message
        if not msg or not msg.photo:
            continue

        caption = (msg.caption or msg.text or "").strip()
        file_id = msg.photo[-1].file_id
        tg_file = bot.get_file(file_id)
        with tempfile.NamedTemporaryFile(suffix=".jpg") as tmp:
            tg_file.download(custom_path=tmp.name)
            raw_text = ocr_image(tmp.name)
            name = normalize(f"{caption} {raw_text}")
            queue_supplier(tmp.name, raw_text, name, supplier="Telegram")

    if max_id != last_offset:
        set_last_offset(max_id)
        logging.info(f"Updated last_offset → {max_id}")

# ─── Entry Point ──────────────────────────────────────────────────────────────

def main():
    handle_telegram()


if __name__ == "__main__":
    main()