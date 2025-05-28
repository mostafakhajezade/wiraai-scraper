import os
import re
import asyncio
from difflib import SequenceMatcher
from crawl4ai import AsyncWebCrawler
from bs4 import BeautifulSoup
from supabase import create_client, Client
from torob_integration.api import Torob

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
            slug = prod_url.split('/product/',1)[-1]
            product['url'] = prod_url

            # Upsert product record
            supabase.table('products').upsert(product, on_conflict='url').execute()
            print(f"  • Stored product: {product['name']}")

            # 3) Query Torob for competitor prices
            try:
                resp = torob.search(q=product['name'], page=0)
                torob_results = resp.get('results', [])
            except Exception as e:
                print(f"    ↳ Torob search error for '{product['name']}': {e}")
                continue

            # 4) Fuzzy filter by name similarity
            filtered = [it for it in torob_results if similar(it.get('name1',''), product['name']) >= 0.6]
            if not filtered:
                filtered = torob_results

            # 5) Take top 3 matches, resolve store names
            for item in filtered[:3]:
                comp_price = item.get('price', 0)
                raw_seller = item.get('shop_text','') or item.get('price_prefix','')
                seller = raw_seller or 'unknown'

                # If summary like "در X فروشگاه", fetch Torob product page for store list
                if seller.startswith('در'):
                    web_url = item.get('web_client_absolute_url')
                    if web_url:
                        detail_url = web_url if web_url.startswith('http') else 'https://torob.com' + web_url
                        detail_html = await fetch_page(crawler, detail_url)
                        detail_soup = BeautifulSoup(detail_html, 'html.parser')
                        # Select first 3 shop names from the Torob listing page
                        shops = [a.text.strip() for a in detail_soup.select('a[href*="/shop/"]') if a.text.strip()][:3]
                        if shops:
                            seller = ', '.join(shops)

                # Upsert competitor prices
                supabase.table('competitor_prices').upsert(
                    {
                        'product_slug': slug,
                        'competitor_name': seller,
                        'competitor_price': comp_price
                    },
                    on_conflict='product_slug,competitor_name'
                ).execute()
                print(f"    ↳ {seller}: {comp_price}")

if __name__ == '__main__':
    asyncio.run(main())