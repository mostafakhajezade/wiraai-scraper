import asyncio
from crawl4ai import AsyncWebCrawler
from bs4 import BeautifulSoup
from supabase import create_client, Client
import os

# تنظیمات Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

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
    # فرض کنیم لینک محصولات در تگ <a> با کلاس "product-link" هست (باید طبق سایت واقعی تغییر بدی)
    for a in soup.select("a.product-link"):
        href = a.get("href")
        if href and href.startswith("/product/"):
            full_url = base_url.rstrip("/") + href
            links.append(full_url)
    return links

def extract_product_data(product_html):
    soup = BeautifulSoup(product_html, "html.parser")
    # استخراج نام محصول، فرضاً در تگ h1 با کلاس product-title
    name_tag = soup.select_one("h1.product-title")
    name = name_tag.text.strip() if name_tag else "No Name"

    # استخراج قیمت، فرضاً در span با کلاس price
    price_tag = soup.select_one("span.price")
    price = price_tag.text.strip() if price_tag else "No Price"

    return {"name": name, "price": price}

async def main():
    base_url = "https://wiraa.ir"
    category_url = f"{base_url}/category/آبمیوه-گیر"

    crawler = AsyncWebCrawler()

    # 1. دانلود صفحه دسته‌بندی
    category_html = await fetch_page(crawler, category_url)
    if not category_html:
        return

    # 2. استخراج لینک محصولات
    product_links = extract_product_links(category_html, base_url)
    print(f"Found {len(product_links)} products.")

    # 3. برای هر محصول، داده‌ها رو استخراج و در Supabase ذخیره کن
    for url in product_links:
        product_html = await fetch_page(crawler, url)
        if not product_html:
            continue
        product_data = extract_product_data(product_html)
        product_data["url"] = url

        # ذخیره در Supabase
        res = supabase.table("products").insert(product_data).execute()
        if res.status_code == 201:
            print(f"Inserted product: {product_data['name']}")
        else:
            print(f"Failed to insert product: {product_data['name']} - {res.data}")

if __name__ == "__main__":
    asyncio.run(main())
