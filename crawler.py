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

import openai

# ──────────────────────────────────────────────────────────────────────────────
# 1) ─── SUPABASE (hard-coded) ─────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────────────
#
# Replace these two lines with your actual Supabase project URL and service-role key.
# Be sure **NOT** to include the angle brackets. For example:
# SUPABASE_URL = "https://abc123xyz.supabase.co"
# SUPABASE_SERVICE_ROLE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.…"
#
SUPABASE_URL = "https://djjmhfffusochizzkhqh.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRqam1oZmZmdXNvY2hpenpraHFoIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc0ODE4MjAwMiwiZXhwIjoyMDYzNzU4MDAyfQ._YkNr4oO5jQ2y-X4ggJjwcTZKphxyo8p4TkuPZCxNCA"

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY (hard-coded)")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


# ──────────────────────────────────────────────────────────────────────────────
# 2) ─── OPENROUTER SETTINGS ───────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────────────
#
# Sign up at https://openrouter.ai, create an API key, and paste it here. For example:
# OPENROUTER_API_KEY = "or-sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
#
OPENROUTER_API_KEY = "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"

if not OPENROUTER_API_KEY:
    raise RuntimeError("Missing OPENROUTER_API_KEY (hard-coded)")

# OpenRouter’s “OpenAI-compatible” base URL:
OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"

# Tell the `openai` library to send requests to OpenRouter instead of api.openai.com:
openai.api_key = OPENROUTER_API_KEY
openai.api_base = OPENROUTER_API_BASE


# ──────────────────────────────────────────────────────────────────────────────
# 3) ─── HELPERS: Digit conversion & similarity functions ─────────────────────
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


def get_embedding(text: str, model: str = "mistralai/devstral-small:free") -> list[float]:
    """
    Fetch a single embedding vector from OpenRouter (via openai.embeddings.create).
    Raises if the API call fails.
    """
    response = openai.embeddings.create(
        model=model,
        input=text
    )
    # response["data"] is a list, and we take the first element’s "embedding" field
    return response["data"][0]["embedding"]


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


def semantic_score(a: str, b: str, model: str = "mistralai/devstral-small:free") -> float:
    """
    Get embeddings for `a` and `b` and return their cosine similarity.
    If anything goes wrong (e.g. rate limit, model not found), this function
    will raise. The caller should catch and fall back to fuzzy.
    """
    emb_a = get_embedding(a, model=model)
    emb_b = get_embedding(b, model=model)
    return cosine_similarity(emb_a, emb_b)


# ──────────────────────────────────────────────────────────────────────────────
# 4) ─── Crawl4AI and HTML link extractor ───────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────────────

async def fetch_page(crawler: AsyncWebCrawler, url: str) -> str:
    """
    Uses Crawl4AI to fetch a URL asynchronously. Returns the raw HTML string if successful,
    or an empty string on failure.
    """
    res = await crawler.arun(url)
    if res.success:
        return res.html
    print(f"[ERROR] couldn't fetch {url}")
    return ""


def extract_links(html: str, selector: str, base_url: str) -> list[str]:
    """
    Given a chunk of HTML, return a deduplicated list of all `href` values found
    by `soup.select(selector)`, turning them into absolute URLs relative to base_url
    if needed.
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
# 5) ─── Wiraa.ir PRODUCT DATA EXTRACTOR ───────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────────────

def extract_product_data(html: str) -> dict:
    """
    Parses a Wiraa.ir product page’s HTML and extracts:
      - name: string inside <h1 data-product="title">…</h1>
      - price: integer price (in Tomans), stripping any non-digits & Persian digits
    Returns {"name": str, "price": int}.
    """
    soup = BeautifulSoup(html, "html.parser")

    title_el = soup.select_one('h1[data-product="title"]')
    name = title_el.text.strip() if title_el else "No Name"

    price_el = soup.select_one("div.styles__price___1uiIp.js-price")
    raw_price = price_el.text.strip() if price_el else "0"
    # Convert Persian digits → English, remove non-digits, then parse
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

    # 1) Fetch homepage, grab category URLs
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

        # 3) Visit each product page
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

            # 3c) Fetch the newly inserted/updated product ID
            res = supabase.table("products") \
                .select("id") \
                .eq("url", product["url"]) \
                .single() \
                .execute()
            product_id = res.data["id"]
            print(f"  • Stored product: {product['name']}  (id={product_id})")

            # 4) Query Torob for competitors
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
                    # If embedding fails, warn and fallback to fuzzy only
                    print(f"      [WARN] Semantic error: {sem_e}, falling back to fuzzy")
                    s_score = 0.0
                combined = max(f_score, s_score)
                scored.append((combined, item))

            # 5b) Sort by combined similarity (descending) and pick top 5
            scored.sort(key=lambda x: x[0], reverse=True)
            top_five = [it for _, it in scored[:5]]

            # 6) From the top five, take the first three competitor entries
            for candidate in top_five[:3]:
                comp_price = candidate.get("price", 0)
                raw_shop = (candidate.get("shop_text") or "").strip()
                link_path = candidate.get("web_client_absolute_url") or candidate.get("more_info_url")
                seller = raw_shop if raw_shop else "unknown"

                # 6a) If this listing says “در X فروشگاه” (multi-store), follow link_path
                if "فروشگاه" in raw_shop and link_path:
                    detail_url = link_path if link_path.startswith("http") else "https://torob.com" + link_path
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

                # 7) Upsert competitor_prices with (product_id, competitor_name) → competitor_price
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
