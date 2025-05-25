import asyncio
import re
from crawl4ai import AsyncHTTPCrawler
from crawl4ai import AsyncWebCrawler, HTTPCrawlerConfig
from supabase import create_client, Client
from bs4 import BeautifulSoup

# اتصال به Supabase
SUPABASE_URL = "https://xppiarnupitknpraqyjo.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhwcGlhcm51cGl0a25wcmFxeWpvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDgwODQyNjIsImV4cCI6MjA2MzY2MDI2Mn0.JIFkUNhH0OL2M8KRDsvvoyqke6_dFQqIgDWcTH5iz94"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def parse_price(price_str):
    digits = re.sub(r"[^\d]", "", price_str)
    return int(digits) if digits else None

def parse_availability(avail_str):
    return "موجود" in avail_str

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

    print(f"Saving product: {data}")
    supabase.table("products").upsert(data, on_conflict="url").execute()

async def main():
    crawler = AsyncHTTPCrawler()  # 👈 به جای AsyncWebCrawler از این استفاده کن

    category_url = "https://wiraa.ir/category/آبمیوه-گیربگ"
    print(f"Crawling category page: {category_url}")
    result = await crawler.arun(category_url)
    
    config = HTTPCrawlerConfig()
    config.verbose = True
    

    category_url = "https://wiraa.ir/category/آبمیوه-گیربگ"
    print(f"Crawling category page: {category_url}")
    result = await crawler.arun(category_url)
    soup = BeautifulSoup(result.html, "html.parser")

    # انتخاب همه لینک‌هایی که به محصولات اشاره دارند
    product_links = set()
    for a in soup.select('a[href^="/product/"]'):
        href = a.get("href")
        if href:
            product_links.add("https://wiraa.ir" + href)

    print(f"Found {len(product_links)} products")

    for url in product_links:
        await crawl_product(crawler, url)

if __name__ == "__main__":
    asyncio.run(main())
