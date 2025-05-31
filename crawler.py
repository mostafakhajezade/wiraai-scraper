# crawler.py

import os
import re
import math
import asyncio
from difflib import SequenceMatcher

from bs4 import BeautifulSoup
from supabase import create_client, Client
from crawl4ai import AsyncWebCrawler
from torob_integration.api import Torob

import openai

# ──────────────────────────────────────────────────────────────────────────────
# 1) SET UP ENVIRONMENT / CLIENTS
# ──────────────────────────────────────────────────────────────────────────────

# 1.a) Supabase (Service‐Role role to bypass RLS)
SUPABASE_URL = os.getenv("https://djjmhfffusochizzkhqh.supabase.co")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRqam1oZmZmdXNvY2hpenpraHFoIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc0ODE4MjAwMiwiZXhwIjoyMDYzNzU4MDAyfQ._YkNr4oO5jQ2y-X4ggJjwcTZKphxyo8p4TkuPZCxNCA")
if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY env var")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# 1.b) OpenRouter (OpenAI‐compatible client)
OPENROUTER_API_KEY = os.getenv("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")
OPENROUTER_API_BASE = os.getenv("OPENROUTER_API_BASE", "https://openrouter.ai/api/v1")
if not OPENROUTER_API_KEY:
    raise RuntimeError("Missing OPENROUTER_API_KEY env var")

# Configure openai to point at OpenRouter’s endpoint
openai.api_key = OPENROUTER_API_KEY
openai.api_base = OPENROUTER_API_BASE  # e.g. "https://openrouter.ai/api/v1"

# ──────────────────────────────────────────────────────────────────────────────
# 2) HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def persian_to_english_numbers(text: str) -> str:
    """
    Convert Persian/Arabic‐Indic digits to standard ASCII digits.
    """
    persian = "۰۱۲۳۴۵۶۷۸۹"
    english = "0123456789"
    return text.translate(str.maketrans(persian, english))


