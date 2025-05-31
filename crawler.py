import os
import re
import asyncio
import math
from difflib import SequenceMatcher
from crawl4ai import AsyncWebCrawler
from bs4 import BeautifulSoup
from supabase import create_client, Client
from torob_integration.api import Torob
from openai import OpenAI

# ─── Supabase Setup ───
SUPABASE_URL             = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY env var")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# ─── OpenRouter Setup ───
OPENROUTER_API_URL = os.getenv("OPENROUTER_API_URL")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
if not OPENROUTER_API_URL or not OPENROUTER_API_KEY:
    raise RuntimeError("Missing OPENROUTER_API_URL or OPENROUTER_API_KEY env var")

# Initialize an OpenAI client that points at OpenRouter
oai = OpenAI(api_key=OPENROUTER_API_KEY, api_base=OPENROUTER_API_URL)

# ─── Helpers ───

def persian_to_english_numbers(text: str) -> str:
    """Convert Persian digits in `text` to ASCII digits."""
    persian = "۰۱۲۳۴۵۶۷۸۹"
    english = "0123456789"
    return text.translate(str.maketrans(persian, english))

def similar(a: str, b: str) -> float:
    """Fallback fuzzy similarity via difflib.SequenceMatcher."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = 0.0
    norm1 = 0.0
    norm2 = 0.0
    for x, y in zip(vec1, vec2):
        dot += x * y
        norm1 += x * x
        norm2 += y * y
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (math.sqrt(norm1) * math.sqrt(norm2))

def get_embedding_via_openrouter(text: str, model_name: str) -> list[float]:
    """
    Query OpenRouter’s embeddings endpoint using the specified model_name
    (e.g. "mistralai/devstral-small:free"). Returns a single embedding vector.
    """
    # The OpenAI‐py client exposes an `embeddings.create(...)` method
    resp = oai.embeddings.create(
        model=model_name,
        input=[text]
    )
    # The response’s `.data` is a list of { index: int, embedding: [...] }. We asked for one input, so index=0.
    return resp["data"][0]["embedding"]

def semantic_score(a: str, b: str) -> float:
    """
    Compute semantic similarity between strings `a` and `b` by:
      1) retrieving each embedding from OpenRouter (“mistralai/devstral-small:free”)
      2) computing cosine similarity of the two embedding vectors.
    """
    emb_a = get_embedding_via_openrouter(a, model_name="mistralai/devstral-small:free")
    emb_b = get_embedding_via_openrouter(b, model_name="mistralai/devstral-small:free")
    return cosine_similarity(emb_a, emb_b)

async def fetch_page(crawler: AsyncWebCrawler, url: str) -> str:
    """Use Crawl4AI to fetch a page’s HTML. Returns empty string on failure."""
    res = await crawler.arun(url)
    if res.success:
        return res.html
    print(f"[ERROR] couldn’t fetch {url}")
    return ""

def extract_links(html: str, selector: str, base_url: str) -> list[str]:
    """
    Given some HTML and a CSS selector (e.g. "a[href^='/category/']"),
    return a deduped list of absolute URLs.
    """
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for a in soup.select(selector):
        href = a.get("href")
        if not href:
            continue
        full = href if href.startswith("http") else base_url.rstrip("/") + href
        if full not in links:
            links.append(full)
    return links

def extract_product_data(html: str) -> dict:
    """
    Parse a Wiraa product page’s HTML and return a dict:
      { "name": <product name>, "price": <integer price in Toman> }
    """
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one('h1[data-product="title"]')
    name = title_el.text.strip() if title_el else "No Name"
    price_el = soup.select_one("div.styles__price___1uiIp.js-price")
    raw_price = price_el.text.strip() if price_el else "0"
    digits_only = re.sub(r"[^\d]", "", persian_to_english_numbers(raw_price))
    price_int = int(digits_only) if digits_only else 0
    return {"name": name, "price": price_int}

# ─── Main crawler logic ───

async def main():
    base_url = "https://wiraa.ir"
    crawler = AsyncWebCrawler()
    torob = Torob()

    # Step 1: Fetch homepage, find category links
    home_html = await fetch_page(crawler, base_url)
    if not home_html:
        return
    categories = extract_links(home_html, "a[href^='/category/']", base_url)
    print(f"[INFO] Found {len(categories)} categories on the homepage.")

    # Step 2: For each category page, scrape product links
    for cat_url in categories:
        print(f"\n[CATEGORY] {cat_url}")
        cat_html = await fetch_page(crawler, cat_url)
        if not cat_html:
            continue

        product_links = extract_links(cat_html, "a[href^='/product/']", base_url)
        print(f" → Found {len(product_links)} products in this category.")

        for prod_url in product_links:
            # Step 3: Fetch the product page and extract name + price
            prod_html = await fetch_page(crawler, prod_url)
            if not prod_html:
                continue

            product = extract_product_data(prod_html)
            product["url"] = prod_url  # use URL as the unique key

            # Upsert into `products` table (on conflict, uses `url` to decide)
            supabase.table("products").upsert(product, on_conflict="url").execute()

            # Step 4: Retrieve the newly‐inserted (or updated) product’s ID
            row = (
                supabase.table("products")
                .select("id")
                .eq("url", product["url"])
                .single()
                .execute()
            )

            # In supabase‐py v2, `.single().execute()` yields a SingleAPIResponse with `.data`
            if not row.data:
                print(f"    [WARN] Could not retrieve ID for {product['url']}")
                continue

            product_id = row.data["id"]
            print(f"  • Stored product: {product['name']}  (id={product_id})")

            # Step 5: Query Torob for competitor listings
            try:
                resp = torob.search(q=product["name"], page=0)
                torob_results = resp.get("results", [])
            except Exception as e:
                print(f"    ↳ Torob search error for '{product['name']}': {e}")
                continue

            # Step 6: Score each Torob result by either fuzzy‐score or semantic‐score
            scored: list[tuple[float, dict]] = []
            for it in torob_results:
                name1 = it.get("name1", "")
                f_score = similar(name1, product["name"])
                s_score = semantic_score(name1, product["name"])
                combined = max(f_score, s_score)
                scored.append((combined, it))
            scored.sort(key=lambda x: x[0], reverse=True)

            # Keep the top 5 matches by combined score
            top_matches = [item for _, item in scored[:5]]

            # Step 7: From those top matches, upsert up to 3 competitor_price rows
            for item in top_matches[:3]:
                comp_price = item.get("price", 0)
                raw_shop   = (item.get("shop_text") or "").strip()
                link_path  = item.get("web_client_absolute_url") or item.get("more_info_url")
                seller     = raw_shop or "unknown"

                # If the Torob listing says “در X فروشگاه” (multi‐store), follow that detail page
                if "فروشگاه" in raw_shop and link_path:
                    detail_url = (
                        link_path if link_path.startswith("http")
                        else "https://torob.com" + link_path
                    )
                    detail_html = await fetch_page(crawler, detail_url)
                    if detail_html:
                        dsoup = BeautifulSoup(detail_html, "html.parser")
                        shops: list[str] = []
                        for a_tag in dsoup.select("a.shop-name"):
                            name_text = a_tag.get_text(strip=True).split(",")[0].strip()
                            if name_text and name_text not in shops:
                                shops.append(name_text)
                            if len(shops) == 3:
                                break
                        if shops:
                            seller = ", ".join(shops)

                # Step 8: Upsert into competitor_prices (use product_id as FK)
                supabase.table("competitor_prices").upsert(
                    {
                        "product_id":       product_id,
                        "competitor_name":  seller,
                        "competitor_price": comp_price,
                    },
                    on_conflict="product_id,competitor_name"
                ).execute()

                print(f"    ↳ {seller}: {comp_price}")

if __name__ == "__main__":
    asyncio.run(main())
