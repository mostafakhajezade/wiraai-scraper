import asyncio
from crawl4ai import AsyncWebCrawler, BrowserConfig

start_urls = [
    "https://wiraa.ir/category/آرایشی-و-بهداشتی"
]

config = BrowserConfig(
    headless=True,
    verbose=True
)

crawler = AsyncWebCrawler(config=config)

async def main():
    for url in start_urls:
        await crawler.arun(url)

if __name__ == "__main__":
    asyncio.run(main())
