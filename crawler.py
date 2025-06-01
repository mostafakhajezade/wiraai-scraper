# crawler.py
import os
import re
import json
import asyncio
from difflib import SequenceMatcher
from crawl4ai import AsyncWebCrawler
from bs4 import BeautifulSoup
from supabase import create_client, Client
from torob_integration.api import Torob
from huggingface_hub import InferenceClient
from uuid import uuid4

# ─── 1) Supabase configuration ──────────────────────────────────────────────
# Paste your Supabase URL and Service-Role Key directly here:
SUPABASE_URL              = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")

# Initialize Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# ─── 2) Hugging Face configuration (optional) ───────────────────────────────
# If you have an HF token with inference access:
HF_API_TOKEN = os.getenv("HF_API_TOKEN")  # or hard-code "hf_xxx..." for quick tests
if not HF_API_TOKEN:
    print("[WARN] No HF_API_TOKEN set → Will only use fuzzy matching.")
    hf_client = None
else:
    hf_client = InferenceClient(token=HF_API_TOKEN)

# ─── 3) Helper functions ─────────────────────────────────────────────────────
def persian_to_english_numbers(text: str) -> str:
    persian = "۰۱۲۳۴۵۶۷۸۹"
    english = "0123456789"
    return text.translate(str.maketrans(persian, english))

def fuzzy_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

