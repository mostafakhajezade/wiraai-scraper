import os
from torob_integration.api import Torob
from supabase import create_client

# Supabase settings from environment
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# List of your product slugs (last segment of product URLs)
# You can auto-extract slugs from your existing crawler output URLs:
# Example: if you have a list of full URLs, use:
#
#   full_urls = [
#       "https://wiraa.ir/product/آبمیوه-گیر-Green-lion-مدل-MEGA-PRO",
#       "https://wiraa.ir/product/تیغ-اصلاح-گرین-لاین",
#       # ...
#   ]
#   PRODUCT_SLUGS = [url.rsplit('/product/', 1)[1] for url in full_urls]
#
# Or manually list them:
PRODUCT_SLUGS = [
    # e.g. "آبمیوه-گیر-Green-lion-مدل-MEGA-PRO",
    # "تیغ-اصلاح-گرین-لاین",
]

# Upsert a competitor price record
def upsert_competitor_price(slug: str, seller: str, price: int):
    supabase.table("competitor_prices").upsert(
        {
            "product_slug": slug,
            "competitor_name": seller,
            "competitor_price": price,
        },
        on_conflict="product_slug,competitor_name"
    ).execute()

# Fetch from Torob and store
def fetch_and_store():
    torob = Torob()
    for slug in PRODUCT_SLUGS:
        results = torob.search(slug, page=0)
        for item in results.get("results", []):
            seller = item.get("seller_name")
            price  = int(item.get("price", 0))
            print(f"[{slug}] {seller} → {price}")
            upsert_competitor_price(slug, seller, price)

if __name__ == "__main__":
    fetch_and_store()