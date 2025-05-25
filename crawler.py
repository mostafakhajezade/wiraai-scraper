import asyncio
from crawl4ai.async_webcrawler import AsyncWebCrawler, HTTPCrawlerConfig, Extractor

async def main():
    # آدرس صفحه دسته‌بندی که میخوای محصولا رو ازش بگیری
    start_url = "https://wiraa.ir/category/آبمیوه-گیربگ"

    # تنظیم استخراج داده ها: محصول داخل div با کلاس مخصوص، و استخراج موارد دلخواه
    extractor = Extractor(
        css_selector="div.styles__product___QFT8B",
        attributes={
            "url": "a.styles__link___12EyG::attr(href)",
            "title": "h2.styles__title___EVTlZ::text",
            "price": "div.styles__price___1uiIp.js-price::text"
        }
    )

    # تنظیمات کلی کرال
    config = HTTPCrawlerConfig(
        start_urls=[start_url],
        extractors=[extractor],
        # اگر بخوای محدودیت سرعت و تعداد صفحه بذاری، اینجا میشه اضافه کرد
        max_pages=5
    )

    crawler = AsyncWebCrawler(config=config)

    async for result in crawler.crawl():
        # اینجا می‌تونی اطلاعات هر محصول رو ببینی و ذخیره کنی
        print(result)

asyncio.run(main())
