import asyncio
from crawl4ai import AsyncWebCrawler
from bs4 import BeautifulSoup
from supabase import create_client, Client
import os
import re
from urllib.parse import urljoin

# تنظیمات Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def persian_to_english_numbers(text: str) -> str:
    persian_nums = "۰۱۲۳۴۵۶۷۸۹"
    english_nums = "0123456789"
    translation_table = str.maketrans("".join(persian_nums), "".join(english_nums))
    return text.translate(translation_table)

async def fetch_page(crawler, url: str) -> str:
    result = await crawler.arun(url)
    if result.success:
        return result.html
    else:
        print(f"Failed to fetch {url}")
        return ""

def extract_product_links(category_html, base_url) -> list[str]:
    soup = BeautifulSoup(category_html, "html.parser")
    links = []
    for a in soup.select("a[href^='/product/']"):
        href = a.get("href")
        if href:
            full_url = urljoin(base_url, href)
            if full_url not in links:
                links.append(full_url)
    return links

def extract_product_data(product_html):
    soup = BeautifulSoup(product_html, "html.parser")
    name_tag = soup.select_one("h2.styles__title___EVTlZ")
    name = name_tag.text.strip() if name_tag else "No Name"

    price_tag = soup.select_one("div.styles__price___1uiIp.js-price")
    price = price_tag.text.strip() if price_tag else "No Price"
    price = persian_to_english_numbers(price)
    price = re.sub(r"[^\d]", "", price)  # فقط اعداد نگه داشته شوند

    return {"name": name, "price": price}

async def main():
    base_url = "https://wiraa.ir"
    category_url = f"{base_url}/category/آبمیوه-گیر"

    crawler = AsyncWebCrawler()

    category_html = await fetch_page(crawler, category_url)
    if not category_html:
        print("Failed to fetch category page")
        return

    product_links = extract_product_links(category_html, base_url)
    print(f"Found {len(product_links)} products.")

    for url in product_links:
        product_html = await fetch_page(crawler, url)
        if not product_html:
            continue
        product_data = extract_product_data(product_html)
        product_data["url"] = url

        res = supabase.table("products").insert(product_data).execute()
        if res.error is None:
            print(f"Inserted product: {product_data['name']}")
        else:
            print(f"Failed to insert product: {product_data['name']} - {res.error}")

if __name__ == "__main__":
    asyncio.run(main())
