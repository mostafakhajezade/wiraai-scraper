from crawl4ai import crawl

async def main():
    result = await crawl("https://wiraa.ir/category/آبمیوه-گیر")
    print(result.html)  # چاپ کل HTML صفحه
