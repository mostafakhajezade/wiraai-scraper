# file: crawler.py

import sys
sys.path.insert(0, './crawl4ai')

# crawler.py

from crawl4ai import AsyncWebCrawler, HTTPCrawlerConfig

config = HTTPCrawlerConfig(
    start_urls=["https://wiraa.ir/category/آرایشی-و-بهداشتی"],
    follow_url_patterns=[r"/category/.*", r"/product/.*"],
    max_pages=50,
)

crawler = AsyncWebCrawler(config=config)

if __name__ == "__main__":
    import asyncio

    async def main():
        results = await crawler.crawl()
        for result in results:
            print(result.url, result.content[:200])  # فقط بخشی از محتوای هر صفحه

    asyncio.run(main())
