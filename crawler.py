import asyncio
from crawl4ai import AsyncWebCrawler
from bs4 import BeautifulSoup
from supabase import create_client, Client
import os
import re

# تنظیمات Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# تبدیل اعداد فارسی به انگلیسی
def persian_to_english_numbers(text: str) -> str:
    persian_nums = "۰۱۲۳۴۵۶۷۸۹"
    english_nums = "0123456789"
    translation_table = str.maketrans(persian_nums, english_nums)
    return text.translate(translation_table)

# دریافت HTML یک صفحه
async def fetch_page(crawler, url: str) -> str:
    result = await crawler.arun(url)
    if result.success:
        return result.html
    else:
        print(f"Failed to fetch {url}")
        return ""

# گرفتن لیست دسته‌بندی‌ها
def extract_category_links(home_html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(home_html, "html.parser")
    links = []
    for a in soup.select("a[href^='/category/']"):
        href = a.get("href")
        full_url = base_url.rstrip("/") + href
        if full_url not in links:
            links.append(full_url)
    return links

# گرفتن لینک محصولات از صفحه دسته‌بندی
def extract_product_links(category_html, base_url) -> list[str]:
    soup = BeautifulSoup(category_html, "html.parser")
    links = []
    for a in soup.select("a[href^='/product/']"):
        href = a.get("href")
        full_url = base_url.rstrip("/") + href
        if full_url not in links:
            links.append(full_url)
    return links

# گرفتن اطلاعات محصول
def extract_product_data(product_html):
    soup = BeautifulSoup(product_html, "html.parser")
    name_tag = soup.select_one("h2.styles__title___EVTlZ")
    name = name_tag.text.strip() if name_tag else "No Name"

    price_tag = soup.select_one("div.styles__price___1uiIp.js-price")
    price = price_tag.text.strip() if price_tag else "No Price"
    price = persian_to_english_numbers(price)
    price = re.sub(r"[^\d]", "", price)

    return {"name": name, "price": price}

# تابع اصلی
async def main():
    base_url = "https://wiraa.ir"
    home_url = base_url

    crawler = AsyncWebCrawler()

    # 1. گرفتن دسته‌بندی‌ها
    home_html = await fetch_page(crawler, home_url)
    if not home_html:
        print("Failed to fetch homepage.")
        return

    category_links = extract_category_links(home_html, base_url)
    print(f"Found {len(category_links)} categories.")

    for category_url in category_links:
        print(f"Processing category: {category_url}")
        category_html = await fetch_page(crawler, category_url)
        if not category_html:
            continue

        product_links = extract_product_links(category_html, base_url)
        print(f"  Found {len(product_links)} products.")

        for url in product_links:
            product_html = await fetch_page(crawler, url)
            if not product_html:
                continue

            product_data = extract_product_data(product_html)
            product_data["url"] = url

            try:
                res = supabase.table("products").insert(product_data).execute()
                print(f"    Inserted product: {product_data['name']}")
            except Exception as e:
                if "duplicate key" in str(e).lower():
                    print(f"    Duplicate product skipped: {product_data['name']}")
                else:
                    print(f"    Failed to insert product: {product_data['name']} - {e}")

if __name__ == "__main__":
    asyncio.run(main())
print(f"Title from {url}: {title}")
