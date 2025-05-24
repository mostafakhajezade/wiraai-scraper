# file: crawler.py

import sys
sys.path.insert(0, './crawl4ai')

from crawl4ai.agent import CrawlAgent
from crawl4ai.plugins.extract import ExtractProduct
from crawl4ai.plugins.actions import ClickNextPage
from crawl4ai.plugins.browsing import VisitURLs
from crawl4ai.plugins.utils import SaveAsJSONLines

# لینک دسته‌بندی‌ها
CATEGORY_URLS = [
    "https://wiraa.ir/category/آرایشی-و-بهداشتی"
]

agent = CrawlAgent(
    name="wiraa-product-crawler",
    start_urls=CATEGORY_URLS,
    plugins=[
        VisitURLs(follow_links={"include": [r"/category/.*"]}),
        ClickNextPage(button_text="بعدی"),  # یا اگر کلاس خاصی داره با selector
        VisitURLs(follow_links={"include": [r"/product/.*"]}),
        ExtractProduct(selectors={
            "title": "h1.product_title",
            "price": ".price",
            "description": ".woocommerce-Tabs-panel--description",
        }),
        SaveAsJSONLines("products.jsonl"),
    ]
)

if __name__ == "__main__":
    agent.run()
