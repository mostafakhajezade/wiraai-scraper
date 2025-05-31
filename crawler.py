# crawler.py
import os
import re
import asyncio
from difflib import SequenceMatcher
from crawl4ai import AsyncWebCrawler
from bs4 import BeautifulSoup
from supabase import create_client, Client
from torob_integration.api import Torob
from openai import OpenAI, APIError

# ─── Supabase setup ──────────────────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY env var")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# ─── OpenRouter (OpenAI‐compatible) setup ────────────────────────────────────
OPENROUTER_API_URL = os.getenv("OPENROUTER_API_URL")    # e.g. "https://api.openrouter.ai/v1"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
if not OPENROUTER_API_URL or not OPENROUTER_API_KEY:
    raise RuntimeError("Missing OPENROUTER_API_URL or OPENROUTER_API_KEY env var")

# Instruct the OpenAI SDK to send requests to OpenRouter instead of api.openai.com:
oai = OpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url=OPENROUTER_API_URL,
    # If your OpenRouter endpoint requires an extra header or path,
    # adjust base_url accordingly (some installations are "/v1" vs "/v1/embeddings",
    # but typically "https://api.openrouter.ai/v1" works).
)

# ─── Helper: convert Persian digits to English ─────────────────────────────────
def persian_to_english_numbers(text: str) -> str:
    persian = "۰۱۲۳۴۵۶۷۸۹"
    english = "0123456789"
    return text.translate(str.maketrans(persian, english))

# ─── Helper: fuzzy string similarity (fallback) ───────────────────────────────
def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

# ─── Helper: semantic similarity via embeddings (OpenRouter) ─────────────────
async def semantic_score(a: str, b: str) -> float:
    """
    Returns cosine similarity of embeddings for strings `a` and `b`.
    If the OpenRouter call fails for any reason, we fall back to fuzzy similarity.
    """
    try:
        # Use an OpenRouter‐supported embedding model. 
        # Common free model on OpenRouter is "text-embedding-3-small".
        resp_a = await oai.embeddings.create(
            model="text-embedding-3-small",
            input=a
        )
        resp_b = await oai.embeddings.create(
            model="text-embedding-3-small",
            input=b
        )
        emb_a = resp_a["data"][0]["embedding"]
        emb_b = resp_b["data"][0]["embedding"]

        # Cosine similarity:
        dot = sum(x * y for x, y in zip(emb_a, emb_b))
        norm_a = sum(x * x for x in emb_a) ** 0.5
        norm_b = sum(x * x for x in emb_b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    except APIError as e:
        # If OpenRouter embedding fails (e.g. invalid model, rate‐limit, etc.),
        # fall back to fuzzy ratio:
        return similar(a, b)

# ─── Fetch via Crawl4AI ───────────────────────────────────────────────────────
async def fetch_page(crawler: AsyncWebCrawler, url: str) -> str:
    res = await crawler.arun(url)
    if res.success:
        return res.html
    print(f"[ERROR] couldn't fetch {url}")
    return ""

# ─── Extract links matching a CSS selector ───────────────────────────────────
def extract_links(html: str, selector: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.select(selector):
        href = a.get("href")
        if href:
            full = href if href.startswith("http") else base_url.rstrip("/") + href
            if full not in links:
                links.append(full)
    return links

# ─── Extract product data from Wiraa page ────────────────────────────────────
def extract_product_data(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one('h1[data-product="title"]')
    name = title_el.text.strip() if title_el else "No Name"
    price_el = soup.select_one("div.styles__price___1uiIp.js-price")
    raw = price_el.text.strip() if price_el else "0"
    num = re.sub(r"[^\d]", "", persian_to_english_numbers(raw))
    price = int(num) if num else 0
    return {"name": name, "price": price}

# ─── MAIN crawler logic ───────────────────────────────────────────────────────
async def main():
    base_url = "https://wiraa.ir"
    crawler = AsyncWebCrawler()
    torob = Torob()

    # 1) Fetch home page, gather category URLs
    home_html = await fetch_page(crawler, base_url)
    if not home_html:
        return
    categories = extract_links(home_html, "a[href^='/category/']", base_url)
    print(f"[INFO] Found {len(categories)} categories")

    # 2) For each category, fetch list of products
    for cat_url in categories:
        print(f"\n[CATEGORY] {cat_url}")
        cat_html = await fetch_page(crawler, cat_url)
        if not cat_html:
            continue

        products = extract_links(cat_html, "a[href^='/product/']", base_url)
        print(f" → {len(products)} products found")

        # 3) For each product page…
        for prod_url in products:
            html = await fetch_page(crawler, prod_url)
            if not html:
                continue

            product = extract_product_data(html)
            product["url"] = prod_url

            # 4) Upsert product into Supabase and fetch its UUID
            supabase.table("products").upsert(
                product,
                on_conflict="url"
            ).execute()

            # Immediately query Supabase to retrieve the UUID (id)
            row = supabase.table("products") \
                .select("id") \
                .eq("url", product["url"]) \
                .single() \
                .execute()
            if row.error or (row.data is None):
                print(f"    [ERROR] fetching product ID for URL {product['url']}")
                continue
            product_id = row.data["id"]
            print(f"  • Stored product: {product['name']} (id={product_id})")

            # 5) Query Torob API for competitor prices
            try:
                resp = torob.search(q=product["name"], page=0)
                torob_results = resp.get("results", [])
            except Exception as e:
                print(f"    ↳ Torob search error for '{product['name']}': {e}")
                continue

            # 6) Score each Torob result by fuzzy+semantic similarity
            scored = []
            for it in torob_results:
                name1 = it.get("name1", "")
                f_score = similar(name1, product["name"])
                s_score = await semantic_score(name1, product["name"])
                score = max(f_score, s_score)
                scored.append((score, it))
            scored.sort(key=lambda x: x[0], reverse=True)
            top_matches = [it for _, it in scored[:5]]

            # 7) Insert/update top 3 competitor prices
            for item in top_matches[:3]:
                comp_price = item.get("price", 0)
                raw_shop = (item.get("shop_text") or "").strip()
                link_path = item.get("web_client_absolute_url") or item.get("more_info_url")
                seller = raw_shop or "unknown"

                # 7a) If this is a “در X فروشگاه” entry, follow that Torob URL and parse first 3 shops
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
                            if len(shops) == 3:
                                break
                        if shops:
                            seller = ", ".join(shops)

                # 8) Upsert competitor_price with foreign key product_id
                supabase.table("competitor_prices").upsert(
                    {
                        "product_id": product_id,
                        "competitor_name": seller,
                        "competitor_price": comp_price
                    },
                    on_conflict="product_id,competitor_name"
                ).execute()
                print(f"    ↳ {seller}: {comp_price}")

if __name__ == "__main__":
    asyncio.run(main())
