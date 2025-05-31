import os
import re
import math
import asyncio
from difflib import SequenceMatcher
from crawl4ai import AsyncWebCrawler
from bs4 import BeautifulSoup
from supabase import create_client, Client
from torob_integration.api import Torob
import openai

# ──────────────────────────────────────────────────────────────────────────────
# 1) SUPABASE (hard‐coded)
# ──────────────────────────────────────────────────────────────────────────────

# Replace these two lines with your actual Supabase project URL and service‐role key:
SUPABASE_URL = "https://djjmhfffusochizzkhqh.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRqam1oZmZmdXNvY2hpenpraHFoIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc0ODE4MjAwMiwiZXhwIjoyMDYzNzU4MDAyfQ._YkNr4oO5jQ2y-X4ggJjwcTZKphxyo8p4TkuPZCxNCA"

# Initialize Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# ──────────────────────────────────────────────────────────────────────────────
# 2) OPENROUTER (hard‐coded)
# ──────────────────────────────────────────────────────────────────────────────

# Replace this with your OpenRouter API key (you must create an account on openrouter.ai 
# and obtain a key from the dashboard).
OPENROUTER_API_KEY = "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"

# The OpenRouter base URL for OpenAI-compatible endpoints:
OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"

# Configure OpenAI client to point at OpenRouter
openai.api_key = OPENROUTER_API_KEY
openai.api_base = OPENROUTER_API_BASE

# ──────────────────────────────────────────────────────────────────────────────
# 3) Helpers: Persian digit conversion, fuzzy and semantic similarity
# ──────────────────────────────────────────────────────────────────────────────

def persian_to_english_numbers(text: str) -> str:
    """
    Convert Persian digits in `text` to English digits.
    """
    persian_digits = "۰۱۲۳۴۵۶۷۸۹"
    english_digits = "0123456789"
    return text.translate(str.maketrans(persian_digits, english_digits))


def similar(a: str, b: str) -> float:
    """
    Simple fuzzy similarity (Ratcliff/Obershelp) between two strings.
    """
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def get_embedding(text: str, model: str = "mistralai/devstral-small:free") -> list[float]:
    """
    Retrieve the embedding for a given `text` using the specified OpenRouter model.
    This wraps openai.Embedding.create(...) and returns the embedding vector.
    """
    # Note: the `model` string should exactly match one available on OpenRouter.
    response = openai.Embedding.create(
        model=model,
        input=text
    )
    # The OpenAI/Embeddings API returns a "data" list; each item has an "embedding" key.
    return response["data"][0]["embedding"]


def cosine_similarity(a_emb: list[float], b_emb: list[float]) -> float:
    """
    Compute the cosine similarity between two embedding vectors.
    """
    dot_product = sum(x * y for x, y in zip(a_emb, b_emb))
    norm_a = math.sqrt(sum(x * x for x in a_emb))
    norm_b = math.sqrt(sum(y * y for y in b_emb))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot_product / (norm_a * norm_b)


def semantic_score(a: str, b: str, model: str = "mistralai/devstral-small:free") -> float:
    """
    Compute a semantic similarity score between strings `a` and `b` by
    fetching their embeddings and taking cosine similarity.
    """
    emb_a = get_embedding(a, model=model)
    emb_b = get_embedding(b, model=model)
    return cosine_similarity(emb_a, emb_b)


# ──────────────────────────────────────────────────────────────────────────────
# 4) Crawl4AI fetch helper and HTML link‐extractor
# ──────────────────────────────────────────────────────────────────────────────

async def fetch_page(crawler: AsyncWebCrawler, url: str) -> str:
    """
    Use Crawl4AI to fetch a page at `url`. Return the raw HTML if successful,
    otherwise return an empty string.
    """
    res = await crawler.arun(url)
    if res.success:
        return res.html
    print(f"[ERROR] couldn't fetch {url}")
    return ""


def extract_links(html: str, selector: str, base_url: str) -> list[str]:
    """
    Given a chunk of HTML, find all `<a>` tags matching the CSS `selector`
    (e.g. "a[href^='/product/']").  Convert relative hrefs to absolute by
    prefixing `base_url`.  Return a deduplicated list of full URLs.
    """
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for a in soup.select(selector):
        href = a.get("href")
        if not href:
            continue
        # If href is already absolute (starts with "http"), keep it. Otherwise prepend base_url.
        full = href if href.startswith("http") else base_url.rstrip("/") + href
        if full not in links:
            links.append(full)
    return links


# ──────────────────────────────────────────────────────────────────────────────
# 5) Product data extractor (from Wiraa.ir product page)
# ──────────────────────────────────────────────────────────────────────────────

