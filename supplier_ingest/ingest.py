# supplier_ingest/ingest.py

import os
import logging
import requests
import tempfile
from uuid import uuid4
from supabase import create_client, Client

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

# ─── ENV & CLIENTS ────────────────────────────────────────────────────────────
SUPABASE_URL   = os.getenv("SUPABASE_URL")
SUPABASE_KEY   = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
HF_TOKEN       = os.getenv("HUGGINGFACE_TOKEN")

if not (SUPABASE_URL and SUPABASE_KEY and TELEGRAM_TOKEN and HF_TOKEN):
    raise RuntimeError("Missing one of SUPABASE_URL, SUPABASE_KEY, TELEGRAM_BOT_TOKEN or HUGGINGFACE_TOKEN")

sb = create_client(SUPABASE_URL, SUPABASE_KEY)
API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

HF_URL = "https://api-inference.huggingface.co/pipeline/vision-to-text/Salesforce/blip2-flan-t5-base"
HF_HEADERS = {"Authorization": f"Bearer {HF_TOKEN}"}

# ─── HELPERS ───────────────────────────────────────────────────────────────────
def hf_ocr(path: str) -> str:
    """Caption the image via HF's BLIP2 vision-to-text."""
    with open(path, "rb") as f:
        data = f.read()
    try:
        res = requests.post(HF_URL, headers=HF_HEADERS, data=data, timeout=60)
        res.raise_for_status()
        out = res.json()
        if isinstance(out, list) and out:
            return out[0].get("generated_text", "").strip()
    except Exception as e:
        logging.warning("HF OCR failed: %s", e)
    return ""

def get_last_offset() -> int:
    r = sb.table("ingest_state") \
          .select("offset_id") \
          .eq("id", "telegram_suppliers") \
          .single() \
          .execute()
    return int(r.data["offset_id"]) if r.data else 0

def set_last_offset(offset: int):
    sb.table("ingest_state") \
      .upsert({"id": "telegram_suppliers", "offset_id": offset}) \
      .execute()

def queue_supplier(image_url: str, caption: str, box_text: str):
    full = (caption + " " + box_text).strip()
    sb.table("supplier_queue").insert({
        "id":             str(uuid4()),
        "image_url":      image_url,
        "raw_ocr_text":   box_text,
        "extracted_name": full,
        "supplier":       "Telegram",
        "status":         "pending"
    }).execute()
    logging.info("Queued offer: %s", full)

# ─── MAIN POLLER ───────────────────────────────────────────────────────────────
def handle_telegram():
    last = get_last_offset()
    try:
        resp = requests.get(f"{API}/getUpdates",
                            params={"offset": last+1, "timeout": 10}, timeout=30)
        resp.raise_for_status()
        updates = resp.json().get("result", [])
    except Exception as e:
        logging.error("Failed fetchUpdates: %s", e)
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
        # download Telegram file_path
        file_id = msg["photo"][-1]["file_id"]
        try:
            meta = requests.get(f"{API}/getFile",
                                params={"file_id": file_id}, timeout=20).json()
            path = meta["result"]["file_path"]
        except Exception as e:
            logging.error("getFile failed: %s", e)
            continue

        url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{path}"
        # fetch to temp, run HF OCR
        try:
            dl = requests.get(url, stream=True, timeout=30); dl.raise_for_status()
            with tempfile.NamedTemporaryFile(suffix=".jpg") as tmp:
                for chunk in dl.iter_content(1024):
                    tmp.write(chunk)
                tmp.flush()

                box_text = hf_ocr(tmp.name)
                queue_supplier(url, caption, box_text)

        except Exception as e:
            logging.error("Processing %s failed: %s", url, e)

    if max_id != last:
        set_last_offset(max_id)
        logging.info("Updated last_offset → %d", max_id)

if __name__ == "__main__":
    handle_telegram()