async def get_semantic_score(a: str, b: str) -> float:
    """
    Compute cosine similarity of embeddings via HF InferenceClient.
    Returns -1.0 on any failure (→ fallback to fuzzy only).
    """
    if not hf_client:
        return -1.0

    try:
        resp_a = hf_client.text_embedding(
            model="sentence-transformers/all-MiniLM-L6-v2",
            inputs=[a]
        )
        resp_b = hf_client.text_embedding(
            model="sentence-transformers/all-MiniLM-L6-v2",
            inputs=[b]
        )
        emb_a = resp_a["embeddings"][0]
        emb_b = resp_b["embeddings"][0]
        dot = sum(x*y for x, y in zip(emb_a, emb_b))
        norm_a = sum(x*x for x in emb_a) ** 0.5
        norm_b = sum(y*y for y in emb_b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return -1.0
        return dot / (norm_a * norm_b)
    except Exception as e:
        print(f"[WARN] HF semantic error: {e} → fallback to fuzzy only.")
        return -1.0

async def fetch_page(crawler: AsyncWebCrawler, url: str) -> str:
    res = await crawler.arun(url)
    if res.success:
        return res.html
    print(f"[ERROR] Failed to fetch {url}")
    return ""

def extract_product_data(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one('h1[data-product="title"]')
    name = title_el.get_text(strip=True) if title_el else "No Name"

    price_el = soup.select_one("div.styles__price___1uiIp.js-price")
    raw = price_el.get_text(strip=True) if price_el else "0"
    digits = re.sub(r"[^\d]", "", persian_to_english_numbers(raw))
    price = int(digits) if digits else 0
    return {"name": name, "price": price}

def extract_links(html: str, selector: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for a in soup.select(selector):
        href = a.get("href")
        if not href:
            continue
        full = href if href.startswith("http") else base_url.rstrip("/") + href
        if full not in results:
            results.append(full)
    return results

# ─── 4) Main crawler logic ───────────────────────────────────────────────────
async def main():
    base_url = "https://wiraa.ir"
    crawler = AsyncWebCrawler()
    torob = Torob()

    # 4.1) Fetch home page & extract categories
    home_html = await fetch_page(crawler, base_url)
    if not home_html:
        print("[FATAL] Couldn’t fetch the home page.")
        return

    categories = extract_links(home_html, "a[href^='/category/']", base_url)
    print(f"[INFO] Found {len(categories)} categories")

    for cat_url in categories:
        print(f"\n[CATEGORY] {cat_url}")
        cat_html = await fetch_page(crawler, cat_url)
        if not cat_html:
            continue

        # 4.2) Extract all product URLs under that category
        product_urls = extract_links(cat_html, "a[href^='/product/']", base_url)
        print(f" → {len(product_urls)} products found in this category")

        for prod_url in product_urls:
            html = await fetch_page(crawler, prod_url)
            if not html:
                continue

            # 4.3) Extract name, price, and compute slug
            product = extract_product_data(html)
            slug = prod_url.split("/product/", 1)[-1]
            product["url"] = prod_url
            product["slug"] = slug

            # 4.4) Upsert product into Supabase (on_conflict="url")
            upsert_resp = supabase.table("products") \
                                 .upsert(product, on_conflict="url") \
                                 .execute()
            # Note: we no longer do “if upsert_resp.error” because APIResponse has no attribute .error
            if upsert_resp.data is None:
                print(f"[ERROR] Supabase returned no data when upserting {product['name']}")
                continue

            print(f"  • Stored product: {product['name']} (slug={slug})")

            # 4.5) Retrieve the product’s UUID (primary key) from Supabase:
            fetch_id = supabase.table("products") \
                               .select("id") \
                               .eq("slug", slug) \
                               .single() \
                               .execute()
            if fetch_id.data is None:
                print(f"[ERROR] Could not fetch ID for slug={slug}")
                continue
            product_id = fetch_id.data["id"]

            # 4.6) Query Torob for competitor prices
            try:
                torob_resp = torob.search(q=product["name"], page=0)
                torob_results = torob_resp.get("results", [])
            except Exception as e:
                print(f"    ↳ Torob search failed for '{product['name']}': {e}")
                continue

            # 4.7) Score each Torob candidate
            scored_candidates = []
            for item in torob_results:
                name1 = item.get("name1", "")
                f_score = fuzzy_similarity(name1, product["name"])
                s_score = await get_semantic_score(name1, product["name"])
                if s_score < 0:
                    final_score = f_score
                else:
                    final_score = max(f_score, s_score)
                scored_candidates.append((final_score, f_score, s_score, item))

            scored_candidates.sort(key=lambda x: x[0], reverse=True)
            top_five = scored_candidates[:5]

            # 4.8) If best_score < 0.5 → send to review_queue
            if top_five:
                best_score, best_f, best_s, best_item = top_five[0]
                if best_score < 0.5:
                    review_resp = supabase.table("review_queue").insert({
                        "id": str(uuid4()),
                        "product_slug": slug,
                        "candidate_name": best_item.get("name1", ""),
                        "candidate_shop": best_item.get("shop_text", ""),
                        "fuzzy_score": round(best_f, 4),
                        "semantic_score": round(best_s, 4),
                        "raw_torob_data": json.dumps(best_item, ensure_ascii=False)
                    }).execute()
                    # Again, no .error check—just log if data is missing
                    if review_resp.data is None:
                        print(f"[WARN] Couldn’t queue '{best_item.get('name1','')}' for review.")
                    else:
                        print(f"    [REVIEW] Queued '{best_item.get('name1','')}' (score={best_score:.3f})")

            # 4.9) Upsert top-3 matches into competitor_prices
            for idx, (final_score, f_sc, s_sc, item) in enumerate(top_five[:3]):
                comp_price = item.get("price", 0)
                raw_shop = (item.get("shop_text") or "").strip()
                link_path = item.get("web_client_absolute_url") or item.get("more_info_url")
                seller = raw_shop or "unknown"

                # Follow multi-store links if necessary
                if "فروشگاه" in raw_shop and link_path:
                    detail_url = link_path if link_path.startswith("http") else "https://torob.com" + link_path
                    detail_html = await fetch_page(crawler, detail_url)
                    if detail_html:
                        dsoup = BeautifulSoup(detail_html, "html.parser")
                        shops = []
                        for a_tag in dsoup.select("a.shop-name"):
                            txt = a_tag.get_text(strip=True).split(",")[0].strip()
                            if txt and txt not in shops:
                                shops.append(txt)
                            if len(shops) >= 3:
                                break
                        if shops:
                            seller = ", ".join(shops)

                comp_resp = supabase.table("competitor_prices") \
                                    .upsert({
                                        "product_slug": slug,
                                        "competitor_name": seller,
                                        "competitor_price": comp_price
                                    }, on_conflict="product_slug,competitor_name") \
                                    .execute()
                if comp_resp.data is None:
                    print(f"[WARN] Couldn’t upsert competitor_price '{seller}' for '{product['name']}'")
                else:
                    print(f"    ↳ [{idx+1}] {seller}: {comp_price} تومان (score={final_score:.3f})")

    print("\n[Crawling Completed]")

# ─── 5) Entry Point ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    asyncio.run(main())