def fuzzy_similarity(a: str, b: str) -> float:
    """
    Return a simple fuzzy‐string similarity (0.0 – 1.0) via SequenceMatcher.
    """
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    """
    Compute cosine similarity between two equal‐length vectors (lists of floats).
    cos_sim = (a·b) / (||a|| * ||b||)
    """
    # dot product
    dot = sum(x * y for x, y in zip(vec1, vec2))
    # norms
    norm1 = math.sqrt(sum(x * x for x in vec1))
    norm2 = math.sqrt(sum(y * y for y in vec2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)


async def get_embedding_or_fallback(text: str) -> list[float]:
    """
    Try to call OpenRouter's embedding model ("openai/text-embedding-3-small").
    If it fails (network issues, model not found, etc.), return a zero‐vector
    so the fallback fuzzy similarity can be used.
    """
    try:
        resp = openai.Embedding.create(
            model="openai/text-embedding-3-small",
            input=text
        )
        # Extract the embedding (it's in resp["data"][0]["embedding"])
        return resp["data"][0]["embedding"]
    except Exception as e:
        # On any error (404, network, key missing, etc.), just return a zero vector
        # so that cosine_similarity will be 0, forcing fuzzy_similarity to dominate.
        print(f"    [WARN] embedding call failed for text='{text[:30]}...' → {e}")
        return []  # an “empty” embedding will be treated as zero‐vector


async def semantic_similarity(a: str, b: str) -> float:
    """
    Compute semantic similarity between two strings via embeddings + cosine.
    If embedding fails, returns 0.0.
    """
    emb_a = await get_embedding_or_fallback(a)
    emb_b = await get_embedding_or_fallback(b)
    if not emb_a or not emb_b:
        return 0.0
    return cosine_similarity(emb_a, emb_b)


async def fetch_page(crawler: AsyncWebCrawler, url: str) -> str:
    """
    Uses Crawl4AI to fetch the full HTML of a page. Returns HTML string or empty.
    """
    res = await crawler.arun(url)
    if res.success:
        return res.html
    print(f"[ERROR] couldn't fetch {url}")
    return ""


def extract_links(html: str, selector: str, base_url: str) -> list[str]:
    """
    Parse `html` with BeautifulSoup, select using CSS `selector` (e.g. "a[href^='/product/']"),
    and return full absolute URLs (prefixing with base_url if needed).
    """
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for a in soup.select(selector):
        href = a.get("href")
        if not href:
            continue
        if href.startswith("http"):
            full = href
        else:
            full = base_url.rstrip("/") + href
        if full not in links:
            links.append(full)
    return links


def extract_product_data(html: str) -> dict:
    """
    Given the HTML of a product page on wiraa.ir, extract:
      - name
      - price (in integer Toman)
    Return a dict: {"name": ..., "price": ...}.
    """
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one('h1[data-product="title"]')
    name = title_el.text.strip() if title_el else "No Name"

    price_el = soup.select_one("div.styles__price___1uiIp.js-price")
    raw = price_el.text.strip() if price_el else "0"
    num = re.sub(r"[^\d]", "", persian_to_english_numbers(raw))
    price = int(num) if num else 0
    return {"name": name, "price": price}


# ──────────────────────────────────────────────────────────────────────────────
# 3) MAIN CRAWLER LOGIC
# ──────────────────────────────────────────────────────────────────────────────

async def main():
    base_url = "https://wiraa.ir"
    crawler = AsyncWebCrawler()
    torob = Torob()

    # Step 1) Fetch homepage → find all category URLs
    home_html = await fetch_page(crawler, base_url)
    if not home_html:
        print("Could not fetch homepage; exiting.")
        return
    categories = extract_links(home_html, "a[href^='/category/']", base_url)
    print(f"[INFO] Found {len(categories)} categories")

    # Step 2) Loop over each category page
    for cat_url in categories:
        print(f"\n[CATEGORY] {cat_url}")
        cat_html = await fetch_page(crawler, cat_url)
        if not cat_html:
            continue

        # On the category page, gather product URLs
        products = extract_links(cat_html, "a[href^='/product/']", base_url)
        print(f" → {len(products)} products found")

        # Step 3) For each product URL, fetch product details + upsert to Supabase
        for prod_url in products:
            html = await fetch_page(crawler, prod_url)
            if not html:
                continue

            product = extract_product_data(html)
            slug = prod_url.split("/product/", 1)[-1]  # e.g. "ادکلن-دانهیل-آیکون-الیت-100-میل-Dunhill-Icon-Elite"
            product["url"] = prod_url

            # 3.a) Upsert into `products` table keyed on `url`
            supabase.table("products").upsert(product, on_conflict="url").execute()

            # 3.b) Retrieve the newly‐inserted (or existing) product ID
            prod_res = supabase.table("products").select("id").eq("url", product["url"]).single().execute()
            if not prod_res or prod_res.data is None:
                print("    [ERROR] could not retrieve product ID after upsert!")
                continue
            product_id = prod_res.data["id"]
            print(f"  • Stored product: {product['name']} (id={product_id})")

            # Step 4) Query Torob for competitor pricing
            try:
                resp = torob.search(q=product["name"], page=0)
                torob_results = resp.get("results", []) or []
            except Exception as e:
                print(f"    ↳ Torob search error for '{product['name']}': {e}")
                torob_results = []

            if not torob_results:
                continue

            # Step 5) Score each Torob result by combining fuzzy + semantic
            scored: list[tuple[float, dict]] = []
            for it in torob_results:
                name1 = it.get("name1", "")
                f_score = fuzzy_similarity(name1, product["name"])
                # Try semantic (embedding) similarity; fallback to 0
                s_score = await semantic_similarity(name1, product["name"])
                score = max(f_score, s_score)
                scored.append((score, it))

            # Sort descending by combined score
            scored.sort(key=lambda x: x[0], reverse=True)
            top_matches = [item for (_, item) in scored[:5]]

            # Step 6) For the top 3 matches, extract price + seller name
            for item in top_matches[:3]:
                comp_price = item.get("price", 0)
                raw_shop = (item.get("shop_text") or "").strip()
                link_path = item.get("web_client_absolute_url") or item.get("more_info_url")
                seller = raw_shop or "unknown"

                # If the Torob entry is a “multi‐store” entry (contains “فروشگاه”), follow the detail page
                if "فروشگاه" in raw_shop and link_path:
                    detail_url = link_path if link_path.startswith("http") else f"https://torob.com{link_path}"
                    detail_html = await fetch_page(crawler, detail_url)
                    if detail_html:
                        dsoup = BeautifulSoup(detail_html, "html.parser")
                        shops: list[str] = []
                        for a_tag in dsoup.select("a.shop-name"):
                            txt = a_tag.get_text(strip=True)
                            clean = txt.split(",")[0].strip()
                            if clean and clean not in shops:
                                shops.append(clean)
                            if len(shops) == 3:
                                break
                        if shops:
                            seller = ", ".join(shops)

                # Step 7) Upsert into `competitor_prices` using product_id as FK
                supabase.table("competitor_prices").upsert(
                    {
                        "product_id": product_id,
                        "competitor_name": seller,
                        "competitor_price": comp_price
                    },
                    on_conflict="product_id,competitor_name"
                ).execute()

                print(f"    ↳ {seller}: {comp_price}")

    print("\n[INFO] Crawl completed.")


if __name__ == "__main__":
    asyncio.run(main())
