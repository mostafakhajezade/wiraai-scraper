# file: crawler.py

from crawl4ai import AsyncWebCrawler, HTTPCrawlerConfig

start_urls = [
    "https://wiraa.ir/category/آرایشی-و-بهداشتی"
]

config = HTTPCrawlerConfig()

crawler = AsyncWebCrawler(
    config=config,
    start_urls=start_urls
)

if __name__ == "__main__":
    crawler.run()
