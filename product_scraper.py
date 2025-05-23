
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://wiraa.ir"

def get_product_links(category_url, max_pages=2):
    links = []
    for page in range(1, max_pages + 1):
        url = f"{category_url}?page={page}"
        print(f"📄 Fetching: {url}")
        response = requests.get(url)
        if response.status_code != 200:
            break

        soup = BeautifulSoup(response.text, "html.parser")
        cards = soup.select("a.product-card__link")

        for card in cards:
            href = card.get("href")
            if href:
                full_url = BASE_URL + href
                links.append(full_url)

    return links


if __name__ == "__main__":
    category_url = "https://wiraa.ir/category/آرایشی-و-بهداشتی"
    product_links = get_product_links(category_url)
    print(f"✅ Found {len(product_links)} products")
    for link in product_links:
        print(link)

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://wiraa.ir"

def get_product_links(category_url, max_pages=2):
    links = []
    for page in range(1, max_pages + 1):
        url = f"{category_url}?page={page}"
        print(f"📄 Fetching: {url}")
        response = requests.get(url)
        if response.status_code != 200:
            break

        soup = BeautifulSoup(response.text, "html.parser")
        cards = soup.select("a.product-card__link")

        for card in cards:
            href = card.get("href")
            if href:
                full_url = BASE_URL + href
                links.append(full_url)

    return links


if __name__ == "__main__":
    category_url = "https://wiraa.ir/category/آرایشی-و-بهداشتی"
    product_links = get_product_links(category_url)
    print(f"✅ Found {len(product_links)} products")
    for link in product_links:
        print(link)