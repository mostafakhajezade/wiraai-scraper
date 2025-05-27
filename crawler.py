import os
import re
import asyncio
from crawl4ai import AsyncWebCrawler
from bs4 import BeautifulSoup
from supabase import create_client, Client
from torob_integration.api import Torob

# --- Supabase setup ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Helpers ---
def persian_to_english_numbers(text: str) -> str:
    persian = "۰۱۲۳۴۵۶۷۸۹"
    english = "0123456789"
    return text.translate(str.maketrans(persian, english))

async def fetch_page(crawler: AsyncWebCrawler, url: str) -> str:
    res = await crawler.arun(url)
    if res.success:
        return res.html
    print(f"[ERROR] couldn’t fetch {url}")
    return ""

def extract_category_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for a in soup.select("a[href^='/category/']"):
        href = a["href"]
        full = base_url.rstrip("/") + href
        if full not in out:
            out.append(full)
    return out

def extract_product_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for a in soup.select("a[href^='/product/']"):
        href = a["href"]
        full = base_url.rstrip("/") + href
        if full not in out:
            out.append(full)
    return out

def extract_product_data(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    # match H1 with data-product="title"
    title_el = soup.select_one('h1[data-product="title"].styles__title___1LiMX')
    name = title_el.text.strip() if title_el else "No Name"
    price_el = soup.select_one("div.styles__price___1uiIp.js-price")
    raw = price_el.text.strip() if price_el else "0"
    num = re.sub(r"[^\d]", "", persian_to_english_numbers(raw))
    return {"name": name, "price": num}

async def main():
    base_url = "https://wiraa.ir"
    crawler = AsyncWebCrawler()
    torob = Torob()

    # 1) Grab all categories
    home = await fetch_page(crawler, base_url)
    if not home:
        return
    categories = extract_category_links(home, base_url)
    print(f"Found {len(categories)} categories")

    # 2) Loop each category
    for cat in categories:
        print(f"\n[CATEGORY] {cat}")
        cat_html = await fetch_page(crawler, cat)
        if not cat_html:
            continue
        products = extract_product_links(cat_html, base_url)
        print(f" → {len(products)} products")

        # derive slugs for Torob
        slugs = [u.rsplit("/product/",1)[1] for u in products]

        # 3) Loop each product
        for url, slug in zip(products, slugs):
            page = await fetch_page(crawler, url)
            if not page:
                continue
            data = extract_product_data(page)
            data["url"] = url

            # upsert into your own products table
            supabase.table("products").upsert(data, on_conflict="url").execute()
            print(f"  • Stored: {data['name']}")

            # 4) Fetch competitor prices from Torob
            torob_res = torob.search(slug, page=0).get("results", [])
            for item in torob_res:
                seller = item.get("seller_name") or "unknown"
                cp = int(item.get("price", 0))
                supabase.table("competitor_prices").upsert(
                    {
                      "product_slug": slug,
                      "competitor_name": seller,
                      "competitor_price": cp
                    },
                    on_conflict="product_slug,competitor_name"
                ).execute()
                print(f"    ↳ {seller}: {cp}")

if __name__ == "__main__":
    asyncio.run(main())
