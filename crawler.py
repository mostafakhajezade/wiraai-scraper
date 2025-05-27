import os
import re
import asyncio
from crawl4ai import AsyncWebCrawler
from bs4 import BeautifulSoup
from supabase import create_client, Client
from torob_integration.api import Torob
import requests

# --- Supabase setup ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Helper to convert Persian numbers ---
def persian_to_english_numbers(text: str) -> str:
    persian = "۰۱۲۳۴۵۶۷۸۹"
    english = "0123456789"
    return text.translate(str.maketrans(persian, english))

# --- Fetch a page via Crawl4AI ---
async def fetch_page(crawler: AsyncWebCrawler, url: str) -> str:
    res = await crawler.arun(url)
    if res.success:
        return res.html
    print(f"[ERROR] couldn't fetch {url}")
    return ""

# --- Extract category links from homepage ---
def extract_category_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.select("a[href^='/category/']"):
        href = a.get('href')
        full = base_url.rstrip('/') + href
        if full not in links:
            links.append(full)
    return links

# --- Extract product links from a category page ---
def extract_product_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.select("a[href^='/product/']"):
        href = a.get('href')
        full = base_url.rstrip('/') + href
        if full not in links:
            links.append(full)
    return links

# --- Extract product data (name and price) ---
def extract_product_data(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one('h1[data-product="title"].styles__title___1LiMX')
    name = title_el.text.strip() if title_el else "No Name"
    price_el = soup.select_one("div.styles__price___1uiIp.js-price")
    raw = price_el.text.strip() if price_el else "0"
    num = re.sub(r"[^\d]", "", persian_to_english_numbers(raw))
    return {"name": name, "price": num}

# --- Main async routine ---
async def main():
    base_url = "https://wiraa.ir"
    crawler = AsyncWebCrawler()
    torob = Torob()

    # Fetch homepage and find categories
    homepage = await fetch_page(crawler, base_url)
    if not homepage:
        return
    categories = extract_category_links(homepage, base_url)

    print(f"[INFO] Found {len(categories)} categories")

    # Loop through each category
    for cat_url in categories:
        print(f"\n[CATEGORY] {cat_url}")
        cat_html = await fetch_page(crawler, cat_url)
        if not cat_html:
            continue
        products = extract_product_links(cat_html, base_url)
        print(f" → {len(products)} products found")

        # Process each product
        for url in products:
            html = await fetch_page(crawler, url)
            if not html:
                continue
            data = extract_product_data(html)
            data['url'] = url

            # Upsert into products table
            supabase.table('products').upsert(
                data,
                on_conflict='url'
            ).execute()
            print(f"  • Stored: {data['name']}")

            # Attempt fetching competitor prices via Torob
            slug = url.rsplit('/product/', 1)[-1]
            try:
                torob_res = torob.search(slug, page=0).get('results', [])
            except requests.exceptions.HTTPError as e:
                print(f"    ↳ Torob API error for '{slug}': {e}")
                continue

            # Upsert competitor prices
            for item in torob_res:
                seller = item.get('seller_name') or 'unknown'
                try:
                    price = int(item.get('price', 0))
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