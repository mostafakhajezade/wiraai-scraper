# crawler.py

import os
import re
import math
import asyncio
from difflib import SequenceMatcher

from crawl4ai import AsyncWebCrawler
from bs4 import BeautifulSoup
from supabase import create_client, Client
from torob_integration.api import Torob

import requests

# ──────────────────────────────────────────────────────────────────────────────
# 1) ─── SUPABASE (hard-coded) ─────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────────────
#
# Replace these two lines with your actual Supabase project URL and service-role key.
# Example:
#   SUPABASE_URL = "https://abc123xyz.supabase.co"
#   SUPABASE_SERVICE_ROLE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.…"
#
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY (hard-coded)")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


# ──────────────────────────────────────────────────────────────────────────────
# 2) ─── HUGGING FACE INFERENCE API SETTINGS ───────────────────────────────────
# ──────────────────────────────────────────────────────────────────────────────
#
# 1) Sign up for a free account at https://huggingface.co (if you don’t already have one).
# 2) Go to your Account Settings → Access Tokens → New Token → name it “crawler-embeddings” (scope = “read”).
# 3) Copy that token and paste it below. For example:
#       HF_API_TOKEN = "hf_xxxYOURTOKENxxx"
#
HF_API_TOKEN = os.getenv("HF_API_TOKEN")
if not HF_API_TOKEN:
    raise RuntimeError("Missing HF_API_TOKEN (set it in .env or your environment)")


# We’ll call the “all-MiniLM-L6-v2” sentence-transformers model endpoint for embeddings.
HF_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Hugging Face Inference API URL:
HF_INFERENCE_URL = f"https://api-inference.huggingface.co/embeddings/{HF_EMBEDDING_MODEL}"


# ──────────────────────────────────────────────────────────────────────────────
# 3) ─── HELPER: Digit conversion & similarity functions ────────────────────────
# ──────────────────────────────────────────────────────────────────────────────

def persian_to_english_numbers(text: str) -> str:
    """
    Convert Persian digits in `text` to English digits.
    """
    persian_digits = "۰۱۲۳۴۵۶۷۸۹"
    english_digits = "0123456789"
    return text.translate(str.maketrans(persian_digits, english_digits))


