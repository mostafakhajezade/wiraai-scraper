import os
import re
import math
import asyncio
from difflib import SequenceMatcher
from crawl4ai import AsyncWebCrawler
from bs4 import BeautifulSoup
from supabase import create_client, Client
from torob_integration.api import Torob
from openai import OpenAI

# --- Supabase setup (Service Role bypasses RLS) ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY env var")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# --- OpenRouter setup for embeddings (using OpenAI SDK) ---
OPENROUTER_API_URL = os.getenv("OPENROUTER_API_URL")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
if not OPENROUTER_API_URL or not OPENROUTER_API_KEY:
    raise RuntimeError("Missing OPENROUTER_API_URL or OPENROUTER_API_KEY env var")

# Instantiate OpenAI client, pointing at your OpenRouter endpoint
oai = OpenAI(api_key=OPENROUTER_API_KEY, base_url=OPENROUTER_API_URL)

# --- Helper: convert Persian digits to English ---
def persian_to_english_numbers(text: str) -> str:
    persian = "۰۱۲۳۴۵۶۷۸۹"
    english = "0123456789"
    return text.translate(str.maketrans(persian, english))

# --- Helper: fuzzy similarity (fallback) ---
def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

# --- Helper: compute cosine similarity between two vectors ---
def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0

# --- Helper: semantic similarity via embeddings ---
def semantic_score(a: str, b: str) -> float:
    # Obtain embedding for text A
    resp_a = oai.embeddings.create(model="text-embedding-ada-002", input=a)
    emb_a = resp_a.data[0].embedding
    # Obtain embedding for text B
    resp_b = oai.embeddings.create(model="text-embedding-ada-002", input=b)
    emb_b = resp_b.data[0].embedding
    return cosine_similarity(emb_a, emb_b)

# --- Fetch via Crawl4AI ---
async def fetch_page(crawler: AsyncWebCrawler, url: str) -> str:
    res = await crawler.arun(url)
    if res.success:
        return res.html
    print(f"[ERROR] couldn't fetch {url}")
    return ""

# --- Extract links matching a CSS selector ---
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

# --- Extract product data ---
def extract_product_data(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one('h1[data-product="title"]')
    name = title_el.text.strip() if title_el else "No Name"
    price_el = soup.select_one("div.styles__price___1uiIp.js-price")
    raw = price_el.text.strip() if price_el else "0"
    num = re.sub(r"[^\d]", "", persian_to_english_numbers(raw))
    price = int(num) if num else 0
    return {"name": name, "price": price}

# --- Main crawler logic ---
async def main():
    base_url = "https://wiraa.ir"
    crawler = AsyncWebCrawler()
    torob = Torob()

    # 1) Get categories
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

        for prod_url in products:
            html = await fetch_page(crawler, prod_url)
            if not html:
                continue

            product = extract_product_data(html)
            product["url"] = prod_url

            # 3) Upsert product record and retrieve its UUID
            supabase.table("products").upsert(product, on_conflict="url").execute()
            res = (
                supabase.table("products")
                .select("id")
                .eq("url", product["url"])
                .single()
                .execute()
            )
            product_id = res.data["id"]
            print(f"  • Stored product: {product['name']} (id={product_id})")

            # 4) Query Torob for competitor prices
            try:
                resp = torob.search(q=product["name"], page=0)
                torob_results = resp.get("results", [])
            except Exception as e:
                print(f"    ↳ Torob search error for '{product['name']}': {e}")
                continue

            # 5) Enhanced filtering by combining fuzzy and semantic similarity
            scored: list[tuple[float, dict]] = []
            for it in torob_results:
                name1 = it.get("name1", "")
                f_score = similar(name1, product["name"])
                s_score = semantic_score(name1, product["name"])
                score = max(f_score, s_score)
                scored.append((score, it))
            scored.sort(key=lambda x: x[0], reverse=True)
            top_matches = [it for _, it in scored[:5]]

            # 6) Take top 3 matches, resolve store names
            for item in top_matches[:3]:
                comp_price = item.get("price", 0)
                raw_shop = (item.get("shop_text") or "").strip()
                link_path = item.get("web_client_absolute_url") or item.get("more_info_url")
                seller = raw_shop or "unknown"

                # Handle multi-store entries
                if "فروشگاه" in raw_shop and link_path:
                    detail_url = (
                        link_path if link_path.startswith("http") else "https://torob.com" + link_path
                    )
                    detail_html = await fetch_page(crawler, detail_url)
                    if detail_html:
                        dsoup = BeautifulSoup(detail_html, "html.parser")
                        shops = []
                        for a_tag in dsoup.select("a.shop-name"):
                            name_text = a_tag.get_text(strip=True).split(",")[0].strip()
                            if name_text and name_text not in shops:
                                shops.append(name_text)
                            if len(shops) == 3:
                                break
                        if shops:
                            seller = ", ".join(shops)

                # 7) Upsert competitor prices with product_id foreign key
                supabase.table("competitor_prices").upsert(
                    {
                        "product_id": product_id,
                        "competitor_name": seller,
                        "competitor_price": comp_price,
                    },
                    on_conflict="product_id,competitor_name",
                ).execute()
                print(f"    ↳ {seller}: {comp_price}")

if __name__ == "__main__":
    asyncio.run(main())
