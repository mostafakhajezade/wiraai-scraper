import asyncio
from crawl4ai import AsyncWebCrawler

async def main():
    url = "https://wiraa.ir/category/آبمیوه-گیربگ"

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
        print("\n🔎 Raw result:", result)
        print("\n🔎 Dir result:", dir(result))
        print("\n🔎 Result as dict:", result.__dict__)

asyncio.run(main())
