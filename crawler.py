import asyncio
from crawl4ai.async_webcrawler import AsyncWebCrawler, Extractor
from crawl4ai.config import HTTPCrawlerConfig

async def main():
    start_url = "https://wiraa.ir/category/آبمیوه-گیربگ"

    extractor = Extractor(
        css_selector="div.styles__product___QFT8B",
        attributes={
            "url": "a.styles__link___12EyG::attr(href)",
            "title": "h2.styles__title___EVTlZ::text",
            "price": "div.styles__price___1uiIp.js-price::text"
        }
    )

    config = HTTPCrawlerConfig(
        start_urls=[start_url],
        extractors=[extractor],
        max_pages=5
    )

    crawler = AsyncWebCrawler(config=config)

    async for result in crawler.crawl():
        print(result)

asyncio.run(main())
