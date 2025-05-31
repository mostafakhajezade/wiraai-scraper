import os
import re
import asyncio
import math
from difflib import SequenceMatcher
from crawl4ai import AsyncWebCrawler
from bs4 import BeautifulSoup
from supabase import create_client, Client
from torob_integration.api import Torob
from openai import OpenAI

# ─── STEP 1: HARDCODE (OR “GITIGNORE”) YOUR CREDENTIALS ─────────────────────────
# Replace each "<…>" with your real values. Do NOT commit these to a public repo.

# 1) Your Supabase project URL and its Service Role key:
SUPABASE_URL = "https://djjmhfffusochizzkhqh.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRqam1oZmZmdXNvY2hpenpraHFoIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc0ODE4MjAwMiwiZXhwIjoyMDYzNzU4MDAyfQ._YkNr4oO5jQ2y-X4ggJjwcTZKphxyo8p4TkuPZCxNCA"

# 2) Your OpenRouter base URL and API key (for “OpenAI” compatibility):
#    - example base URL: "https://api.openrouter.ai/v1"
OPENAI_API_BASE = "https://api.openrouter.ai/v1"
OPENAI_API_KEY  = "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"
# ────────────────────────────────────────────────────────────────────────────────

# Create Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# Create OpenAI (OpenRouter) client – note use of `base_url=…`
oai = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_API_BASE)

# --- Helper: convert Persian digits to English ---
def persian_to_english_numbers(text: str) -> str:
    persian = "۰۱۲۳۴۵۶۷۸۹"
    english = "0123456789"
    return text.translate(str.maketrans(persian, english))

# --- Helper: fuzzy similarity (fallback) ---
def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

# --- Helper: call OpenAI embeddings endpoint directly and return a vector ---
def get_embedding(text: str) -> list[float]:
    """
    Returns the embedding vector for `text` by calling OpenRouter's embeddings endpoint.
    """
    resp = oai.embeddings.create(model="text-embedding-ada-002", input=text)
    # Response shape: { "data": [ { "embedding": [...], ... } ], ... }
    return resp["data"][0]["embedding"]

# --- Helper: compute cosine similarity between two vectors ---
def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))

# --- Helper: semantic similarity via embeddings (OpenRouter) ---
def semantic_score(a: str, b: str) -> float:
    """
    Returns the cosine similarity between embeddings of strings a and b.
    """
    emb_a = get_embedding(a)
    emb_b = get_embedding(b)
    return cosine_similarity(emb_a, emb_b)

# --- Fetch a page with Crawl4AI (Headless Chromium) ---
async def fetch_page(crawler: AsyncWebCrawler, url: str) -> str:
    res = await crawler.arun(url)
    if res.success:
        return res.html
    print(f"[ERROR] couldn't fetch {url}")
    return ""

# --- Extract all links matching a CSS selector, prefixing with base_url if needed ---
def extract_links(html: str, selector: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for a in soup.select(selector):
        href = a.get("href")
        if href:
            full = href if href.startswith("http") else base_url.rstrip("/") + href
            if full not in links:
                links.append(full)
    return links

# --- Extract product data (name + price) from a product page's HTML ---
def extract_product_data(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one('h1[data-product="title"]')
    name = title_el.text.strip() if title_el else "No Name"
    price_el = soup.select_one("div.styles__price___1uiIp.js-price")
    raw = price_el.text.strip() if price_el else "0"
    # Remove non-digits, convert Persian digits → English digits
    num = re.sub(r"[^\d]", "", persian_to_english_numbers(raw))
    price = int(num) if num else 0
    return {"name": name, "price": price}

# ─── MAIN crawler logic ────────────────────────────────────────────────────────
async def main():
    base_url = "https://wiraa.ir"
    crawler = AsyncWebCrawler()
    torob = Torob()

    # 1) Fetch homepage, find all category URLs
    home_html = await fetch_page(crawler, base_url)
    if not home_html:
        return

    categories = extract_links(home_html, "a[href^='/category/']", base_url)
    print(f"[INFO] Found {len(categories)} categories")

    # 2) Iterate over each category page
    for cat_url in categories:
        print(f"\n[CATEGORY] {cat_url}")
        cat_html = await fetch_page(crawler, cat_url)
        if not cat_html:
            continue

        products = extract_links(cat_html, "a[href^='/product/']", base_url)
        print(f" → {len(products)} products found")

        # 3) Iterate over each product link
        for prod_url in products:
            html = await fetch_page(crawler, prod_url)
            if not html:
                continue

            # Extract “name” and “price” from product page
            product = extract_product_data(html)
            product["url"] = prod_url

            # Upsert into Supabase “products” table (on the “url” column)
            supabase.table("products").upsert(product, on_conflict="url").execute()

            # Retrieve the newly inserted (or existing) product’s ID
            res = supabase.table("products").select("id").eq("url", product["url"]).single().execute()
            product_id = res.data["id"]
            print(f"  • Stored product: {product['name']} (id={product_id})")

            # 4) Query Torob for competitor listings matching this product’s name
            try:
                resp = torob.search(q=product["name"], page=0)
                torob_results = resp.get("results", [])
            except Exception as e:
                print(f"    ↳ Torob search error for '{product['name']}': {e}")
                continue

            # 5) Score each Torob result by fuzzy OR semantic similarity
            scored: list[tuple[float, dict]] = []
            for it in torob_results:
                name1 = it.get("name1", "")
                if not name1:
                    continue
                f_score = similar(name1, product["name"])
                s_score = semantic_score(name1, product["name"])
                score = max(f_score, s_score)
                scored.append((score, it))

            # Sort by descending similarity, take top‐5
            scored.sort(key=lambda x: x[0], reverse=True)
            top_matches = [it for _, it in scored[:5]]

            # 6) For the top‐3 matches, resolve “shop_text” and possibly follow a “multi‐store” page
            for item in top_matches[:3]:
                comp_price = item.get("price", 0)
                raw_shop = (item.get("shop_text") or "").strip()
                link_path = item.get("web_client_absolute_url") or item.get("more_info_url")
                seller = raw_shop or "unknown"

                # If the listing string contains “در X فروشگاه” → follow the detail page to extract individual shops
                if "فروشگاه" in raw_shop and link_path:
                    detail_url = link_path if link_path.startswith("http") else "https://torob.com" + link_path
                    detail_html = await fetch_page(crawler, detail_url)
                    if detail_html:
                        dsoup = BeautifulSoup(detail_html, "html.parser")
                        shops: list[str] = []
                        for a_tag in dsoup.select("a.shop-name"):
                            name_text = a_tag.get_text(strip=True).split(",")[0].strip()
                            if name_text and name_text not in shops:
                                shops.append(name_text)
                            if len(shops) == 3:
                                break
                        if shops:
                            seller = ", ".join(shops)

                # 7) Upsert into “competitor_prices” using product_id as foreign key
                supabase.table("competitor_prices").upsert(
                    {
                        "product_id":        product_id,
                        "competitor_name":   seller,
                        "competitor_price":  comp_price,
                    },
                    on_conflict="product_id,competitor_name"
                ).execute()
                print(f"    ↳ {seller}: {comp_price}")

if __name__ == "__main__":
    asyncio.run(main())