def similar(a: str, b: str) -> float:
    """
    Fuzzy/character-based similarity between two strings using SequenceMatcher.
    """
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def get_hf_embedding(text: str) -> list[float]:
    """
    Call the Hugging Face embeddings endpoint and return a single vector.
    Raises an exception if something goes wrong (e.g. rate‐limit, invalid token).
    """
    headers = {
        "Authorization": f"Bearer {HF_API_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {"inputs": text}
    resp = requests.post(HF_INFERENCE_URL, headers=headers, json=data, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Hugging Face embedding API returned {resp.status_code}: {resp.text}")
    # The response is a JSON list of floats
    embedding_vector = resp.json()
    if not isinstance(embedding_vector, list):
        raise RuntimeError(f"Unexpected HF embedding response format: {resp.text}")
    return embedding_vector


def cosine_similarity(a_emb: list[float], b_emb: list[float]) -> float:
    """
    Compute cosine similarity between two embedding vectors.
    """
    dot = sum(x * y for x, y in zip(a_emb, b_emb))
    norm_a = math.sqrt(sum(x * x for x in a_emb))
    norm_b = math.sqrt(sum(y * y for y in b_emb))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def semantic_score(a: str, b: str) -> float:
    """
    Get embeddings for `a` and `b` via Hugging Face’s Inference API
    and return their cosine similarity. Raises on error.
    """
    emb_a = get_hf_embedding(a)
    emb_b = get_hf_embedding(b)
    return cosine_similarity(emb_a, emb_b)


# ──────────────────────────────────────────────────────────────────────────────
# 4) ─── Crawl4AI fetch + HTML link extractor ──────────────────────────────────
# ──────────────────────────────────────────────────────────────────────────────

async def fetch_page(crawler: AsyncWebCrawler, url: str) -> str:
    """
    Uses Crawl4AI to fetch a URL asynchronously. Returns the HTML string if successful,
    or an empty string otherwise.
    """
    res = await crawler.arun(url)
    if res.success:
        return res.html
    print(f"[ERROR] couldn't fetch {url}")
    return ""


def extract_links(html: str, selector: str, base_url: str) -> list[str]:
    """
    Given a chunk of HTML, return a deduplicated list of all `href` values found
    by `soup.select(selector)`, turned into absolute URLs relative to base_url.
    """
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for a in soup.select(selector):
        href = a.get("href")
        if not href:
            continue
        full = href if href.startswith("http") else base_url.rstrip("/") + href
        if full not in links:
            links.append(full)
    return links


# ──────────────────────────────────────────────────────────────────────────────
# 5) ─── Wiraa.ir product‐page parser ──────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────────────

def extract_product_data(html: str) -> dict:
    """
    Parses a Wiraa.ir product page’s HTML and extracts:
      - name: string inside <h1 data-product="title">…</h1>
      - price: integer (Tomans), stripping non-digits & Persian digits
    Returns {"name": str, "price": int}.
    """
    soup = BeautifulSoup(html, "html.parser")

    title_el = soup.select_one('h1[data-product="title"]')
    name = title_el.text.strip() if title_el else "No Name"

    price_el = soup.select_one("div.styles__price___1uiIp.js-price")
    raw_price = price_el.text.strip() if price_el else "0"
    digits_only = re.sub(r"[^\d]", "", persian_to_english_numbers(raw_price))
    price = int(digits_only) if digits_only else 0

    return {"name": name, "price": price}


# ──────────────────────────────────────────────────────────────────────────────
# 6) ─── MAIN CRAWLER LOGIC ────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────────────

async def main():
    base_url = "https://wiraa.ir"
    crawler = AsyncWebCrawler()
    torob = Torob()

    # 1) Fetch homepage and get category URLs
    home_html = await fetch_page(crawler, base_url)
    if not home_html:
        return
    categories = extract_links(home_html, "a[href^='/category/']", base_url)
    print(f"[INFO] Found {len(categories)} categories")

    # 2) Iterate each category
    for cat_url in categories:
        print(f"\n[CATEGORY] {cat_url}")
        cat_html = await fetch_page(crawler, cat_url)
        if not cat_html:
            continue

        products = extract_links(cat_html, "a[href^='/product/']", base_url)
        print(f" → {len(products)} products found")

        # 3) Visit each product URL
        for prod_url in products:
            product_html = await fetch_page(crawler, prod_url)
            if not product_html:
                continue

            # 3a) Extract name & price from Wiraa.ir
            product = extract_product_data(product_html)
            product["url"] = prod_url

            # 3b) Upsert into `products` (on conflict url)
            supabase.table("products") \
                .upsert(product, on_conflict="url") \
                .execute()

            # 3c) Fetch the inserted/updated product ID
            res = supabase.table("products") \
                .select("id") \
                .eq("url", product["url"]) \
                .single() \
                .execute()
            product_id = res.data["id"]
            print(f"  • Stored product: {product['name']}  (id={product_id})")

            # 4) Query Torob for competitor listings
            try:
                torob_resp = torob.search(q=product["name"], page=0)
                torob_results = torob_resp.get("results", [])
            except Exception as e:
                print(f"    ↳ Torob search error for '{product['name']}': {e}")
                continue

            # 5) Score each Torob result by max(fuzzy, semantic)
            scored: list[tuple[float, dict]] = []
            for item in torob_results:
                name1 = item.get("name1", "")
                f_score = similar(name1, product["name"])
                try:
                    s_score = semantic_score(name1, product["name"])
                except Exception as sem_e:
                    # If the HF embedding call fails, fall back to fuzzy only
                    print(f"      [WARN] Semantic error: {sem_e}.  Falling back to fuzzy only.")
                    s_score = 0.0
                combined = max(f_score, s_score)
                scored.append((combined, item))

            # 5b) Sort descending & take top 5 candidates
            scored.sort(key=lambda x: x[0], reverse=True)
            top_five = [it for _, it in scored[:5]]

            # 6) From top 5, choose up to 3 to upsert into competitor_prices
            for candidate in top_five[:3]:
                comp_price = candidate.get("price", 0)
                raw_shop = (candidate.get("shop_text") or "").strip()
                link_path = candidate.get("web_client_absolute_url") or candidate.get("more_info_url")
                seller = raw_shop if raw_shop else "unknown"

                # 6a) If listing says “در X فروشگاه” (multi‐shop), follow detail link
                if "فروشگاه" in raw_shop and link_path:
                    detail_url = (
                        link_path
                        if link_path.startswith("http")
                        else "https://torob.com" + link_path
                    )
                    detail_html = await fetch_page(crawler, detail_url)
                    if detail_html:
                        dsoup = BeautifulSoup(detail_html, "html.parser")
                        shops_list: list[str] = []
                        for a_tag in dsoup.select("a.shop-name"):
                            txt = a_tag.get_text(strip=True).split(",")[0].strip()
                            if txt and txt not in shops_list:
                                shops_list.append(txt)
                            if len(shops_list) >= 3:
                                break
                        if shops_list:
                            seller = ", ".join(shops_list)

                # 7) Upsert competitor_prices (needs UNIQUE(product_id, competitor_name))
                supabase.table("competitor_prices") \
                    .upsert({
                        "product_id": product_id,
                        "competitor_name": seller,
                        "competitor_price": comp_price
                    }, on_conflict="product_id,competitor_name") \
                    .execute()

                print(f"    ↳ {seller}: {comp_price}")


if __name__ == "__main__":
    asyncio.run(main())
