from crawl4ai import AsyncCrawler
import asyncio

async def main():
    crawler = AsyncCrawler()
    result = await crawler.crawl("https://wiraا.ir/category/آبمیوه-گیر")
    print(result.html)

asyncio.run(main())
