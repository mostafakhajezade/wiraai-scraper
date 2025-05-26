import asyncio
from crawl4ai import AsyncWebCrawler
from bs4 import BeautifulSoup
from supabase import create_client, Client
import os
import re

# --- تنظیمات Supabase ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- تبدیل اعداد فارسی به انگلیسی ---
def persian_to_english_numbers(text: str) -> str:
    persian_nums = "۰۱۲۳۴۵۶۷۸۹"
    english_nums = "0123456789"
    translation_table = str.maketrans(persian_nums, english_nums)
    return text.translate(translation_table)

# --- دریافت HTML یک صفحه ---
async def fetch_page(crawler, url: str) -> str:
    result = await crawler.arun(url)
    if result.success:
        return result.html
    else:
        print(f"[ERROR] Failed to fetch {url}")
        return ""

# --- گرفتن لینک دسته‌بندی‌ها ---
def extract_category_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.select("a[href^='/category/']"):
        href = a.get("href")
        full_url = base_url.rstrip("/") + href
        if full_url not in links:
            links.append(full_url)
    return links

# --- گرفتن لینک محصولات ---
def extract_product_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.select("a[href^='/product/']"):
        href = a.get("href")
        full_url = base_url.rstrip("/") + href
        if full_url not in links:
            links.append(full_url)
    return links

# --- گرفتن اطلاعات یک محصول ---
def extract_product_data(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    # اصلاح سلکتور نام محصول با توجه به نمونه HTML
    name_tag = soup.select_one('h1[data-product="title"].styles__title___1LiMX')
    name = name_tag.text.strip() if name_tag else "No Name"

    price_tag = soup.select_one("div.styles__price___1uiIp.js-price")
    price_text = price_tag.text.strip() if price_tag else "0"
    price = re.sub(r"[^\d]", "", persian_to_english_numbers(price_text))

    return {"name": name, "price": price}

# --- تابع اصلی ---
async def main():
    base_url = "https://wiraa.ir"
    crawler = AsyncWebCrawler()

    # گرفتن لیست دسته‌بندی‌ها
    homepage_html = await fetch_page(crawler, base_url)
    if not homepage_html:
        return

    category_links = extract_category_links(homepage_html, base_url)
    print(f"[INFO] Found {len(category_links)} categories.\n")

    for category_url in category_links:
        print(f"[CATEGORY] {category_url}")
        cat_html = await fetch_page(crawler, category_url)
        if not cat_html:
            continue

        product_links = extract_product_links(cat_html, base_url)
        print(f"  └─ Found {len(product_links)} products.")

        for url in product_links:
            html = await fetch_page(crawler, url)
            if not html:
                continue

            product = extract_product_data(html)
            product["url"] = url

            # چاپ عنوان و لینک مربوط به همان محصول
            print(f"    → {product['name']} ({url})")

            # بررسی تکراری بودن
            try:
                existing = supabase.table("products").select("id").eq("url", url).execute()
                if existing.data:
                    print(f"      ↳ Skipped (duplicate)\n")
                    continue

                supabase.table("products").insert(product).execute()
                print(f"      ↳ Inserted ✅\n")

            except Exception as e:
                print(f"      ↳ Failed ❌: {e}\n")

if __name__ == "__main__":
    asyncio.run(main())
