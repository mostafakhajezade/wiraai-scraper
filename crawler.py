import os
import re
import asyncio
from difflib import SequenceMatcher
import numpy as np
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

# --- OpenAI setup for embeddings ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("Missing OPENAI_API_KEY env var")
oai = OpenAI(api_key=OPENAI_API_KEY)

# --- Helper: convert Persian digits to English ---
def persian_to_english_numbers(text: str) -> str:
    persian = "۰۱۲۳۴۵۶۷۸۹"
    english = "0123456789"
    return text.translate(str.maketrans(persian, english))

# --- Helper: fuzzy similarity (fallback) ---
def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

# --- Embedding helpers ---
def get_embedding(text: str) -> list[float]:
    resp = oai.embeddings.create(
        model="text-embedding-ada-002",
        input=text,
    )
    return resp.data[0].embedding


def cosine_similarity(a: list[float], b: list[float]) -> float:
    a_arr = np.array(a, dtype=np.float32)
    b_arr = np.array(b, dtype=np.float32)
    return float(a_arr.dot(b_arr) / (np.linalg.norm(a_arr) * np.linalg.norm(b_arr)))

# --- Helper: semantic similarity via embeddings ---
def semantic_score(a: str, b: str) -> float:
    emb_a = get_embedding(a)
    emb_b = get_embedding(b)
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
    links = []
    for a in soup.select(selector):
        href = a.get('href')
        if href:
            full = href if href.startswith('http') else base_url.rstrip('/') + href
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

    # 2) Iterate categories
    for cat_url in categories:
        cat_html = await fetch_page(crawler, cat_url)
        if not cat_html:
            continue
        products = extract_links(cat_html, "a[href^='/product/']", base_url)
        print(f"[CATEGORY] {cat_url} → {len(products)} products")

        for prod_url in products:
            html = await fetch_page(crawler, prod_url)
            if not html:
                continue

            # 3) Upsert product
            product = extract_product_data(html)
            product['url'] = prod_url
            supabase.table('products') \
                .upsert(product, on_conflict='url') \
                .execute()
            # fetch its auto-generated ID
            res = supabase.table('products') \
                .select('id') \
                .eq('url', prod_url) \
                .single() \
                .execute()
            product_id = res.data['id']
            print(f"  • Stored product: {product['name']} (id={product_id})")

            # 4) Query Torob
            try:
                resp = torob.search(q=product['name'], page=0)
                torob_results = resp.get('results', [])
            except Exception as e:
                print(f"    ↳ Torob error: {e}")
                continue

            # 5) Score matches
            scored = []
            for it in torob_results:
                name1 = it.get('name1','')
                score = max(similar(name1, product['name']), semantic_score(name1, product['name']))
                scored.append((score, it))
            scored.sort(key=lambda x: x[0], reverse=True)
            top = [it for _, it in scored[:3]]

            # 6) Upsert competitor prices
            for item in top:
                price = item.get('price', 0)
                shop = (item.get('shop_text') or '').strip()
                if 'فروشگاه' in shop and item.get('web_client_absolute_url'):
                    detail_url = item['web_client_absolute_url']
                    detail_html = await fetch_page(crawler, detail_url)
                    if detail_html:
                        dsoup = BeautifulSoup(detail_html, 'html.parser')
                        shops = [a.get_text(strip=True).split(',')[0] for a in dsoup.select('a.shop-name')][:3]
                        shop = ', '.join(shops)
                supabase.table('competitor_prices') \
                    .upsert({
                        'product_id': product_id,
                        'competitor_name': shop or 'unknown',
                        'competitor_price': price
                    }, on_conflict='product_id,competitor_name') \
                    .execute()
                print(f"    ↳ {shop}: {price}")

if __name__ == '__main__':
    asyncio.run(main())