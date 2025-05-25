import asyncio
from crawl4ai import AsyncWebCrawler
from urllib.parse import quote

async def main():
    category = "آبمیوه-گیربگ"
    url = f"https://wiraa.ir/category/{quote(category)}"

    crawler = AsyncWebCrawler(
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

    results = await crawler.arun(url)

    for result in results:
        print(result.html[:1000])  # نمایش بخش کوچکی از HTML برای بررسی سریع

asyncio.run(main())
