# supplier_ingest/telegram_bot_listener.py

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    filters,
    ContextTypes,
)
import tempfile, logging
from uuid import uuid4
from PIL import Image
import pytesseract
from supabase import create_client

# Supabase client
sb = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SERVICE_ROLE_KEY"]
)

def ocr_image(path):
    return pytesseract.image_to_string(Image.open(path), lang="eng+fas").strip()

def normalize(text):
    return " ".join(text.split())

def queue_supplier(image_url, raw_text, name, supplier):
    sb.table("supplier_queue").insert({
        "id": str(uuid4()),
        "image_url": image_url,
        "raw_ocr_text": raw_text,
        "extracted_name": name,
        "supplier": supplier,
        "status": "pending",
    }).execute()
    logging.info(f"Queued {name!r} from {supplier}")

# Handler for any photo—DM, forward, or group
async def on_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    # Only proceed if it's a forwarded message
    if not msg.forward_date:
        return

    supplier = msg.forward_from_chat.username or str(msg.forward_from_chat.id)
    text = (msg.caption or msg.text or "").strip()

    photo = msg.photo[-1]
    f = await ctx.bot.get_file(photo.file_id)
    with tempfile.NamedTemporaryFile(suffix=".jpg") as tmp:
        await f.download_to_drive(tmp.name)
        raw = ocr_image(tmp.name)

    combined = normalize(f"{text} {raw}")
    queue_supplier(f.file_path, combined, combined, supplier)

    # Optional: acknowledge to the supplier
    await update.message.reply_text(f"✅ Received and queued “{combined}”")

async def main():
    logging.basicConfig(level=logging.INFO)
    app = ApplicationBuilder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    logging.info("Starting bot, waiting for forwarded supplier images…")
    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
