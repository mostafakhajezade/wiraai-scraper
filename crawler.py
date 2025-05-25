import asyncio
import re
from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler, HTTPCrawlerConfig
from supabase import create_client, Client

# اتصال به Supabase
SUPABASE_URL = "https://xppiarnupitknpraqyjo.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhwcGlhcm51cGl0a25wcmFxeWpvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDgwODQyNjIsImV4cCI6MjA2MzY2MDI2Mn0.JIFkUNhH0OL2M8KRDsvvoyqke6_dFQqIgDWcTH5iz94"  # 👈 حواست باشه اینو ایمن نگه داری
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# تبدیل قیمت به عدد
def parse_price(price_str):
    digits = re.sub(r"[^\d]", "", price_str)
    return int(digits) if digits else None

def parse_availability(avail_str):
    return avail_str.strip() == "موجود"

# کرال کردن صفحه محصول
async def crawl_product(crawler, url):
    print(f"Crawling product: {url}")
    result = await crawler.arun(url)
    soup = BeautifulSoup(result.html, "html.parser")

    name = soup.select_one("h1.product-name")
    price = soup.select_one(".price")
    availability = soup.select_one(".availability")

    data = {
        "url": url,
        "name": name.text.strip() if name else "",
        "price": parse_price(price.text) if price else None,
        "available": parse_availability(availability.text) if availability else False,
    }
    print(f"Inserting: {data}")
    supabase.table("products").upsert(data, on_conflict="url").execute()

# کرال کردن لینک‌های یک دسته‌بندی
async def main():
    config = HTTPCrawlerConfig()
    crawler = AsyncWebCrawler(config=config)

    category_url = "https://wiraa.ir/category/آبمیوه-گیر"  # ← این لینک دسته‌بندی رو می‌تونی تغییر بدی
    result = await crawler.arun(category_url)
    soup = BeautifulSoup(result.html, "html.parser")

    # سلکتور کارت‌های محصول رو با توجه به سایتت تنظیم کن
    product_links = set()
    for a in soup.select("div.grid__container-12___3u-ry a"):
        href = a.get("href")
        if href and href.startswith("/product/"):
            product_links.add("https://wiraa.ir" + href)

    print(f"Found {len(product_links)} product links")
    for url in product_links:
        await crawl_product(crawler, url)

if __name__ == "__main__":
    asyncio.run(main())
