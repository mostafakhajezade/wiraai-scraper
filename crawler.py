import asyncio
import re
from crawl4ai import AsyncWebCrawler, BrowserCrawlerConfig
from supabase import create_client, Client
from bs4 import BeautifulSoup

SUPABASE_URL = "https://xppiarnupitknpraqyjo.supabase.co"
SUPABASE_KEY = "YOUR_SUPABASE_KEY"
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
    config = BrowserCrawlerConfig()
    config.verbose = True
    crawler = AsyncWebCrawler(config=config)

    category_url = "https://wiraa.ir/category/آبمیوه-گیربگ"

    print(f"Crawling category page: {category_url}")
    result = await crawler.arun(category_url)
    soup = BeautifulSoup(result.html, "html.parser")

    product_links = set()
    for a in soup.select("a.product-link"):
        href = a.attrs.get("href")
        if href and href.startswith("/product/"):
            full_url = "https://wiraa.ir" + href
            product_links.add(full_url)

    print(f"Found {len(product_links)} products")

    for url in product_links:
        await crawl_product(crawler, url)

if __name__ == "__main__":
    asyncio.run(main())
