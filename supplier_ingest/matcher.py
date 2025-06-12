import os
from uuid import uuid4
from rapidfuzz import fuzz
from supabase import create_client

# ─── Supabase setup ───────────────────────────────────────────────────────────
URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
sb  = create_client(URL, KEY)

# ─── Fetch pending supplier offers ────────────────────────────────────────────
def fetch_pending_offers():
    res = sb.table("supplier_queue") \
            .select("id, extracted_name, image_url, supplier") \
            .eq("status", "pending") \
            .execute()
    return res.data or []

# ─── Fetch your catalog ────────────────────────────────────────────────────────
def fetch_products():
    res = sb.table("products") \
            .select("id, product_slug, name") \
            .execute()
    return res.data or []

# ─── Insert review candidates ─────────────────────────────────────────────────
def enqueue_review(offer_id, product_id, slug, name, score, supplier, image_url):
    sb.table("review_queue").insert({
        "id":           str(uuid4()),
        "product_id":   product_id,
        "candidate_name": name,
        "candidate_shop": supplier,
        "fuzzy_score":  score,
        "semantic_score": 0,           # fill later if you add embeddings
        "raw_torob_data": {},          # optional
        "product_slug": slug,
        "status":      "pending",
        "queued_at":   "now()"
    }).execute()
    # mark original offer
    sb.table("supplier_queue").update({"status": "in_review"}) \
      .eq("id", offer_id).execute()

# ─── Main matching logic ──────────────────────────────────────────────────────
def main():
    offers  = fetch_pending_offers()
    prods   = fetch_products()
    for o in offers:
        best = None
        for p in prods:
            score = fuzz.token_sort_ratio(o["extracted_name"], p["name"])
            if not best or score > best[1]:
                best = (p, score)
        if best and best[1] >= 50:   # tune threshold
            p, sc = best
            enqueue_review(
                offer_id=o["id"],
                product_id=p["id"],
                slug=p["product_slug"],
                name=o["extracted_name"],
                score=sc,
                supplier=o["supplier"],
                image_url=o["image_url"]
            )
    print(f"Matched {len(offers)} offers into review_queue.")

if __name__ == "__main__":
    main()
