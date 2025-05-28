import os
import re
import asyncio
from difflib import SequenceMatcher
from crawl4ai import AsyncWebCrawler
from bs4 import BeautifulSoup
from supabase import create_client, Client
from torob_integration.api import Torob
import requests

# --- Supabase setup (Service Role bypasses RLS) ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY env var")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# --- Helper: convert Persian digits to English ---
def persian_to_english_numbers(text: str) -> str:
    persian = "۰۱۲۳۴۵۶۷۸۹"
    english = "0123456789"
    return text.translate(str.maketrans(persian, english))

# --- Helper: fuzzy similarity ---
def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

# --- Fetch via Crawl4AI ---
async def fetch_page(crawler: AsyncWebCrawler, url: str) -> str:
    res = await crawler.arun(url)
    if res.success:
        return res.html
    print(f"[ERROR] couldn't fetch {url}")
    return ""

# --- Extract links ---
def extract_links(html: str, selector: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    return list({ base_url.rstrip('/') + a['href'] for a in soup.select(selector) if a.get('href') })

# --- Extract product data ---
def extract_product_data(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one('h1[data-product="title"].styles__title___1LiMX')
    name = title_el.text.strip() if title_el else "No Name"
    price_el = soup.select_one("div.styles__price___1uiIp.js-price")
    raw = price_el.text.strip() if price_el else "0"
    num = re.sub(r"[^\d]", "", persian_to_english_numbers(raw))
    price = int(num) if num else 0
    return {"name": name, "price": price}

# --- Main ---
async def main():
    base_url = "https://wiraa.ir"
    crawler = AsyncWebCrawler()
    torob = Torob()

    # 1) Categories
    home = await fetch_page(crawler, base_url)
    if not home:
        return
    categories = extract_links(home, "a[href^='/category/']", base_url)
    print(f"[INFO] Found {len(categories)} categories")

    for cat in categories:
        print(f"\n[CATEGORY] {cat}")
        ch = await fetch_page(crawler, cat)
        if not ch:
            continue
        products = extract_links(ch, "a[href^='/product/']", base_url)
        print(f" → {len(products)} products found")

        for url in products:
            html = await fetch_page(crawler, url)
            if not html:
                continue
            product = extract_product_data(html)
            slug = url.split('/product/',1)[-1]
            product['url'] = url

            # Upsert product
            supabase.table('products').upsert(product, on_conflict='url').execute()
            print(f"  • Stored product: {product['name']}")

            # 2) Torob search
            try:
                resp = torob.search(q=product['name'], page=0)
                torob_res = resp.get('results', [])
            except requests.exceptions.HTTPError as e:
                print(f"    ↳ Torob API error for '{product['name']}': {e}")
                continue

            # 3) Filter to fuzzy matches
            filtered = [item for item in torob_res if similar(item.get('name1',''), product['name']) >= 0.6]
            if not filtered:
                filtered = torob_res

            # 4) Store top 3 competitor prices with real names
            for item in filtered[:3]:
                seller = item.get('shop_text') or item.get('direct_cta','unknown')
                # if summary says "در X فروشگاه", fetch detail page
                if seller.startswith('در') and item.get('prk') and item.get('search_id'):
                    try:
                        detail = torob.details(prk=item['prk'], search_id=item['search_id'])
                        shops = [d.get('shop_text') or d.get('shop_name','') for d in detail.get('items', [])]
                        seller = ', '.join(shops[:3]) if shops else seller
                    except Exception as e:
                        print(f"    [ERROR] could fetch detail for '{seller}': {e}")
                comp_price = item.get('price', 0)
                supabase.table('competitor_prices').upsert(
                    {'product_slug': slug, 'competitor_name': seller, 'competitor_price': comp_price},
                    on_conflict='product_slug,competitor_name'
                ).execute()
                print(f"    ↳ {seller}: {comp_price}")

if __name__ == '__main__':
    asyncio.run(main())