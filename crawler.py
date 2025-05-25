import asyncio
import re
from crawl4ai import AsyncWebCrawler, BrowserConfig, HTTPCrawlerConfig
from supabase import create_client, Client
from bs4 import BeautifulSoup

# تنظیمات سوپابیس
SUPABASE_URL = "https://xppiarnupitknpraqyjo.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhwcGlhcm51cGl0a25wcmFxeWpvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDgwODQyNjIsImV4cCI6MjA2MzY2MDI2Mn0.JIFkUNhH0OL2M8KRDsvvoyqke6_dFQqIgDWcTH5iz94"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def parse_price(price_str):
    digits = re.sub(r"[^\d]", "", price_str)
    return int(digits) if digits else None

def parse_availability(avail_str):
    return avail_str.strip() == "موجود"

async def crawl_product(crawler, url):
    print(f"Crawling product: {url}")
    result = await crawler.arun(url)
    soup = BeautifulSoup(result.html, "html.parser")

    name = soup.select_one("h1.product-name").text.strip() if soup.select_one("h1.product-name") else ""
    price = soup.select_one(".price").text.strip() if soup.select_one(".price") else ""
    availability = soup.select_one(".availability").text.strip() if soup.select_one(".availability") else ""

    price_num = parse_price(price)
    available = parse_availability(availability)

    data = {
        "url": url,
        "name": name,
        "price": price_num,
        "available": available,
    }
    print(f"Saving product: {data}")
    supabase.table("products").upsert(data, on_conflict="url").execute()

async def main():
    browser_config = BrowserConfig()
    browser_config.browser_type = "chromium"  # یا "firefox" یا "webkit"
    config = HTTPCrawlerConfig(browser_config=browser_config)
    crawler = AsyncWebCrawler(config=config)

    category_url = "https://wiraa.ir/category/آبمیوه-گیربگ"
    print(f"Crawling category page: {category_url}")
    result = await crawler.arun(category_url)
    soup = BeautifulSoup(result.html, "html.parser")

    product_links = set()
    # سلکتور لینک محصول رو متناسب با سایت خودتون تنظیم کنید:
    for a in soup.select("div.grid__container-12___3u-ry a"):
        href = a.attrs.get("href")
        if href and href.startswith("/product/"):
            full_url = "https://wiraa.ir" + href
            product_links.add(full_url)

    print(f"Found {len(product_links)} products")

    for url in product_links:
        await crawl_product(crawler, url)

if __name__ == "__main__":
    asyncio.run(main())
