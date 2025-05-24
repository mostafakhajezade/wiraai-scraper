# file: crawler.py

import asyncio
from crawl4ai import AsyncWebCrawler, BrowserConfig

start_urls = [
    "https://wiraa.ir/category/آرایشی-و-بهداشتی"
]

config = BrowserConfig(
    headless=True,
    verbose=True
)

crawler = AsyncWebCrawler(
    config=config,
    start_urls=start_urls
)

if __name__ == "__main__":
    asyncio.run(crawler.arun())
