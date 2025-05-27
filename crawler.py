# -----------------------------------------------------------------------
# 🛠️ Setup Environment Variables
#
# Provide your SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY via .env or shell (see below):
#
# 1) Create a `.env` file:
#    SUPABASE_URL=https://your-project.supabase.co
#    SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJ...
#    then install `python-dotenv` and at top:
#    from dotenv import load_dotenv
#    load_dotenv()
#
# 2) Export in shell:
#    Linux/macOS:
#      export SUPABASE_URL=...
#      export SUPABASE_SERVICE_ROLE_KEY=...
#    PowerShell:
#      $env:SUPABASE_URL="..."
#      $env:SUPABASE_SERVICE_ROLE_KEY="..."
# -----------------------------------------------------------------------

import os
import re
import asyncio
from crawl4ai import AsyncWebCrawler
from bs4 import BeautifulSoup
from supabase import create_client, Client
from torob_integration.api import Torob
import requests

# --- Supabase setup (service role key to bypass RLS) ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
if not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("Missing SUPABASE_SERVICE_ROLE_KEY env var")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# --- Persian to English numbers ---
def persian_to_english_numbers(text: str) -> str:
    persian = "۰۱۲۳۴۵۶۷۸۹"
    english = "0123456789"
    return text.translate(str.maketrans(persian, english))

# --- Fetch HTML via Crawl4AI ---
async def fetch_page(crawler: AsyncWebCrawler, url: str) -> str:
    res = await crawler.arun(url)
    if res.success:
        return res.html
    print(f"[ERROR] couldn't fetch {url}")
    return ""

# --- Extract category links ---
def extract_category_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    return list({ base_url.rstrip('/') + a['href'] for a in soup.select("a[href^='/category/']") })

# --- Extract product links ---
def extract_product_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    return list({ base_url.rstrip('/') + a['href'] for a in soup.select("a[href^='/product/']") })

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

    # Fetch homepage
    homepage = await fetch_page(crawler, base_url)
    if not homepage:
        return
    categories = extract_category_links(homepage, base_url)
    print(f"[INFO] Found {len(categories)} categories")

    for cat_url in categories:
        print(f"\n[CATEGORY] {cat_url}")
        cat_html = await fetch_page(crawler, cat_url)
        if not cat_html:
            continue
        products = extract_product_links(cat_html, base_url)
        print(f" → {len(products)} products found")

        for url in products:
            html = await fetch_page(crawler, url)
            if not html:
                continue
            data = extract_product_data(html)
            data['url'] = url

            # Upsert product
            supabase.table('products').upsert(
                data,
                on_conflict='url'
            ).execute()
            print(f"  • Stored product: {data['name']}")

            # Torob search by slug
            slug = url.rsplit('/product/', 1)[-1]
            try:
                search_res = torob.search(slug, page=0).get('results', [])
            except requests.exceptions.HTTPError as e:
                print(f"    ↳ Torob search error for '{slug}': {e}")
                continue

            # For each result, call details with both prk and search_id
            for item in search_res:
                prk = item.get('prk')
                search_id = item.get('search_id')
                if not prk or not search_id:
                    continue
                try:
                    detail = torob.details(prk=prk, search_id=search_id)
                except requests.exceptions.HTTPError as e:
                    print(f"    ↳ Torob details error for prk {prk}: {e}")
                    continue

                offers = detail.get('offers', []) or detail.get('prices', [])
                for offer in offers:
                    seller = offer.get('seller_name') or offer.get('store_name') or 'unknown'
                    try:
                        price = int(offer.get('price', 0))
                    except (TypeError, ValueError):
                        price = 0

                    supabase.table('competitor_prices').upsert(
                        {
                            'product_slug': slug,
                            'competitor_name': seller,
                            'competitor_price': price
                        },
                        on_conflict='product_slug,competitor_name'
                    ).execute()
                    print(f"    ↳ {seller}: {price}")

if __name__ == '__main__':
    asyncio.run(main())