def extract_product_data(html: str) -> dict:
    """
    Parse a Wiraa.ir product page's HTML to extract:
      - name: the product title (inside <h1 data-product="title">…</h1>)
      - price: a numeric integer price (in Tomans)
    Returns a dictionary: {"name": str, "price": int}.
    """
    soup = BeautifulSoup(html, "html.parser")

    title_el = soup.select_one('h1[data-product="title"]')
    name = title_el.text.strip() if title_el else "No Name"

    price_el = soup.select_one("div.styles__price___1uiIp.js-price")
    raw_price = price_el.text.strip() if price_el else "0"
    # Remove any non‐digit characters (including Persian commas) and convert Persian digits→English.
    num_str = re.sub(r"[^\d]", "", persian_to_english_numbers(raw_price))
    price = int(num_str) if num_str else 0

    return {"name": name, "price": price}


# ──────────────────────────────────────────────────────────────────────────────
# 6) Main crawler logic
# ──────────────────────────────────────────────────────────────────────────────

async def main():
    base_url = "https://wiraa.ir"
    crawler = AsyncWebCrawler()
    torob = Torob()

    # Step 1) Fetch Wiraa.ir homepage, find category links
    home_html = await fetch_page(crawler, base_url)
    if not home_html:
        return

    categories = extract_links(home_html, "a[href^='/category/']", base_url)
    print(f"[INFO] Found {len(categories)} categories")

    # Step 2) Iterate through each category
    for cat_url in categories:
        print(f"\n[CATEGORY] {cat_url}")
        cat_html = await fetch_page(crawler, cat_url)
        if not cat_html:
            continue

        products = extract_links(cat_html, "a[href^='/product/']", base_url)
        print(f" → {len(products)} products found")

        # Step 3) For each product URL: scrape details, upsert into Supabase, then fetch Torob competitor prices
        for prod_url in products:
            product_html = await fetch_page(crawler, prod_url)
            if not product_html:
                continue

            # Extract name & price from Wiraa.ir page
            product = extract_product_data(product_html)
            product["url"] = prod_url

            # 3a) Upsert into `products` table (on conflict by URL)
            supabase.table("products") \
                .upsert(product, on_conflict="url") \
                .execute()

            # 3b) Immediately fetch the row back to retrieve its `id` (UUID primary key)
            res = supabase.table("products") \
                .select("id") \
                .eq("url", product["url"]) \
                .single() \
                .execute()
            # `res.data` will be a dict like {"id": "<uuid>"} if found.
            product_id = res.data["id"]
            print(f"  • Stored product: {product['name']}  (id={product_id})")

            # Step 4) Query Torob.com for competitor listings of the same product
            try:
                resp = torob.search(q=product["name"], page=0)
                torob_results = resp.get("results", [])
            except Exception as e:
                print(f"    ↳ Torob search error for '{product['name']}': {e}")
                continue

            # Step 5) Combine fuzzy + semantic filtering to pick top matches
            scored: list[tuple[float, dict]] = []
            for item in torob_results:
                name1 = item.get("name1", "")
                f_score = similar(name1, product["name"])
                try:
                    s_score = semantic_score(name1, product["name"])
                except Exception as sem_e:
                    # If embedding fails (e.g. rate‐limit or model not found), fallback to fuzzy
                    print(f"      [WARN] Semantic error: {sem_e}, falling back to fuzzy only")
                    s_score = 0.0
                combined = max(f_score, s_score)
                scored.append((combined, item))

            # Sort descending by combined score
            scored.sort(key=lambda x: x[0], reverse=True)
            top_matches = [it for _, it in scored[:5]]

            # Step 6) From the top 5, take the first 3 and extract store names & prices
            for candidate in top_matches[:3]:
                comp_price = candidate.get("price", 0)
                raw_shop = (candidate.get("shop_text") or "").strip()
                link_path = candidate.get("web_client_absolute_url") or candidate.get("more_info_url")
                seller = raw_shop if raw_shop else "unknown"

                # If Torob returned a "چند فروشگاه" (multi‐store) entry, follow that detail link
                if "فروشگاه" in raw_shop and link_path:
                    detail_url = link_path if link_path.startswith("http") else "https://torob.com" + link_path
                    detail_html = await fetch_page(crawler, detail_url)
                    if detail_html:
                        dsoup = BeautifulSoup(detail_html, "html.parser")
                        shops_list: list[str] = []
                        # Torob shop links have class "shop-name"
                        for a_tag in dsoup.select("a.shop-name"):
                            name_text = a_tag.get_text(strip=True).split(",")[0].strip()
                            if name_text and name_text not in shops_list:
                                shops_list.append(name_text)
                            if len(shops_list) == 3:
                                break
                        if shops_list:
                            seller = ", ".join(shops_list)

                # Step 7) Upsert into competitor_prices (foreign key = product_id)
                supabase.table("competitor_prices") \
                    .upsert({
                        "product_id": product_id,
                        "competitor_name": seller,
                        "competitor_price": comp_price
                    }, on_conflict="product_id,competitor_name") \
                    .execute()

                print(f"    ↳ {seller}: {comp_price}")


if __name__ == "__main__":
    asyncio.run(main())
