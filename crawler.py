import asyncio
from crawl4ai import AsyncWebCrawler

async def main():
    crawler = AsyncWebCrawler(
        start_urls=["https://wiraa.ir/category/آبمیوه-گیربگ"],
        max_pages=5,
        extract_rules={
            "products": {
                "selector": "div.styles__product___QFT8B",
                "type": "list",
                "children": {
                    "url": {"selector": "a.styles__link___12EyG", "attr": "href"},
                    "title": {"selector": "h2.styles__title___EVTlZ", "type": "text"},
                    "price": {"selector": "div.styles__price___1uiIp.js-price", "type": "text"}
                }
            }
        }
    )

    # پرینت متدها و ویژگی‌ها
    print(dir(crawler))

asyncio.run(main())
