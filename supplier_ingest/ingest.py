# supplier_ingest/ingest.py

import os
import json
import asyncio
from uuid import uuid4
from supabase import create_client, Client
from telegram import Bot
from telegram.error import TelegramError
from PIL import Image
import pytesseract
import tempfile
import requests

# ─── Supabase client ─────────────────────────────────────────────────────────
SUPABASE_URL              = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# ─── Telegram client ─────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TG_CHANNEL_ID      = os.getenv("TG_CHANNEL_ID")  # e.g. "@supplier_channel"
if not TELEGRAM_BOT_TOKEN or not TG_CHANNEL_ID:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TG_CHANNEL_ID")
bot = Bot(token=TELEGRAM_BOT_TOKEN)

# ─── OCR + normalization ──────────────────────────────────────────────────────
def ocr_image(path: str) -> str:
    img = Image.open(path)
    text = pytesseract.image_to_string(img, lang="eng+fas")
    return text.strip()

def normalize(text: str) -> str:
    return " ".join(text.split())

# ─── State helpers ────────────────────────────────────────────────────────────
def get_last_offset() -> int:
    resp = supabase.table("ingest_state")\
                   .select("offset_id")\
                   .eq("id", "telegram_suppliers")\
                   .single().execute()
    row = resp.data
    return int(row["offset_id"]) if row else 0

def set_last_offset(offset: int):
    supabase.table("ingest_state").upsert({
        "id": "telegram_suppliers",
        "offset_id": offset
    }).execute()

# ─── Queue into supplier_queue ────────────────────────────────────────────────
def queue_supplier(image_url: str, raw_text: str, extracted_name: str, supplier: str):
    supabase.table("supplier_queue").insert({
        "id": str(uuid4()),
        "image_url": image_url,
        "raw_ocr_text": raw_text,
        "extracted_name": extracted_name,
        "supplier": supplier,
        "status": "pending"
    }).execute()

# ─── Telegram handler ─────────────────────────────────────────────────────────
def handle_telegram():
    last = get_last_offset()
    try:
        updates = bot.get_updates(offset=last+1, timeout=10)
    except TelegramError as e:
        print("[ERROR] Telegram fetch:", e)
        return

    max_id = last
    for u in updates:
        if u.update_id > max_id:
            max_id = u.update_id

        msg = u.message
        if not msg:
            continue

        # get caption or text (we expect short desc in caption)
        text = (msg.caption or msg.text or "").strip()
        # gather any photo URLs
        media_urls = []
        if msg.photo:
            # pick highest-resolution
            file_id = msg.photo[-1].file_id
            file = bot.get_file(file_id)
            url = file.file_path
            media_urls.append(url)

        # for each attached photo, OCR + normalize + queue
        for url in media_urls:
            # download temporarily
            r = requests.get(url, stream=True)
            with tempfile.NamedTemporaryFile(suffix=".jpg") as tmp:
                for chunk in r.iter_content(1024):
                    tmp.write(chunk)
                tmp.flush()

                raw_text = ocr_image(tmp.name)
                name = normalize(raw_text)
                queue_supplier(url, raw_text, name, supplier="Telegram")

    if max_id != last:
        set_last_offset(max_id)
        print(f"[INFO] Updated last_offset → {max_id}")

# ─── (Stubs) WhatsApp / Instagram handlers ────────────────────────────────────
def handle_whatsapp():
    # TODO: poll via Twilio or similar, then same OCR + queue_supplier(...)
    pass

def handle_instagram():
    # TODO: fetch via Graph API or scrape DMs, then same OCR + queue_supplier(...)
    pass

# ─── Entry point ──────────────────────────────────────────────────────────────
def main():
    handle_whatsapp()
    handle_telegram()
    handle_instagram()

if __name__ == "__main__":
    main()
